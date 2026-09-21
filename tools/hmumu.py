#!/usr/bin/env python3
"""Small, discoverable command line interface for the H->mumu framework."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tools.variable_catalog import (
    configured_in,
    definitions_for,
    dependency_names,
    discover_definitions,
)


DEFAULT_ERAS = ("2022", "2022EE", "2023", "2023BPix", "2024", "2025")
DEFAULT_INPUT = "/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4"
DEFAULT_MANIFESTS = "/eos/user/v/vdamante/H_mumu/manifests_skim_v4"
DEFAULT_OUTPUT_BASE = "/eos/user/v/vdamante/H_mumu"
DEFAULT_TEST_OUTPUT_BASE = "/tmp/vdamante/hmumu_tests"
DEFAULT_SYSTEMATICS = ("Central", "JERC", "Muon", "PDF", "PU", "QCDScale", "ScaRe")
DEFAULT_RUN2_3_ERAS = ("Run3_2022", "Run3_2022EE", "Run3_2023", "Run3_2023BPix")
# Keep the default histogram campaign aligned with the datasets actually
# produced by each era's config/<era>/skim_cfg.yaml.  Explicit --datasets
# values remain available for specialised campaigns.
DEFAULT_GROUPS = "skim_cfg"
DEFAULT_MC_GROUPS = (
    "DiTriBoson,DY_amcatnlo,DY_amcatnlo_105_160,EWK,"
    "signals,SingleH,SingleTop,TTX,TT,W"
)
SOURCE_SUFFIXES = {".py", ".cc", ".cpp", ".h", ".hpp", ".yaml", ".yml", ".toml"}
IGNORED_PARTS = {".git", "soft", "__pycache__", "results"}


def normalized_era(value: str) -> str:
    return value if value.startswith("Run3_") else f"Run3_{value}"


def csv_or_repeated(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        result.extend(item.strip() for item in value.split(",") if item.strip())
    return result


def shell_join(command: Iterable[str]) -> str:
    return shlex.join(str(item) for item in command)


def root_files_by_relative_path(directory: Path) -> dict[Path, Path]:
    if not directory.is_dir():
        return {}
    return {
        path.relative_to(directory): path
        for path in sorted(directory.rglob("*.root"))
        if (
            path.is_file()
            and path.stat().st_size > 0
            and not any(part.endswith("_tmp") for part in path.relative_to(directory).parts)
        )
    }


def run_hadd_plan(
    jobs: list[tuple[Path, list[Path]]], *, execute: bool, overwrite: bool,
    skip_errors: bool = False,
) -> int:
    if not jobs:
        print("No non-empty ROOT inputs found.", file=sys.stderr)
        return 1
    for index, (output, inputs) in enumerate(jobs, start=1):
        command = ["hadd"]
        if overwrite:
            command.append("-f")
        if skip_errors:
            command.append("-k")
        command += [str(output), *(str(path) for path in inputs)]
        print(f"[{index}/{len(jobs)}] {shell_join(command)}", flush=True)
        if execute:
            output.parent.mkdir(parents=True, exist_ok=True)
            completed = subprocess.run(command, cwd=REPO, check=False)
            if completed.returncode:
                return completed.returncode
    if not execute:
        print("\nPlan only: add --run to execute.")
    return 0


def run_merge_eras(args: argparse.Namespace) -> int:
    base = Path(args.input_dir).expanduser()
    era_values = args.eras or [",".join(DEFAULT_RUN2_3_ERAS)]
    eras = [normalized_era(era) for era in csv_or_repeated(era_values)]
    output_era = normalized_era(args.output_era)
    sources = {
        era: root_files_by_relative_path(base / era)
        for era in eras
    }
    dy_mll_pattern = re.compile(
        r"^DYto2Mu_MLL105To160(?:_combined)?"
        r"(?P<suffix>_(?:0J|1J_Hard|1J_PU|2J_Hard|2J_PU1|2J_PU2))?\.root$"
    )
    relative_paths = sorted({relative for files in sources.values() for relative in files})
    combine_dy_mll_generations = getattr(
        args, "combine_dy_mll_generations", False
    )
    if combine_dy_mll_generations:
        relative_paths = [
            relative
            for relative in relative_paths
            if dy_mll_pattern.fullmatch(relative.name) is None
        ]
    jobs = [
        (
            base / output_era / relative,
            [sources[era][relative] for era in eras if relative in sources[era]],
        )
        for relative in relative_paths
    ]
    if combine_dy_mll_generations:
        suffixes = ("", "_0J", "_1J_Hard", "_1J_PU", "_2J_Hard", "_2J_PU1", "_2J_PU2")
        for suffix in suffixes:
            output_relative = Path(f"DYto2Mu_MLL105To160{suffix}.root")
            inputs = []
            for era in eras:
                input_path = sources[era].get(
                    Path(f"DYto2Mu_MLL105To160{suffix}.root")
                ) or sources[era].get(
                    Path(f"DYto2Mu_MLL105To160_combined{suffix}.root")
                )
                if input_path is not None:
                    inputs.append(input_path)
            if inputs:
                jobs.append((base / output_era / output_relative, inputs))
    if getattr(args, "missing_only", False):
        existing = sum(output.is_file() and output.stat().st_size > 0 for output, _ in jobs)
        jobs = [
            (output, inputs)
            for output, inputs in jobs
            if not output.is_file() or output.stat().st_size == 0
        ]
        if not jobs:
            print(
                f"All {existing} merged-era ROOT output(s) already exist; "
                "nothing to do."
            )
            return 0
        jobs.sort(key=lambda job: str(job[0]))
        print(
            "DY MLL 105-160 routing: canonical output name for every era"
        )
    print(f"Merging eras {', '.join(eras)} -> {base / output_era}")
    if not args.execute:
        return run_hadd_plan(jobs, execute=False, overwrite=args.force)
    from common.merge_era_templates import complete_era_shapes
    nominal_base = Path(args.nominal_dir) if getattr(args, 'nominal_dir', None) else base
    import tempfile
    for output, inputs in jobs:
        if output.exists() and not args.force:
            raise FileExistsError(output)
        if output.resolve() in {p.resolve() for p in inputs}:
            raise ValueError('Merged output cannot overwrite a physical era')
        output.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix='.era_merge_', suffix='.root', dir=output.parent)
        os.close(fd)
        temporary = Path(temporary)
        try:
            status = run_hadd_plan([(temporary, inputs)], execute=True, overwrite=True,
                                   skip_errors=getattr(args, 'skip_errors', False))
            if status:
                return status
            nominals = [nominal_base / p.relative_to(base) for p in inputs]
            complete_era_shapes(temporary, inputs, nominals)
            os.replace(temporary, output)
        finally:
            temporary.unlink(missing_ok=True)
    return 0 if jobs else 1


def run_hadd_processes(args: argparse.Namespace) -> int:
    input_dir = Path(args.input_dir).expanduser()
    output_dir = (
        Path(args.output_dir).expanduser()
        if args.output_dir
        else input_dir.with_name(f"{input_dir.name}_hadded")
    )
    eras = [normalized_era(era) for era in csv_or_repeated(args.eras)]
    commands: list[list[str]] = []
    for era in eras:
        command = [
            sys.executable,
            str(REPO / "histograms/hadd_hists_to_processes.py"),
            "--input-dir",
            str(input_dir / era),
            "--output-dir",
            str(output_dir / era),
            "--era",
            era,
        ]
        if args.add_derived_systs:
            command.append("--add-derived-systs")
        if getattr(args, "missing_only", False):
            command.append("--missing-only")
        commands.append(command)

    for index, command in enumerate(commands, start=1):
        print(f"[{index}/{len(commands)}] {shell_join(command)}", flush=True)
        if args.execute:
            completed = subprocess.run(command, cwd=REPO, check=False)
            if completed.returncode:
                return completed.returncode
    if not args.execute:
        print("\nPlan only: add --run to execute.")
    return 0


def run_check_hists(args: argparse.Namespace) -> int:
    command = [
        sys.executable,
        str(REPO / "tools/check_missing_histograms.py"),
        args.folder,
    ]
    for era in args.eras or []:
        command += ["--era", era]
    for systematic in args.systematics or []:
        command += ["--systematics", systematic]
    for group in args.groups or []:
        command += ["--group", group]
    for dataset in args.datasets or []:
        command += ["--dataset", dataset]
    for process in args.processes or []:
        command += ["--process", process]
    if args.datasets_file:
        command += ["--datasets-file", args.datasets_file]
    if args.suffix:
        command += ["--suffix", args.suffix]
    if args.exact:
        command.append("--exact")
    if args.json:
        command.append("--json")
    if args.show_unexpected:
        command.append("--show-unexpected")
    return subprocess.run(command, cwd=REPO, check=False).returncode


def run_plot(args: argparse.Namespace) -> int:
    regions = csv_or_repeated(args.regions)
    variables = csv_or_repeated(args.variables or [])
    commands = []
    for region in regions:
        command = [
            sys.executable,
            str(REPO / "plotting_tools/hist_plotter.py"),
            "--era",
            normalized_era(args.era),
            "--input",
            args.input_dir,
            "--output",
            args.output_dir,
            "--region",
            region,
            "--samples",
            *args.samples,
        ]
        if variables:
            command += ["--vars", ",".join(variables)]
        for systematic_group in getattr(args, "systematic_groups", None) or []:
            command += ["--systematicGroup", systematic_group]
        for systematic_input in getattr(args, "systematic_inputs", None) or []:
            command += ["--systematic-input", systematic_input]
        for enabled, option in (
            (args.systematics, "--systematics"),
            (getattr(args, "overlay_systematic", False), "--overlaySystematic"),
            (getattr(args, "total_systematics", False), "--totalSystematics"),
            (args.want_data, "--wantData"),
            (args.log_y, "--wantLogY"),
            (getattr(args, "log_uncertainties", False), "--logUncertainties"),
            (args.rebin, "--rebin"),
            (args.normalize_dy_to_data, "--normalize-dy-to-data"),
            (args.normalize_mc_to_data, "--normalize-mc-to-data"),
            (getattr(args, "component_composition", False), "--component-composition"),
        ):
            if enabled:
                command.append(option)
        if args.dy_normalization_sample:
            command += [
                "--dy-normalization-sample",
                args.dy_normalization_sample,
            ]
        if getattr(args, "dy_012j_weights", "none") != "none":
            command += ["--dy-012j-weights", args.dy_012j_weights]
        if not getattr(args, "mc_stat_uncertainty", True):
            command.append("--noMCStatUncertainty")
        commands.append(command)

    for index, command in enumerate(commands, start=1):
        print(f"[{index}/{len(commands)}] {shell_join(command)}", flush=True)
        if args.execute:
            completed = subprocess.run(command, cwd=REPO, check=False)
            if completed.returncode:
                return completed.returncode
    if not args.execute:
        print("\nPlan only: add --run to create the plots.")
    return 0


def systematic_directory(central_dir: Path, systematic: str) -> Path:
    if central_dir.name.endswith("_Central_hadded"):
        prefix = central_dir.name.removesuffix("_Central_hadded")
        return central_dir.with_name(f"{prefix}_{systematic}_hadded")
    if central_dir.name.endswith("_Central"):
        return central_dir.with_name(
            f"{central_dir.name.removesuffix('_Central')}_{systematic}"
        )
    if systematic == "Central":
        return central_dir
    return central_dir.with_name(f"{central_dir.name}_{systematic}")


def run_merge_systematics(args: argparse.Namespace) -> int:
    central_dir = Path(args.central_dir).expanduser()
    systematic_values = args.systematics or [",".join(DEFAULT_SYSTEMATICS)]
    systematics = csv_or_repeated(systematic_values)
    requested_eras = {
        normalized_era(era)
        for era in csv_or_repeated(args.eras or [])
    }
    if getattr(args, "source_dirs", None):
        source_dirs = {"Central": central_dir}
        source_dirs.update(
            {f"source_{index}": Path(path).expanduser()
             for index, path in enumerate(args.source_dirs, start=1)}
        )
        systematics = list(source_dirs)
    else:
        source_dirs = {
            systematic: systematic_directory(central_dir, systematic)
            for systematic in systematics
        }
    sources = {
        systematic: {
            relative: path
            for relative, path in root_files_by_relative_path(directory).items()
            if not requested_eras or relative.parts[0] in requested_eras
        }
        for systematic, directory in source_dirs.items()
    }
    relative_paths = sorted({relative for files in sources.values() for relative in files})
    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser()
    elif central_dir.name.endswith("_Central_hadded"):
        output_dir = central_dir.with_name(
            f"{central_dir.name.removesuffix('_Central_hadded')}_merged_hadded"
        )
    elif central_dir.name.endswith("_Central"):
        output_dir = central_dir.with_name(
            f"{central_dir.name.removesuffix('_Central')}_merged"
        )
    else:
        output_dir = central_dir.with_name(f"{central_dir.name}_merged")
    jobs = [
        (
            output_dir / relative,
            [
                sources[systematic][relative]
                for systematic in systematics
                if relative in sources[systematic]
            ],
        )
        for relative in relative_paths
    ]
    print("Systematic inputs:")
    for systematic, directory in source_dirs.items():
        print(f"  {systematic:10} {directory}")
    if requested_eras:
        print(f"Eras: {', '.join(sorted(requested_eras))}")
    print(f"Output: {output_dir}")
    return run_hadd_plan(jobs, execute=args.execute, overwrite=args.force)


@dataclass(frozen=True)
class HistRequest:
    eras: list[str]
    systematics: list[str]
    datasets: str | None
    dataset_name: str | None
    variables: list[str]
    regions: list[str]
    categories: list[str]
    input_dir: str
    manifests: str
    output_base: str
    output_dir: str | None
    chunk_size: int
    cores: int
    retries: int
    retry_delay: float
    condor: bool
    missing_only: bool
    dry_run: bool
    execute: bool
    dy_jet_components: bool
    jet_component_processes: list[str]
    vbf_eta_regions: bool
    max_files: int | None
    extra: list[str]
    dnn_model_set: str = "updated"
    overwrite: bool = False


def output_dir_for(request: HistRequest, systematic: str) -> str:
    if request.output_dir:
        if len(request.systematics) != 1:
            raise ValueError("--output-dir can only be used with one systematic")
        return request.output_dir
    output_base = (
        DEFAULT_TEST_OUTPUT_BASE
        if request.max_files is not None
        and request.output_base == DEFAULT_OUTPUT_BASE
        else request.output_base
    )
    return str(Path(output_base) / f"Hists_{systematic}")


def is_data_dataset_name(dataset_name: str) -> bool:
    """Recognize the explicit data dataset names used by Run 3 campaigns."""
    return bool(re.match(r"^(?:Data(?:_|$)|Muon\d?_|SingleMuon_)", dataset_name, re.I))


def datasets_for_systematic(request: HistRequest, systematic: str) -> tuple[str | None, str | None]:
    """Return (dataset name, dataset groups), excluding data from shifted jobs."""
    if systematic.lower() == "central":
        return request.dataset_name, request.datasets or DEFAULT_GROUPS
    if request.dataset_name:
        if is_data_dataset_name(request.dataset_name):
            raise ValueError(
                f"data dataset {request.dataset_name!r} cannot be run with shifted "
                f"systematic {systematic!r}"
            )
        return request.dataset_name, None
    requested = csv_or_repeated([request.datasets or DEFAULT_MC_GROUPS])
    mc_groups = [group for group in requested if group.lower() != "data"]
    if not mc_groups:
        raise ValueError(
            f"shifted systematic {systematic!r} has no MC dataset groups after "
            "excluding data"
        )
    return None, ",".join(mc_groups)


def histogram_command(request: HistRequest, era: str, systematic: str) -> list[str]:
    is_central = systematic.lower() == "central"
    script = (
        REPO / "histograms/scripts/hists.sh"
        if is_central
        else REPO / "histograms/scripts/systematics.sh"
    )
    command = [
        "bash",
        str(script),
        "--era",
        normalized_era(era),
    ]
    dataset_name, dataset_groups = datasets_for_systematic(request, systematic)
    if dataset_name:
        command += ["--dataset-name", dataset_name]
    else:
        command += ["--datasets", dataset_groups]
    command += [
        "--manifest-input-folder",
        request.manifests,
        "--input-folder",
        request.input_dir,
        "--root-input-folder",
        request.input_dir,
        "--output-dir",
        output_dir_for(request, systematic),
        "--systematics",
        systematic,
        "--chunk-size",
        str(request.chunk_size),
        "--file-open-retries",
        str(request.retries),
        "--file-open-retry-delay",
        str(request.retry_delay),
    ]
    if request.missing_only:
        command.append("--missing-only")
    if request.condor:
        command.append("--condor")
    if request.overwrite:
        command.append("--erase-existing")
    if request.dry_run:
        command.append("--dry-run")

    # The legacy separator is deliberately hidden from users of this CLI.
    command.append("--")
    if request.variables:
        command += ["--variables", *request.variables]
    if request.regions:
        command += ["--mass-regions", *request.regions]
    if request.categories:
        command += ["--categories", *request.categories]
    if request.dy_jet_components:
        command.append("--pu-hard-jet-components")
        if request.jet_component_processes:
            command += [
                "--pu-hard-processes",
                *request.jet_component_processes,
            ]
    if request.vbf_eta_regions:
        command.append("--eta-components")
    if request.max_files is not None:
        command += ["--max-files", str(request.max_files)]
    command += ["--dnn-model-set", request.dnn_model_set]

    command += request.extra
    return command


def report_temporary_histograms(output_dir: str, era: str) -> None:
    era_dir = Path(output_dir) / normalized_era(era)
    temporary_dirs = sorted(
        path for path in era_dir.glob("*_tmp") if path.is_dir()
    ) if era_dir.is_dir() else []
    if not temporary_dirs:
        print(f"[TMP]   {era_dir}: none")
        return
    print(f"[TMP]   {era_dir}: {len(temporary_dirs)} temporary dataset(s)")
    for temporary_dir in temporary_dirs:
        dataset = temporary_dir.name.removesuffix("_tmp")
        final_file = era_dir / f"{dataset}.root"
        chunks = sum(1 for _ in temporary_dir.glob("chunk_*.root"))
        final_status = "final-present" if final_file.is_file() and final_file.stat().st_size else "final-missing"
        print(f"  - {dataset}: {chunks} chunk(s), {final_status}")


def run_hist(args: argparse.Namespace) -> int:
    check_only = bool(args.check)
    request = HistRequest(
        eras=csv_or_repeated(args.era),
        systematics=csv_or_repeated(args.systematics or ["Central"]),
        datasets=args.datasets,
        dataset_name=args.dataset,
        variables=csv_or_repeated(args.variable),
        regions=csv_or_repeated(args.region),
        categories=csv_or_repeated(args.category),
        input_dir=args.input_dir,
        manifests=args.manifests,
        output_base=args.output_base,
        output_dir=args.output_dir,
        chunk_size=args.chunk_size,
        cores=args.cores,
        retries=args.retries,
        retry_delay=args.retry_delay,
        condor=args.condor,
        missing_only=args.missing_only,
        dry_run=args.dry_run or check_only,
        execute=args.execute or check_only,
        dy_jet_components=args.dy_jet_components,
        jet_component_processes=csv_or_repeated(
            args.jet_component_processes or []
        ),
        vbf_eta_regions=args.vbf_eta_regions,
        max_files=1 if args.one_file else args.max_files,
        dnn_model_set=args.dnn_model_set,
        overwrite=args.overwrite,
        extra=args.extra[1:] if args.extra[:1] == ["--"] else args.extra,
    )
    if not request.eras:
        raise ValueError("at least one --era is required")
    if not request.systematics:
        raise ValueError("at least one --systematics value is required")
    if request.max_files is not None and request.max_files < 1:
        raise ValueError("--max-files must be >= 1")

    commands = [
        histogram_command(request, era, systematic)
        for systematic in request.systematics
        for era in request.eras
    ]
    if check_only:
        for systematic in request.systematics:
            for era in request.eras:
                report_temporary_histograms(output_dir_for(request, systematic), era)
    for index, command in enumerate(commands, start=1):
        print(f"[{index}/{len(commands)}] {shell_join(command)}", flush=True)
        if request.execute:
            completed = subprocess.run(command, cwd=REPO, check=False)
            if completed.returncode:
                return completed.returncode
    if not request.execute:
        print("\nPlan only: add --run to execute.")
    elif check_only:
        print("\nCheck only: no jobs were submitted. Replace --check with --run to submit missing outputs.")
    return 0


@dataclass(frozen=True)
class Match:
    path: Path
    line: int
    text: str
    kind: str


def source_files() -> Iterable[Path]:
    for root, directory_names, file_names in os.walk(REPO):
        directory_names[:] = [
            name for name in directory_names if name not in IGNORED_PARTS
        ]
        root_path = Path(root)
        for name in file_names:
            path = root_path / name
            if path.suffix in SOURCE_SUFFIXES:
                yield path


def classify_line(variable: str, text: str) -> str:
    escaped = re.escape(variable)
    if re.search(rf"\bDefine\s*\(\s*[furbFURB]*[\"']{escaped}[\"']", text):
        return "definition"
    if re.search(rf"^\s*{escaped}\s*:", text):
        return "configuration"
    if re.search(rf"[\"']{escaped}[\"']", text):
        return "reference"
    return "text"


def variable_matches(variable: str) -> list[Match]:
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(variable)}(?![A-Za-z0-9_])")
    matches: list[Match] = []
    for path in source_files():
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for number, text in enumerate(lines, start=1):
            if pattern.search(text):
                matches.append(
                    Match(
                        path=path.relative_to(REPO),
                        line=number,
                        text=text.strip(),
                        kind=classify_line(variable, text),
                    )
                )
    order = {"definition": 0, "configuration": 1, "reference": 2, "text": 3}
    return sorted(matches, key=lambda item: (order[item.kind], str(item.path), item.line))


def run_where(args: argparse.Namespace) -> int:
    definitions = discover_definitions(REPO)
    producers = definitions_for(definitions, args.variable)
    known_names = {item.name for item in definitions if not item.dynamic}
    if producers:
        print("DEFINITIONS")
        for producer in producers:
            dynamic = " [dynamic name]" if producer.dynamic else ""
            print(
                f"  {producer.path}:{producer.line} "
                f"in {producer.producer}{dynamic}"
            )
            if producer.expression:
                print(f"    expression: {producer.expression}")
                dependencies = dependency_names(producer, known_names)
                if dependencies:
                    print(f"    known inputs: {', '.join(dependencies)}")

    configurations = configured_in(REPO, args.variable)
    if configurations:
        print("\nCONFIGURATION")
        for path, line, text in configurations[: args.limit]:
            print(f"  {path}:{line}: {text}")

    matches = variable_matches(args.variable)
    if not producers and not configurations and not matches:
        print(f"No exact occurrence found for {args.variable!r}.")
        print("The name may be generated dynamically; try: rg '<part of the name>'")
        return 1
    current_kind = None
    shown = 0
    for match in matches:
        if match.kind in {"definition", "configuration"}:
            continue
        if not args.all and match.kind == "text":
            continue
        if match.kind != current_kind:
            current_kind = match.kind
            print(f"\n{current_kind.upper()}")
        print(f"  {match.path}:{match.line}: {match.text}")
        shown += 1
        if shown >= args.limit:
            remaining = len(matches) - shown
            if remaining > 0:
                print(f"\n... {remaining} more match(es); use --limit or --all.")
            break
    return 0


def run_vars(args: argparse.Namespace) -> int:
    definitions = discover_definitions(REPO)
    pattern = args.filter.lower() if args.filter else None
    rows = [
        item
        for item in definitions
        if not pattern or pattern in item.name.lower()
    ]
    if not args.dynamic:
        rows = [item for item in rows if not item.dynamic]
    if not rows:
        print("No statically discoverable columns matched.")
        return 1
    for item in rows:
        print(f"{item.name:42} {item.path}:{item.line}  {item.producer}")
    print(f"\n{len(rows)} definition(s). Use `hmumu where NAME` for details.")
    return 0


def run_doctor(_: argparse.Namespace) -> int:
    checks = {
        "ANALYSIS_PATH": os.environ.get("ANALYSIS_PATH"),
        "histogram entry point": REPO / "histograms/scripts/hists.sh",
        "systematics entry point": REPO / "histograms/scripts/systematics.sh",
        "campaign engine": REPO / "common/scripts/dataset_campaign.sh",
        "histogram engine": REPO / "histograms/hist_maker.py",
    }
    failed = False
    for label, value in checks.items():
        if label == "ANALYSIS_PATH":
            status = "OK" if value else "OPTIONAL"
            print(f"{status:8} {label}: {value or '(derived by hmumu/scripts)'}")
            continue
        ok = Path(value).exists()
        print(f"{'OK' if ok else 'MISSING':8} {label}: {value}")
        failed |= not ok
    return int(failed)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hmumu",
        description="Simple front-end for common H->mumu framework tasks.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    hist = subparsers.add_parser(
        "hist",
        help="produce one histogram or a histogram campaign",
        description=(
            "Build or run histogram jobs without exposing the legacy nested "
            "scripts and '--' option split."
        ),
    )
    hist.add_argument("-e", "--era", action="append", required=True,
                      help="era, repeat or use commas (e.g. 2024,2025)")
    datasets = hist.add_mutually_exclusive_group()
    datasets.add_argument("-d", "--dataset", help="one exact dataset name")
    datasets.add_argument(
        "--datasets",
        help="dataset groups as a comma-separated list (default: skim_cfg)",
    )
    hist.add_argument("-v", "--variable", action="append", default=[],
                      help="variable, repeat or use commas")
    hist.add_argument("-r", "--region", action="append", default=[],
                      help="mass region, repeat or use commas")
    hist.add_argument("-c", "--category", action="append", default=[],
                      help="category, repeat or use commas")
    hist.add_argument("-s", "--systematics", action="append",
                      help="Central or shifted group; repeat/use commas")
    hist.add_argument("--input-dir", default=DEFAULT_INPUT)
    hist.add_argument("--manifests", default=DEFAULT_MANIFESTS)
    hist.add_argument("--output-base", default=DEFAULT_OUTPUT_BASE)
    hist.add_argument("-o", "--output-dir")
    hist.add_argument("--chunk-size", type=int, default=5)
    hist.add_argument("-j", "--cores", type=int, default=1)
    hist.add_argument("--retries", type=int, default=3)
    hist.add_argument("--retry-delay", type=float, default=2)
    execution = hist.add_mutually_exclusive_group()
    execution.add_argument("--condor", action="store_true")
    execution.add_argument("--local", action="store_true")
    hist.add_argument("--missing-only", action=argparse.BooleanOptionalAction, default=True)
    hist.add_argument(
        "--overwrite",
        action="store_true",
        help=(
            "remove selected existing final ROOT outputs before local execution "
            "or Condor submission"
        ),
    )
    hist.add_argument("--dry-run", action="store_true",
                      help="also pass dry-run to the campaign engine")
    hist.add_argument(
        "--pu-hard-jet-components",
        "--dy-jet-components",
        "--jet-gen-components",
        dest="dy_jet_components",
        action="store_true",
        help=(
            "produce exclusive 0J/1J/2J and VBF hard/PU components, "
            "including the prescribed 2D eta:pT fit templates"
        ),
    )
    hist.add_argument(
        "--pu-hard-processes",
        "--jet-gen-component-processes",
        dest="jet_component_processes",
        action="append",
        help=(
            "MC processes or campaign groups to split into PU/hard components; "
            "repeat or use commas"
        ),
    )
    hist.add_argument(
        "--eta-components",
        "--vbf-eta-regions",
        dest="vbf_eta_regions",
        action="store_true",
        help="split VBF events into nested incl/CC/CF/FF eta regions",
    )
    hist.add_argument(
        "--dnn-model-set",
        choices=["updated", "legacy"],
        default="updated",
        help=(
            "select updated unified DNN or legacy era-split DNN "
            "(2022-2023 versus 2024-2025)"
        ),
    )
    file_limit = hist.add_mutually_exclusive_group()
    file_limit.add_argument(
        "--one-file",
        action="store_true",
        help="test mode: process only the first validated ROOT file",
    )
    file_limit.add_argument(
        "--max-files",
        type=int,
        help="test mode: process at most N validated ROOT files",
    )
    action = hist.add_mutually_exclusive_group()
    action.add_argument("--run", dest="execute", action="store_true",
                        help="execute; without this flag only print the plan")
    action.add_argument(
        "--check",
        action="store_true",
        help="scan missing/queued outputs and temporary directories without submitting",
    )
    hist.add_argument("extra", nargs=argparse.REMAINDER,
                      help="advanced hist_maker options after a literal '--'")
    hist.set_defaults(func=run_hist)

    merge_eras = subparsers.add_parser(
        "merge-eras",
        help="hadd matching ROOT files across data-taking eras",
    )
    merge_eras.add_argument(
        "input_dir",
        help="macro-directory containing Run3_2022, Run3_2022EE, ...",
    )
    merge_eras.add_argument(
        "--eras",
        action="append",
        help="eras to merge (default: 2022, 2022EE, 2023, 2023BPix)",
    )
    merge_eras.add_argument("--nominal-dir", help="Central hadded base for padding unaffected eras in shifted templates")
    merge_eras.add_argument("--output-era", default="Run3_2022_23")
    merge_eras.add_argument(
        "--combine-dy-mll-generations",
        action="store_true",
        help=(
            "merge DYto2Mu_MLL105To160 across production generations; old "
            "_combined inputs are accepted but outputs use the canonical name"
        ),
    )
    merge_eras.add_argument("--force", action=argparse.BooleanOptionalAction, default=True)
    merge_eras.add_argument(
        "--missing-only",
        action="store_true",
        help="create only absent or empty merged-era ROOT outputs",
    )
    merge_eras.add_argument(
        "--skip-errors",
        action="store_true",
        help="pass -k to hadd and continue past corrupt or unreadable inputs",
    )
    merge_eras.add_argument("--run", dest="execute", action="store_true")
    merge_eras.set_defaults(func=run_merge_eras)

    hadd_processes = subparsers.add_parser(
        "hadd-processes",
        help="combine per-dataset histograms into physics-process files",
    )
    hadd_processes.add_argument(
        "input_dir",
        help="macro-directory containing one subdirectory per era",
    )
    hadd_processes.add_argument(
        "-e",
        "--era",
        dest="eras",
        action="append",
        required=True,
        help="era, repeat or use commas",
    )
    hadd_processes.add_argument(
        "-o",
        "--output-dir",
        help="output macro-directory (default: INPUT_hadded)",
    )
    hadd_processes.add_argument(
        "--add-derived-systs",
        action="store_true",
        help="also construct configured derived systematics",
    )
    hadd_processes.add_argument(
        "--missing-only",
        action="store_true",
        help="create only process files that do not already exist",
    )
    hadd_processes.add_argument("--run", dest="execute", action="store_true")
    hadd_processes.set_defaults(func=run_hadd_processes)

    check_hists = subparsers.add_parser(
        "check-hists",
        help="read-only report of missing per-dataset histogram files",
    )
    check_hists.add_argument("folder")
    check_hists.add_argument("-e", "--era", dest="eras", action="append")
    check_hists.add_argument(
        "-s", "--systematics", action="append",
        help="campaign mode: systematic groups to check; repeat/use commas",
    )
    check_hists.add_argument("--dataset", dest="datasets", action="append")
    check_hists.add_argument(
        "--group", dest="groups", action="append",
        help=(
            "MC macrogroup used by histogram production; repeat/use commas"
        ),
    )
    check_hists.add_argument(
        "--process", dest="processes", action="append",
        help="configured process from process_names.yaml; repeat/use commas",
    )
    check_hists.add_argument("--datasets-file")
    check_hists.add_argument("--suffix", default="")
    check_hists.add_argument(
        "--exact",
        action="store_true",
        help="treat --dataset values as literal filenames (for hadded outputs)",
    )
    check_hists.add_argument("--json", action="store_true")
    check_hists.add_argument("--show-unexpected", action="store_true")
    check_hists.set_defaults(func=run_check_hists)

    plot = subparsers.add_parser(
        "plot",
        help="plot one or more regions from hadded histogram files",
    )
    plot.add_argument("-e", "--era", required=True)
    plot.add_argument("-i", "--input", dest="input_dir", required=True)
    plot.add_argument("-o", "--output", dest="output_dir", required=True)
    plot.add_argument(
        "-r",
        "--region",
        dest="regions",
        action="append",
        required=True,
        help="region, repeat or use commas",
    )
    plot.add_argument(
        "--samples",
        nargs="+",
        required=True,
        help="ROOT filenames, configured processes, or plotting groups",
    )
    plot.add_argument(
        "-v",
        "--variable",
        dest="variables",
        action="append",
        help="variable, repeat or use commas; omit to plot all",
    )
    plot.add_argument("--systematics", action="store_true")
    plot.add_argument(
        "--systematic-input",
        dest="systematic_inputs",
        action="append",
        help="load shifted templates from NAME=DIR; repeat for each family",
    )
    plot.add_argument(
        "--systematic-group",
        dest="systematic_groups",
        action="append",
        help=(
            "show only this systematic group; repeat for multiple groups "
            "(for example: 'EWKZ PS')"
        ),
    )
    plot.add_argument(
        "--overlay-systematic",
        action="store_true",
        help="overlay nominal, systematic Up and Down in the main panel",
    )
    plot.add_argument(
        "--total-systematics",
        action="store_true",
        help="draw the quadrature sum of all displayed systematic groups",
    )
    plot.add_argument(
        "--mc-stat-uncertainty",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="show the MC statistical uncertainty band in the ratio panel",
    )
    plot.add_argument("--data", dest="want_data", action="store_true")
    plot.add_argument("--log-y", action="store_true")
    plot.add_argument(
        "--log-uncertainties",
        action="store_true",
        help="use a logarithmic y-axis in the ratio/uncertainty panel",
    )
    plot.add_argument("--rebin", action="store_true")
    plot.add_argument("--normalize-dy-to-data", action="store_true")
    plot.add_argument("--normalize-mc-to-data", action="store_true")
    plot.add_argument(
        "--component-composition",
        "--dy-ewk-composition",
        "--dy-composition",
        dest="component_composition",
        action="store_true",
        help="add one fraction panel for each supplied component family",
    )
    plot.add_argument(
        "--dy-012j-weights",
        choices=("none", "old", "new"),
        default="none",
        help="plot-time DY 0J/1J/2J weights (default: none)",
    )
    plot.add_argument(
        "--dy-012j-reweight",
        dest="dy_012j_weights",
        action="store_const",
        const="new",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    plot.add_argument("--dy-normalization-sample")
    plot.add_argument("--run", dest="execute", action="store_true")
    plot.set_defaults(func=run_plot)

    merge_systematics = subparsers.add_parser(
        "merge-systematics",
        help="hadd Central and shifted histogram files",
    )
    merge_systematics.add_argument(
        "central_dir",
        help="Central macro-directory, for example /path/Hists_Central",
    )
    merge_systematics.add_argument(
        "-s",
        "--systematics",
        action="append",
        help="groups to merge (default: Central,JERC,Muon,PDF,PU,QCDScale,ScaRe)",
    )
    merge_systematics.add_argument(
        "--source-dir",
        dest="source_dirs",
        action="append",
        help=(
            "additional already-hadded directory to merge with Central; "
            "repeatable. This bypasses automatic per-systematic directory names"
        ),
    )
    merge_systematics.add_argument(
        "-e",
        "--era",
        dest="eras",
        action="append",
        help="limit the merge to one or more eras; repeat or use commas",
    )
    merge_systematics.add_argument("-o", "--output-dir")
    merge_systematics.add_argument(
        "--force", action=argparse.BooleanOptionalAction, default=True
    )
    merge_systematics.add_argument("--run", dest="execute", action="store_true")
    merge_systematics.set_defaults(func=run_merge_systematics)

    where = subparsers.add_parser(
        "where",
        help="find where a variable is defined, configured and used",
    )
    where.add_argument("variable")
    where.add_argument("--all", action="store_true", help="include loose text matches")
    where.add_argument("--limit", type=int, default=80)
    where.set_defaults(func=run_where)

    variables = subparsers.add_parser(
        "vars", help="list columns created with RDataFrame Define/Redefine"
    )
    variables.add_argument("filter", nargs="?", help="optional name substring")
    variables.add_argument(
        "--dynamic", action="store_true", help="also show generated name templates"
    )
    variables.set_defaults(func=run_vars)

    doctor = subparsers.add_parser("doctor", help="check the local framework setup")
    doctor.set_defaults(func=run_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ValueError as error:
        parser.error(str(error))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
