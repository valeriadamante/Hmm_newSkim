#!/usr/bin/env python3
"""Build the Signal Extended (SR + Higgs sideband) VBF H->mumu datacard.

"Signal Extended" is not the ``Signal_ext`` mass region: the 105--160 samples
that provide the DY and EWK templates are routed by
``config/histogram_sample_routing.yaml`` into ``Signal_Fit`` and ``H_sideband``
only, so ``Signal_ext_VBF`` does not exist in their histogram files.  The
extended fit is therefore built as two channels per era, ``Signal_Fit_VBF``
and ``H_sideband_VBF``, sharing the same processes and nuisances.

The three DY jet-component models requested for the comparison:

``lnn``            each of Hard/PU1/PU2 carries the DYVBFZ_fit_* log-normal
                   taken from the VBF stage of the 012J fit (the talk model).
``rateparam-pu``   PU1 and PU2 share one free rateParam; Hard keeps its lnN.
``rateparam-both`` PU1+PU2 share one rateParam and Hard has a second one; no
                   DY log-normals.

Shape nuisances come from ``config/Run3_<era>/systematics.yaml`` through
``CombineCardWriter.build_uncertainties``, so the naming and the cross-era
correlation are the same as in the existing cards.  A shape column is only
enabled where both variations exist, are positive and have no negative bin:
vertical morphing is otherwise ill-defined and FitDiagnostics stalls.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import ROOT

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "combine"))

import CombineCardWriter as CCW  # noqa: E402

DEFAULT_INPUT = Path(
    "/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/dnn_vbf_weighted/Hists_systMerged"
)
DEFAULT_ERAS = ("2022", "2022EE", "2023", "2023BPix", "2024", "2025")

# channel tag -> histogram directory
CHANNELS = (("sr", "Signal_Fit_VBF"), ("hsb", "H_sideband_VBF"))

# datacard process -> (file stem, 012J fit parameter)
DY_COMPONENTS = (
    ("DYto2Mu_MLL105To160_2J_Hard", "Hard", "VBFHard"),
    ("DYto2Mu_MLL105To160_2J_PU1", "PU1", "VBFPU1"),
    ("DYto2Mu_MLL105To160_2J_PU2", "PU2", "VBFPU2"),
)

# The 012J fit is shared inside each early-era pair, so the DY nuisances are too.
ERA_GROUPS = {
    "2022": ("2022_2022EE", "Run3_2022_2022EE"),
    "2022EE": ("2022_2022EE", "Run3_2022_2022EE"),
    "2023": ("2023_2023BPix", "Run3_2023_2023BPix"),
    "2023BPix": ("2023_2023BPix", "Run3_2023_2023BPix"),
    "2024": ("2024", "Run3_2024"),
    "2025": ("2025", "Run3_2025"),
    "2026": ("2026", "Run3_2026"),
}

DY_MODELS = ("lnn", "rateparam-pu", "rateparam-both")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT,
                        help="Hists_systMerged base directory (default: %(default)s)")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--eras", default=",".join(DEFAULT_ERAS))
    parser.add_argument("--variable", default="DNN_NNOutput")
    parser.add_argument("--dy-model", choices=DY_MODELS, default="lnn")
    parser.add_argument("--channels", default="sr,hsb",
                        help="Comma-separated subset of sr,hsb (default: both)")
    parser.add_argument("--fit-root", type=Path,
                        default=REPO / "reweights" / "dy_012j_reweight_skim_v4",
                        help="Where the dy_012j_reweight_fit.json payloads live")
    parser.add_argument("--rateparam-scope", choices=("group", "all"), default="group",
                        help="One rateParam per era group (default) or one for all eras")
    parser.add_argument("--rate-param-range", default="0.2,5.0", metavar="MIN,MAX")
    parser.add_argument("--allow-unmerged", action="store_true",
                        help="Accept an era whose merge-syst never wrote its receipt")
    return parser.parse_args()


def resolve_file(directory: Path, stem: str) -> Path | None:
    for candidate in (directory / f"{stem}.root", directory / f"{stem}_NJets.root"):
        if candidate.is_file():
            return candidate.resolve()
    return None


def usable_shapes(handle, region: str, variable: str, names: list[str]) -> set[str]:
    """Nuisances whose Up/Down templates are usable for vertical morphing."""
    usable = set()
    for name in names:
        up = handle.Get(f"{region}/{variable}_{name}Up")
        down = handle.Get(f"{region}/{variable}_{name}Down")
        if not up or not down:
            continue
        if up.Integral() <= 0 or down.Integral() <= 0:
            continue
        if up.GetMinimum() < 0 or down.GetMinimum() < 0:
            continue
        usable.add(name)
    return usable


def dy_lnn_factors(fit_root: Path, eras: list[str]) -> dict[tuple[str, str], float]:
    """1 + err/value of the VBF components of the 012J fit, per era group."""
    factors: dict[tuple[str, str], float] = {}
    for era in eras:
        group, payload_dir = ERA_GROUPS[era]
        payload = json.loads((fit_root / payload_dir / "dy_012j_reweight_fit.json").read_text())
        parameters = dict(zip(payload["parameter_order"],
                              zip(payload["values"], payload["errors"])))
        for _process, label, parameter in DY_COMPONENTS:
            value, error = parameters[parameter]
            if value == 0.0:
                if error != 0.0:
                    raise ValueError(f"{payload_dir}: {parameter} has zero value, nonzero error")
                continue
            factors[(group, label)] = 1.0 + error / value
    return factors


def main() -> int:
    args = parse_args()
    eras = [item.strip() for item in args.eras.split(",") if item.strip()]
    tags = [item.strip() for item in args.channels.split(",") if item.strip()]
    unknown = sorted(set(tags) - {tag for tag, _ in CHANNELS})
    if not tags or unknown:
        raise ValueError(f"--channels must be a subset of sr,hsb; unknown: {unknown}")
    regions = [(tag, region) for tag, region in CHANNELS if tag in tags]
    low, high = (float(item) for item in args.rate_param_range.split(",", 1))

    processes = CCW.signalprocesses + CCW.backgroundprocesses
    # Signals take ids <= 0, backgrounds ids >= 1.
    process_ids: dict[str, int] = {}
    for index, name in enumerate(reversed(CCW.signalprocesses)):
        process_ids[name] = -index
    for index, name in enumerate(CCW.backgroundprocesses, start=1):
        process_ids[name] = index

    xsec = CCW.build_xsec_dictionary(
        str(REPO / "config" / "crossSections13p6TeV.yaml"), processes)

    shape_lines: list[str] = []
    observation_channels: list[str] = []
    columns: list[dict] = []
    # nuisances are era-specific; keep the per-era list to know which row a
    # column may ever be enabled on.
    era_shape_names: dict[str, list[str]] = {}

    for era in eras:
        era_dir = args.input / f"Run3_{era}"
        if not era_dir.is_dir():
            raise RuntimeError(f"Missing input directory {era_dir}")
        # A merge-syst that died half way leaves a directory that looks usable:
        # it holds Data_Muon and the DY components but stops at whatever process
        # the hadd was on, so the card would silently lose ggH, VBFH and every
        # small background of that era.  The campaign writes its receipt only
        # when the merge completed, so that is what certifies the era.
        receipt = args.input.parent / f".workflow_syst_Run3_{era}.json"
        if not receipt.is_file() and not args.allow_unmerged:
            raise RuntimeError(
                f"Run3_{era}: no merge-syst receipt ({receipt}). The merge never "
                f"finished, so {era_dir} is incomplete "
                f"({len(list(era_dir.glob('*.root')))} files). Finish it with "
                f"'campaigns/dnn_vbf_signal.sh merge-syst --eras {era}', or pass "
                "--allow-unmerged if you really want a partial card."
            )
        uncertainties = CCW.build_uncertainties(
            str(REPO / "config" / f"Run3_{era}" / "systematics.yaml"), processes, era)
        shape_names = [entry[0] for entry in uncertainties if entry[1] == "shape"]
        shape_targets = {entry[0]: entry[3] for entry in uncertainties if entry[1] == "shape"}
        era_shape_names[era] = shape_names

        for tag, region in regions:
            channel = f"y{era}_{tag}"
            data_path = resolve_file(era_dir, "Data_Muon")
            if data_path is None:
                raise RuntimeError(f"Missing Data_Muon.root in {era_dir}")
            handle = ROOT.TFile.Open(str(data_path), "READ")
            if not handle or handle.IsZombie() or not handle.Get(f"{region}/{args.variable}"):
                raise RuntimeError(f"Missing {region}/{args.variable} in {data_path}")
            handle.Close()
            shape_lines.append(
                f"shapes data_obs {channel} {data_path} {region}/{args.variable}")
            observation_channels.append(channel)

            for process in processes:
                path = resolve_file(era_dir, process)
                if path is None:
                    print(f"[SKIP] {channel}: no ROOT file for {process}")
                    continue
                handle = ROOT.TFile.Open(str(path), "READ")
                if not handle or handle.IsZombie():
                    print(f"[SKIP] {channel}/{process}: unreadable {path}")
                    continue
                nominal = handle.Get(f"{region}/{args.variable}")
                if not nominal or nominal.Integral() <= 0:
                    print(f"[SKIP] {channel}/{process}: missing or empty nominal")
                    handle.Close()
                    continue
                allowed = [name for name in shape_names
                           if shape_targets[name] is None or process in shape_targets[name]]
                usable = usable_shapes(handle, region, args.variable, allowed)
                dropped = sorted(set(allowed) - usable)
                if dropped:
                    print(f"[WARN] {channel}/{process}: {len(dropped)} shape nuisances "
                          f"disabled ({', '.join(dropped[:4])}"
                          f"{'...' if len(dropped) > 4 else ''})")
                handle.Close()
                columns.append({
                    "channel": channel, "era": era, "process": process,
                    "id": process_ids[process], "shapes": usable,
                })
                shape_lines.append(
                    f"shapes {process} {channel} {path} "
                    f"{region}/{args.variable} {region}/{args.variable}_$SYSTEMATIC")

    if not columns:
        raise RuntimeError("No valid process columns found")

    width = max(16, max(len(c["channel"]) for c in columns),
                max(len(c["process"]) for c in columns))

    def row(label, values):
        return f"{label:<46}" + " ".join(f"{str(v):>{width}}" for v in values)

    lines = ["imax *", "jmax *", "kmax *", "------------", *shape_lines, "------------",
             row("bin", observation_channels),
             row("observation", ["-1"] * len(observation_channels)),
             "------------",
             row("bin", [c["channel"] for c in columns]),
             row("process", [c["process"] for c in columns]),
             row("process", [c["id"] for c in columns]),
             row("rate", ["-1"] * len(columns)),
             "------------"]

    # Shape rows, in the order the per-era configuration produces them.
    seen: list[str] = []
    for era in eras:
        for name in era_shape_names[era]:
            if name not in seen:
                seen.append(name)
    for name in seen:
        values = ["1" if name in c["shapes"] else "-" for c in columns]
        if "1" not in values:
            print(f"[DROP] shape {name}: no usable column")
            continue
        lines.append(row(f"{name} shape", values))

    # Luminosity, correlated exactly as CombineCardWriter does.
    for name, per_year in CCW.lumidict.items():
        values = []
        for c in columns:
            key = c["era"].replace("EE", "").replace("BPix", "")
            values.append(per_year.get(key, "-"))
        if set(values) == {"-"}:
            continue
        lines.append(row(f"{name} lnN", values))

    # Cross-section / theory normalisations, one row per process.
    for process, kappa in xsec.items():
        values = [f"{kappa['down']:.4f}/{kappa['up']:.4f}" if c["process"] == process else "-"
                  for c in columns]
        if set(values) == {"-"}:
            continue
        lines.append(row(f"{process} lnN", values))

    # --- the DY jet-component model -------------------------------------
    rateparam_lines: list[str] = []
    if args.dy_model == "lnn":
        lnn_components = [label for _p, label, _f in DY_COMPONENTS]
        rateparam_groups: dict[str, list[str]] = {}
    elif args.dy_model == "rateparam-pu":
        lnn_components = ["Hard"]
        rateparam_groups = {"PU": ["PU1", "PU2"]}
    else:
        lnn_components = []
        rateparam_groups = {"PU": ["PU1", "PU2"], "Hard": ["Hard"]}

    if lnn_components:
        factors = dy_lnn_factors(args.fit_root, eras)
        groups = list(dict.fromkeys(ERA_GROUPS[era][0] for era in eras))
        for group in groups:
            group_eras = {era for era in eras if ERA_GROUPS[era][0] == group}
            for process, label, _parameter in DY_COMPONENTS:
                if label not in lnn_components:
                    continue
                factor = factors.get((group, label))
                if factor is None:
                    continue
                values = [f"{factor:.6f}"
                          if c["era"] in group_eras and c["process"] == process else "-"
                          for c in columns]
                if set(values) == {"-"}:
                    continue
                lines.append(row(f"DYVBFZ_fit_2J{label}_{group} lnN", values))

    stems = {label: process for process, label, _f in DY_COMPONENTS}
    if rateparam_groups:
        rateparam_lines.append("")
        if args.rateparam_scope == "all":
            for name, labels in rateparam_groups.items():
                for label in labels:
                    rateparam_lines.append(
                        f"DY_norm_{name} rateParam * {stems[label]} 1 [{low:g},{high:g}]")
        else:
            for group in list(dict.fromkeys(ERA_GROUPS[era][0] for era in eras)):
                group_eras = [era for era in eras if ERA_GROUPS[era][0] == group]
                for name, labels in rateparam_groups.items():
                    for era in group_eras:
                        for label in labels:
                            rateparam_lines.append(
                                f"DY_norm_{name}_{group} rateParam y{era}_* "
                                f"{stems[label]} 1 [{low:g},{high:g}]")

    lines.extend(rateparam_lines)
    lines.append("")
    for channel in observation_channels:
        lines.append(f"{channel} autoMCStats 10 0 1")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(lines) + "\n")
    shape_rows = sum(1 for line in lines if " shape " in line)
    print(f"Wrote {args.output}")
    print(f"  dy-model={args.dy_model} channels={len(observation_channels)} "
          f"columns={len(columns)} shape nuisances={shape_rows} "
          f"rateParam lines={len([l for l in rateparam_lines if l])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
