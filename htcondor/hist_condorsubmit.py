#!/usr/bin/env python3
"""Histogram Condor submitter with queue monitoring.

This mirrors the monitoring model used by ``htcondor/condorsubmit.py`` for the
skim workflow, but targets the histogram campaign entry point in
``histograms/scripts/hists.sh``.

The submitter is intentionally lightweight and adapts to the existing stage
workflow by building the same jobs.tsv + submit.sub files used by the shell
campaign runner, then submitting and watching them until the output files become
valid.
"""

from __future__ import annotations

import argparse
import copy
import os
import shlex
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Iterable, List, Sequence

import yaml

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DEFAULT_STAGE_COMMAND = REPO / "histograms" / "scripts" / "hists.sh"


def load_hist_config(era: str) -> dict:
    """Reuse the producer settings from the era's skim configuration."""
    path = REPO / "config" / era / "skim_cfg.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"Missing shared producer configuration: {path}")
    with path.open() as handle:
        return yaml.safe_load(handle) or {}


def apply_hist_config(args: argparse.Namespace, era: str) -> argparse.Namespace:
    configured = copy.copy(args)
    cfg = load_hist_config(era)
    output_dir_was_explicit = configured.output_dir is not None
    if not configured.systematics:
        configured.systematics = ["Central"]
    central_only = {
        name.lower() for name in configured.systematics
    } <= {"central", "nominal"}
    configured_output = cfg.get(
        "histogram_output_dir"
        if central_only
        else "histogram_systematics_output_dir"
    )
    defaults = {
        "datasets": "skim_cfg",
        "input_folder": cfg.get("output_dir", "skim_v4"),
        "output_dir": configured_output,
        "chunk_size": cfg.get("chunk_size", 1),
        "file_open_retries": 3,
        "file_open_retry_delay": 2,
        # Histogram jobs default to workday.  Skim-specific flavour choices
        # must not silently shorten histogram jobs; users can still override
        # this explicitly with --job-flavour.
        "job_flavour": "workday",
        "request_cpus": cfg.get("request_cpus", 1),
        "request_memory": cfg.get("request_memory", "4GB"),
        "request_disk": cfg.get("request_disk", "2GB"),
        # Keep monitoring responsive and consistent with the skim submitter.
        "poll_interval": 120.0,
    }
    for name, fallback in defaults.items():
        if getattr(configured, name, None) is None:
            # skim_cfg.output_dir is the skim destination/input, whereas the
            # histogram destination is selected above from its dedicated key.
            value = fallback if name == "output_dir" else cfg.get(name, fallback)
            if isinstance(value, str):
                value = value.format(era=era)
            setattr(configured, name, value)
    if not output_dir_was_explicit and configured.output_suffix:
        configured.output_dir = f"{configured.output_dir}{configured.output_suffix}"
    if configured.output_dir is None:
        raise ValueError(
            "skim_cfg.yaml must define histogram_output_dir and "
            "histogram_systematics_output_dir"
        )
    if configured.max_parallel_jobs is None:
        configured.max_parallel_jobs = cfg.get("max_parallel_jobs", 6000)
    return configured


def parse_jobs_table(lines: Iterable[str]) -> List[dict]:
    rows: List[dict] = []
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        fields = line.split("\t")
        if len(fields) < 4:
            continue
        dataset, chunk_size, file_suffix, specific_opts = fields[:4]
        rows.append(
            {
                "dataset": dataset,
                "chunk_size": int(chunk_size) if chunk_size.strip() else 1,
                "file_suffix": "" if file_suffix in {"", "-"} else file_suffix,
                "specific_opts": "" if specific_opts in {"", "-"} else specific_opts,
            }
        )
    return rows


def expected_output_paths(
    rows: Sequence[dict],
    output_dir: str | None = None,
    era: str | None = None,
) -> List[str]:
    if output_dir is None:
        output_dir = rows[0].get("output_dir", "") if rows else ""
    if era is None:
        era = rows[0].get("era", "") if rows else ""

    output_paths: List[str] = []
    for row in rows:
        suffix = row.get("file_suffix") or ""
        dataset = row["dataset"]
        row_output_dir = row.get("output_dir", output_dir)
        row_era = row.get("era", era)
        output_paths.append(
            str(Path(row_output_dir) / str(row_era) / f"{dataset}{suffix}.root")
        )
    return output_paths


def run_command(command: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess:
    print("[PREPARE] " + shlex.join(str(part) for part in command), flush=True)
    result = subprocess.run(
        command, cwd=str(REPO), check=False, text=True, capture_output=True
    )
    if check and result.returncode != 0:
        if result.stdout:
            print(result.stdout, file=sys.stderr, end="")
        if result.stderr:
            print(result.stderr, file=sys.stderr, end="")
        result.check_returncode()
    return result


def find_latest_submission_dir(stage_dir: Path) -> Path:
    if not stage_dir.exists():
        raise FileNotFoundError(f"Condor stage directory does not exist: {stage_dir}")
    candidates = [p for p in stage_dir.iterdir() if p.is_dir()]
    if not candidates:
        raise FileNotFoundError(f"No Condor submission directory found under {stage_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def query_condor_cluster(cluster_id: int) -> dict:
    counts = {"idle": 0, "running": 0, "held": 0, "transferring": 0, "total": 0}
    try:
        result = subprocess.run(
            [
                "condor_q",
                str(cluster_id),
                "-autoformat:t",
                "JobStatus",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return counts
    if result.returncode != 0:
        return counts

    for line in result.stdout.splitlines():
        try:
            job_status = int(line.strip())
        except ValueError:
            continue
        counts["total"] += 1
        key = {1: "idle", 2: "running", 5: "held", 6: "transferring"}.get(job_status)
        if key:
            counts[key] += 1
    return counts


def output_is_complete(path: str) -> bool:
    if not os.path.exists(path) or os.path.getsize(path) <= 0:
        return False
    return True


def build_shell_command(args: argparse.Namespace) -> List[str]:
    command = [
        "bash",
        str(DEFAULT_STAGE_COMMAND),
        "--era",
        args.era,
    ]

    datasets = args.datasets or "all"
    command.extend(["--datasets", datasets])

    if args.dataset_name:
        command.extend(["--dataset-name", args.dataset_name])

    if args.input_folder:
        command.extend(["--input-folder", args.input_folder])
    if args.root_input_folder:
        command.extend(["--root-input-folder", args.root_input_folder])
    if args.json_input_folder:
        command.extend(["--json-input-folder", args.json_input_folder])
    if args.manifest_input_folder:
        command.extend(["--manifest-input-folder", args.manifest_input_folder])
    if args.output_suffix:
        command.extend(["--output-suffix", args.output_suffix])
    if args.output_dir:
        command.extend(["--output-dir", args.output_dir])
    if args.condor_label:
        command.extend(["--condor-label", args.condor_label])
    if getattr(args, "summary_file", None):
        command.extend(["--summary-file", args.summary_file])
    if args.chunk_size is not None:
        command.extend(["--chunk-size", str(args.chunk_size)])
    if args.file_open_retries is not None:
        command.extend(["--file-open-retries", str(args.file_open_retries)])
    if args.file_open_retry_delay is not None:
        command.extend(["--file-open-retry-delay", str(args.file_open_retry_delay)])
    if args.max_jobs is not None:
        command.extend(["--max-jobs", str(args.max_jobs)])
    if args.max_parallel_jobs is not None:
        command.extend(["--max-parallel-jobs", str(args.max_parallel_jobs)])
    if args.job_flavour:
        command.extend(["--job-flavour", args.job_flavour])
    if args.request_cpus:
        command.extend(["--request-cpus", str(args.request_cpus)])
    if args.request_memory:
        command.extend(["--request-memory", str(args.request_memory)])
    if args.request_disk:
        command.extend(["--request-disk", str(args.request_disk)])
    if args.force:
        command.append("--force")
    if args.missing_only:
        command.append("--missing-only")
    if args.require_component_outputs:
        command.append("--require-component-outputs")
    if args.require_component_regions:
        command.extend(["--require-component-regions", args.require_component_regions])
    # This frontend owns submission and monitoring.  The shell workflow only
    # prepares jobs.tsv and submit.sub, avoiding accidental double submission.
    command.extend(["--condor", "--dry-run"])

    for systematic in args.systematics:
        command.extend(["--systematics", systematic])

    if args.extra_opts:
        command.extend(["--", *args.extra_opts])

    return command


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build and monitor histogram Condor submissions using the same stage "
            "workflow as the shell campaign runner."
        )
    )
    parser.add_argument("--era", "--eras", dest="eras", default="Run3_2024", help="Comma-separated eras to process.")
    parser.add_argument(
        "--datasets", default=None,
        help="Dataset group(s); defaults to skim_cfg selection.",
    )
    parser.add_argument("--dataset-name", default=None, help="Explicit dataset name to process.")
    parser.add_argument("--input-folder", default=None, help="Validation-manifest base folder.")
    parser.add_argument("--root-input-folder", default=None, help="Skim ROOT input folder.")
    parser.add_argument("--json-input-folder", default=None, help="Skim JSON input folder.")
    parser.add_argument("--manifest-input-folder", default=None, help="Manifest input folder.")
    parser.add_argument("--output-suffix", default="", help="Suffix appended to output names.")
    parser.add_argument("--output-dir", default=None, help="Target output directory.")
    parser.add_argument("--condor-label", default=None, help="Short Condor campaign label.")
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--file-open-retries", type=int, default=None)
    parser.add_argument("--file-open-retry-delay", type=int, default=None)
    parser.add_argument("--job-flavour", default=None)
    parser.add_argument("--request-cpus", type=int, default=None)
    parser.add_argument("--request-memory", default=None)
    parser.add_argument("--request-disk", default=None)
    parser.add_argument("--max-jobs", type=int, default=None)
    parser.add_argument("--max-parallel-jobs", type=int, default=None)
    parser.add_argument("--submit-missing", action="store_true", help="Alias for --force.")
    parser.add_argument("--force", action="store_true", help="Submit even if outputs already exist.")
    parser.add_argument("--missing-only", action="store_true", help="Only run missing outputs.")
    parser.add_argument(
        "--require-component-outputs",
        action="store_true",
        help="Treat a dataset as missing unless its VBF 2J component files exist.",
    )
    parser.add_argument(
        "--require-component-regions",
        help="Comma-separated VBF mass regions required inside component files.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Generate the jobs table without submitting.")
    parser.add_argument("--monitor", action=argparse.BooleanOptionalAction, default=True, help="Monitor until outputs are verified (default: true).")
    parser.add_argument("--poll-interval", type=float, default=None, help="Seconds between queue polls.")
    parser.add_argument("--systematics", action="append", default=[], help="Systematic name/group; repeatable.")
    parser.add_argument("--submit", action=argparse.BooleanOptionalAction, default=True, help="Submit after preparing missing jobs (default: true).")
    parser.add_argument("--extra-opts", nargs="*", default=[], help="Extra options forwarded to hist_maker.py.")
    args, forwarded = parser.parse_known_args()
    if forwarded and forwarded[0] == "--":
        forwarded = forwarded[1:]
    args.extra_opts.extend(forwarded)
    return args


def main() -> int:
    args = parse_args()

    if args.extra_opts and args.extra_opts[0] == "--":
        args.extra_opts = args.extra_opts[1:]
    if not args.extra_opts:
        args.extra_opts = list(args.extra_opts)

    if args.submit_missing:
        args.force = True

    stage_dir = REPO / "htcondor" / "hists"
    failures = 0
    for era in (item.strip() for item in args.eras.split(",")):
        if not era:
            continue
        era_args = apply_hist_config(args, era)
        era_args.era = era
        with tempfile.NamedTemporaryFile(
            prefix=f"hist_submit_{era}_", suffix=".tsv", delete=False
        ) as summary_handle:
            era_args.summary_file = summary_handle.name
        try:
            run_command(build_shell_command(era_args), check=True)
            summary_lines = [
                line for line in Path(era_args.summary_file).read_text().splitlines()
                if line.strip()
            ]
        finally:
            Path(era_args.summary_file).unlink(missing_ok=True)
        if len(summary_lines) < 2:
            raise RuntimeError(
                f"Histogram preparation did not write a summary for {era}"
            )
        summary_fields = summary_lines[-1].split("\t")
        if len(summary_fields) < 11:
            raise RuntimeError(
                f"Malformed histogram preparation summary for {era}: "
                f"{summary_lines[-1]}"
            )
        submit_file = Path(summary_fields[10])
        if not submit_file.is_absolute():
            submit_file = REPO / submit_file
        submit_dir = submit_file.parent
        jobs_file = submit_dir / "jobs.tsv"
        if not jobs_file.exists():
            raise FileNotFoundError(f"Incomplete submission metadata in {submit_dir}")

        rows = parse_jobs_table(jobs_file.read_text().splitlines())
        output_dir = era_args.output_dir
        expected = expected_output_paths(rows, output_dir, era)
        print(f"[PREPARED] {era}: {len(rows)} jobs in {submit_dir}")
        if not rows:
            print(f"[COMPLETE] {era}: no missing histogram outputs to submit")
            continue
        if not submit_file.exists():
            raise FileNotFoundError(f"Missing submit file in {submit_dir}")
        if era_args.dry_run or not era_args.submit:
            continue

        result = subprocess.run(
            ["condor_submit", "-terse", str(submit_file)],
            cwd=str(REPO), text=True, capture_output=True, check=True,
        )
        match = re.search(r"(\d+)\.", result.stdout)
        if not match:
            raise RuntimeError(f"Cannot parse Condor cluster id from: {result.stdout.strip()}")
        cluster_id = int(match.group(1))
        print(f"[SUBMIT] {era}: cluster {cluster_id}, {len(rows)} jobs")
        if not era_args.monitor:
            continue

        start = time.time()
        previous_status = None
        while True:
            complete = sum(output_is_complete(path) for path in expected)
            counts = query_condor_cluster(cluster_id)
            status = (complete, *(counts[key] for key in ("idle", "running", "held", "transferring", "total")))
            if status != previous_status:
                print(
                    f"[MONITOR] {era} cluster={cluster_id} outputs={complete}/{len(expected)} "
                    f"idle={counts['idle']} running={counts['running']} held={counts['held']}"
                )
                previous_status = status
            if counts["total"] == 0:
                missing = [path for path in expected if not output_is_complete(path)]
                if missing:
                    failures += len(missing)
                    print(f"[ERROR] {era}: {len(missing)} outputs missing after cluster {cluster_id}", file=sys.stderr)
                    for path in missing:
                        print(f"  - {path}", file=sys.stderr)
                break
            time.sleep(era_args.poll_interval)

        print(f"[SUMMARY] {era}: {len(expected) - len(missing)}/{len(expected)} outputs valid, elapsed={time.time() - start:.0f}s")

    if args.dry_run or not args.submit:
        print("[DRY RUN] Metadata generated; no jobs submitted.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
