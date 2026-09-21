#!/usr/bin/env python3
"""DNN output performance from the skims, with and without event weights.

Both curves come from the same event loop and the same selection, so the only
difference between them is whether ``weight__Central`` is used. The unweighted
curve answers "how well does the network separate the two classes", the
weighted one "how well does it separate the expected event yields".

Process composition is read from config/dnn_studies.yaml, shared with
tools/optimize_dnn_binning.py, tools/compare_dnn_performance.py and
studies/sensitivity_vs_nbins.py.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ANALYSIS_PATH = os.environ.get(
    "ANALYSIS_PATH", str(Path(__file__).resolve().parents[1])
)
if ANALYSIS_PATH not in sys.path:
    sys.path.insert(0, ANALYSIS_PATH)

from common.dnn_studies import (  # noqa: E402
    background_processes,
    load_dnn_studies_config,
    signal_processes,
)
from common.utilities import (  # noqa: E402
    dataset_region_allowed,
    get_config,
    get_segmentation_dict,
    initialize_root_runtime,
    list_root_files,
    report_path_for_root,
    resolve_dataset_selection,
)

ALL_ERAS = [
    "Run3_2022",
    "Run3_2022EE",
    "Run3_2023",
    "Run3_2023BPix",
    "Run3_2024",
    "Run3_2025",
    "Run3_2026",
]


def normalized_era(era: str) -> str:
    return era if era.startswith("Run3_") else f"Run3_{era}"


def datasets_for_processes(era: str, processes: list[str]) -> dict[str, list[str]]:
    """Map each requested process to its datasets, skipping absent processes."""
    selection = resolve_dataset_selection(ANALYSIS_PATH, era)
    available = selection["process_datasets"]
    resolved = {}
    for process in processes:
        members = available.get(process)
        if not members:
            continue
        resolved[process] = list(members)
    return resolved


def _make_vector(paths):
    """std::vector<string> per i costruttori di RDataFrame."""
    import ROOT

    vector = ROOT.std.vector("string")()
    for path in paths:
        vector.push_back(str(path))
    return vector

def read_dataset(
    dataset: str,
    *,
    era: str,
    input_dir: Path,
    selections_cfg,
    systematics_cfg,
    samples_cfg,
    selection_expression: str,
    dy_weights: frozenset[str],
    max_files: int = 0,
) -> tuple[np.ndarray, np.ndarray]:
    """Return (DNN score, weight__Central) for one skim dataset.

    With max_files > 0 only an evenly-spaced subset of the dataset's ROOT files
    is read and the weights are scaled by n_all/n_used.  The per-event weight
    comes from the generator normalization in the reports, which is global and
    does not depend on how many files are opened, so the rescaled yields stay
    unbiased and the ROC -- which only depends on the score/weight pairs -- is
    unchanged up to the statistics actually read.  The stride spans the whole
    dataset rather than taking the first files, so no run range is favoured.
    """
    from common.dnn_application import clear_prediction_registry
    from common.prepare_rdf import prepare_rdf

    dataset_dir = input_dir / era / dataset
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Skim directory does not exist: {dataset_dir}")
    root_files = sorted(list_root_files(str(dataset_dir)))
    if not root_files:
        raise FileNotFoundError(f"No ROOT files under {dataset_dir}")
    weight_scale = 1.0
    if max_files and len(root_files) > max_files:
        stride = len(root_files) / max_files
        picked = sorted({int(index * stride) for index in range(max_files)})
        weight_scale = len(root_files) / len(picked)
        print(
            f"    {dataset}: subset {len(picked)}/{len(root_files)} file, "
            f"pesi x{weight_scale:.3g}",
            flush=True,
        )
        root_files = [root_files[index] for index in picked]

    sample_info = samples_cfg.get(dataset)
    if sample_info is None:
        raise KeyError(f"{dataset} is missing from config/{era}/samples.yaml")
    is_data = bool(sample_info.get("is_data", False))
    if is_data:
        raise ValueError(f"{dataset} is a data sample; ROC inputs must be simulation")

    report_files = [
        path
        for path in (report_path_for_root(root_file) for root_file in root_files)
        if path and os.path.isfile(path)
    ]
    if not report_files:
        raise FileNotFoundError(f"No skim report JSON next to the ROOT files in {dataset_dir}")
    seg_dict = get_segmentation_dict(report_files)
    if not seg_dict:
        raise RuntimeError(f"Empty generator normalization for {dataset}")

    # Un dataset i cui file non contengono alcun evento non ha nemmeno le
    # colonne dei pesi, e prepare_rdf muore nel JIT con "use of undeclared
    # identifier 'genWeight'", portandosi dietro l'intera run multi-era.
    # Saltarlo e' corretto: non contribuisce ne' alla ROC ne' alle rese.
    import ROOT as _ROOT
    if _ROOT.RDataFrame("Events", _make_vector(root_files)).Count().GetValue() == 0:
        print(f"    {dataset}: 0 entries nei file, salto", flush=True)
        return np.empty(0, dtype=np.float64), np.empty(0, dtype=np.float64)

    started = time.perf_counter()
    prepared = prepare_rdf(
        dataset_name=dataset,
        era=era,
        selections_cfg=selections_cfg,
        systematics_cfg=systematics_cfg,
        is_data=False,
        input_files=root_files,
        seg_dict=seg_dict,
        dnn_payloads=["DNN"],
        skip_validation=True,
        enable_dy012j="jet-component" in dy_weights,
        enable_dyptll="ptll" in dy_weights,
        enable_dynjets="njets" in dy_weights,
    )
    rdf = prepared.get("inclusive")
    if rdf is None:
        raise RuntimeError(f"prepare_rdf returned no inclusive node for {dataset}")
    columns = rdf.Filter(selection_expression).AsNumpy(
        ["DNN_NNOutput", "weight__Central"]
    )
    scores = np.asarray(columns["DNN_NNOutput"], dtype=np.float64)
    weights = np.asarray(columns["weight__Central"], dtype=np.float64)
    if weight_scale != 1.0:
        weights = weights * weight_scale
    clear_prediction_registry()
    print(
        f"    {dataset}: {scores.size} events, "
        f"sum(w)={weights.sum():.4g}, {time.perf_counter() - started:.1f} s",
        flush=True,
    )
    return scores, weights


def roc_from_scores(
    signal_scores: np.ndarray,
    signal_weights: np.ndarray,
    background_scores: np.ndarray,
    background_weights: np.ndarray,
) -> dict:
    """Weighted ROC, AUC and S/sqrt(S+B) scan at every observed threshold.

    Passing unit weights gives the unweighted curve, so both variants share one
    implementation and cannot drift apart.
    """
    scores = np.concatenate([signal_scores, background_scores])
    is_signal = np.concatenate(
        [
            np.ones(signal_scores.size, dtype=bool),
            np.zeros(background_scores.size, dtype=bool),
        ]
    )
    weights = np.concatenate([signal_weights, background_weights])

    order = np.argsort(scores, kind="mergesort")[::-1]
    scores, is_signal, weights = scores[order], is_signal[order], weights[order]

    signal_above = np.cumsum(np.where(is_signal, weights, 0.0))
    background_above = np.cumsum(np.where(is_signal, 0.0, weights))

    # One point per distinct threshold value.
    last = np.r_[np.flatnonzero(np.diff(scores)), scores.size - 1]
    thresholds = scores[last]
    signal_above = signal_above[last]
    background_above = background_above[last]

    signal_total = float(signal_weights.sum())
    background_total = float(background_weights.sum())
    if signal_total <= 0.0 or background_total <= 0.0:
        raise RuntimeError("signal and background weight sums must both be positive")

    tpr = np.r_[0.0, signal_above / signal_total]
    fpr = np.r_[0.0, background_above / background_total]
    auc = float(np.trapz(tpr, fpr))

    denominator = np.sqrt(np.maximum(signal_above + background_above, 0.0))
    significance = np.divide(
        signal_above,
        denominator,
        out=np.zeros_like(signal_above),
        where=denominator > 0.0,
    )
    best = int(np.argmax(significance))
    return {
        "auc": auc,
        "signal_yield": signal_total,
        "background_yield": background_total,
        "signal_entries": int(signal_scores.size),
        "background_entries": int(background_scores.size),
        "best_threshold": float(thresholds[best]),
        "best_significance": float(significance[best]),
        "signal_efficiency_at_best": float(signal_above[best] / signal_total),
        "background_efficiency_at_best": float(background_above[best] / background_total),
        "thresholds": thresholds.tolist(),
        "tpr": tpr.tolist(),
        "fpr": fpr.tolist(),
        "significance": significance.tolist(),
    }


CURVE_KEYS = ("thresholds", "tpr", "fpr", "significance")


def compact(result: dict) -> dict:
    """Drop the per-threshold arrays, keeping the summary numbers."""
    return {key: value for key, value in result.items() if key not in CURVE_KEYS}


def thinned(result: dict, max_points: int = 2000) -> dict:
    """Sub-sample the curve arrays for serialization.

    One point per selected event gives millions of entries and a JSON of
    hundreds of megabytes. The endpoints and the best-significance point are
    always kept, so the stored curve still reproduces the plot and the quoted
    working point.
    """
    length = len(result["thresholds"])
    if length <= max_points:
        indices = np.arange(length)
    else:
        indices = np.unique(
            np.r_[
                np.linspace(0, length - 1, max_points).astype(int),
                int(np.argmax(result["significance"])),
                length - 1,
            ]
        )
    payload = compact(result)
    payload["curve_points"] = int(indices.size)
    for key in CURVE_KEYS:
        values = np.asarray(result[key])
        # tpr/fpr carry one leading zero point that thresholds do not.
        offset = values.size - length
        payload[key] = (
            np.r_[values[:offset], values[offset:][indices]].tolist()
            if offset
            else values[indices].tolist()
        )
    return payload


def write_plot(curves: dict, output_png: Path, title: str) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, axes = plt.subplots(1, 2, figsize=(12, 5))
    for label, result in curves.items():
        axes[0].plot(
            result["fpr"], result["tpr"], lw=2, label=f"{label} (AUC = {result['auc']:.4f})"
        )
    axes[0].plot([0, 1], [0, 1], "--", color="0.6", label="Random classifier")
    axes[0].set(
        xlabel="Background efficiency",
        ylabel="Signal efficiency",
        xlim=(0, 1),
        ylim=(0, 1),
    )
    # S/sqrt(S+B) is only a physics quantity for the weighted curve; on raw
    # entries it just measures relative sample sizes, so it is not drawn.
    weighted = curves.get("weighted")
    if weighted is not None:
        axes[1].plot(
            weighted["thresholds"], weighted["significance"], lw=2, color="crimson",
            label="weighted",
        )
    axes[1].set(xlabel="DNN_NNOutput threshold", ylabel=r"$S/\sqrt{S+B}$")
    for axis in axes:
        axis.grid(alpha=0.25)
        axis.legend(loc="lower right")
    figure.suptitle(title)
    figure.tight_layout()
    output_png.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_png, dpi=160)
    plt.close(figure)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--era",
        nargs="+",
        required=True,
        help="One or more eras, or 'all' for Run3_2022 through Run3_2026.",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Skim base directory containing Run3_<era>/<dataset>/.",
    )
    parser.add_argument("--region", default="Signal_Fit", help="Mass region selection column.")
    parser.add_argument("--category", default="VBF", help="Category selection column.")
    parser.add_argument(
        "--signal-generator",
        choices=("powheg", "amcatnlo", "all"),
        default="powheg",
        help="Signal set from config/dnn_studies.yaml.",
    )
    parser.add_argument(
        "--signal-process",
        action="append",
        default=None,
        help="Override the configured signal processes; repeatable.",
    )
    parser.add_argument(
        "--background-process",
        action="append",
        default=None,
        help="Override the configured background processes; repeatable.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output prefix, without extension. Writes <prefix>.json and <prefix>.png.",
    )
    parser.add_argument(
        "--per-era-output",
        action="store_true",
        help="Also write <prefix>_<era>.png for every era.",
    )
    parser.add_argument(
        "--dy-weights",
        default="jet-component,ptll,njets",
        help=(
            "Custom DY reweights to apply, among jet-component, ptll and njets; "
            "empty disables all three. Only the selected payloads must exist."
        ),
    )
    parser.add_argument(
        "--threads", type=int, default=4, help="RDataFrame worker threads (default: 4)."
    )
    parser.add_argument(
        "--max-files-per-dataset",
        type=int,
        default=0,
        help=(
            "Read at most this many ROOT files per MC dataset, evenly spaced over "
            "the whole dataset, and scale the weights by n_all/n_used. 0 reads "
            "everything. Cuts memory and wall time roughly proportionally; the "
            "ROC shape is unchanged, only its statistical precision drops."
        ),
    )
    parser.add_argument(
        "--no-region-sample-routing",
        dest="region_sample_routing",
        action="store_false",
        help="Keep DY/EWK samples outside their default generated mass region.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_arguments()
    if args.threads < 1:
        raise SystemExit("--threads must be at least 1")

    dy_weights = frozenset(
        x for x in args.dy_weights.replace(",", " ").split() if x
    )
    unknown = dy_weights - {"jet-component", "ptll", "njets"}
    if unknown:
        raise SystemExit("Unknown DY weight: " + ",".join(sorted(unknown)))
    eras = ALL_ERAS if args.era == ["all"] else [normalized_era(era) for era in args.era]
    unknown = sorted(set(eras) - set(ALL_ERAS))
    if unknown:
        raise SystemExit(f"unknown era(s): {', '.join(unknown)}")

    load_dnn_studies_config()
    wanted_signal = args.signal_process or signal_processes(args.signal_generator)
    wanted_background = args.background_process or background_processes()
    selection_expression = f"{args.region} && {args.category}"

    initialize_root_runtime()
    import ROOT

    if args.threads > 1:
        ROOT.EnableImplicitMT(args.threads)

    print(f"Selection: {selection_expression}")
    print(f"Signal processes:     {', '.join(wanted_signal)}")
    print(f"Background processes: {', '.join(wanted_background)}")

    per_era = {}
    signal_chunks, background_chunks = [], []
    for era in eras:
        print(f"\n{era}")
        config_dir = Path(ANALYSIS_PATH) / "config" / era
        selections_cfg = get_config(str(config_dir / "selections.yaml"))
        systematics_cfg = get_config(str(config_dir / "systematics.yaml"))
        samples_cfg = get_config(str(config_dir / "samples.yaml"))

        era_chunks = {"signal": [], "background": []}
        for role, processes in (
            ("signal", wanted_signal),
            ("background", wanted_background),
        ):
            resolved = datasets_for_processes(era, processes)
            skipped = [name for name in processes if name not in resolved]
            if skipped:
                print(f"  {role}: not configured in {era}: {', '.join(skipped)}")
            for process, datasets in resolved.items():
                for dataset in datasets:
                    if args.region_sample_routing and not dataset_region_allowed(
                        dataset, args.region
                    ):
                        print(f"    {dataset}: routed away from {args.region}, skipped")
                        continue
                    era_chunks[role].append(
                        read_dataset(
                            dataset,
                            era=era,
                            input_dir=args.input_dir,
                            selections_cfg=selections_cfg,
                            systematics_cfg=systematics_cfg,
                            samples_cfg=samples_cfg,
                            selection_expression=selection_expression,
                            dy_weights=dy_weights,
                            max_files=args.max_files_per_dataset,
                        )
                    )

        for role in ("signal", "background"):
            if not era_chunks[role]:
                raise RuntimeError(f"{era}: no {role} events selected")

        era_signal = (
            np.concatenate([chunk[0] for chunk in era_chunks["signal"]]),
            np.concatenate([chunk[1] for chunk in era_chunks["signal"]]),
        )
        era_background = (
            np.concatenate([chunk[0] for chunk in era_chunks["background"]]),
            np.concatenate([chunk[1] for chunk in era_chunks["background"]]),
        )
        signal_chunks.append(era_signal)
        background_chunks.append(era_background)

        era_curves = {
            "unweighted": roc_from_scores(
                era_signal[0],
                np.ones_like(era_signal[0]),
                era_background[0],
                np.ones_like(era_background[0]),
            ),
            "weighted": roc_from_scores(
                era_signal[0], era_signal[1], era_background[0], era_background[1]
            ),
        }
        per_era[era] = era_curves
        for label, result in era_curves.items():
            print(
                f"  {label:11s} AUC={result['auc']:.5f}  "
                f"best S/sqrt(S+B)={result['best_significance']:.5g} "
                f"at DNN>{result['best_threshold']:.5g}"
            )
        if args.per_era_output:
            write_plot(
                era_curves,
                args.output.with_name(f"{args.output.name}_{era}.png"),
                f"{era} — {selection_expression}",
            )

    combined_signal = (
        np.concatenate([chunk[0] for chunk in signal_chunks]),
        np.concatenate([chunk[1] for chunk in signal_chunks]),
    )
    combined_background = (
        np.concatenate([chunk[0] for chunk in background_chunks]),
        np.concatenate([chunk[1] for chunk in background_chunks]),
    )
    combined = {
        "unweighted": roc_from_scores(
            combined_signal[0],
            np.ones_like(combined_signal[0]),
            combined_background[0],
            np.ones_like(combined_background[0]),
        ),
        "weighted": roc_from_scores(
            combined_signal[0],
            combined_signal[1],
            combined_background[0],
            combined_background[1],
        ),
    }

    title = f"{'+'.join(era.replace('Run3_', '') for era in eras)} — {selection_expression}"
    write_plot(combined, args.output.with_suffix(".png"), title)

    payload = {
        "eras": eras,
        "input_dir": str(args.input_dir),
        "dy_weights": sorted(dy_weights),
        "selection": selection_expression,
        "signal_generator": args.signal_generator,
        "signal_processes": wanted_signal,
        "background_processes": wanted_background,
        "region_sample_routing": args.region_sample_routing,
        "max_files_per_dataset": args.max_files_per_dataset,
        "notes": {
            "unweighted": (
                "ROC on raw event counts. best_significance is entries-based "
                "and is not a physics sensitivity."
            ),
            "weighted": "weight__Central, i.e. expected yields.",
            "subset": (
                "max_files_per_dataset > 0 means only that many evenly spaced "
                "ROOT files per dataset were read, with weights scaled by "
                "n_all/n_used: yields stay unbiased, statistical precision drops."
            ),
        },
        "combined_curves": {
            label: thinned(result) for label, result in combined.items()
        },
        "combined_summary": {
            label: compact(result) for label, result in combined.items()
        },
        "per_era_summary": {
            era: {label: compact(result) for label, result in curves.items()}
            for era, curves in per_era.items()
        },
    }
    json_path = args.output.with_suffix(".json")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    with json_path.open("w") as handle:
        json.dump(payload, handle, indent=2)

    print()
    for label, result in combined.items():
        print(f"combined {label:11s} AUC={result['auc']:.6f}")
    print(f"Wrote {args.output.with_suffix('.png')}")
    print(f"Wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
