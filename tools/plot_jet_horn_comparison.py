#!/usr/bin/env python3
"""Compare 2024 and 2025 jet-horn campaigns with Data/DY ratio panels."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import matplotlib.pyplot as plt
import mplhep as hep
import numpy as np
import uproot

import common.utilities as utilities
from common.utilities import (
    findBinEntry, findNewBins, getNewBins, groups_for_region, load_routing,
)


DEFAULT_BASE = Path("/eos/user/v/vdamante/H_mumu/campaigns/JetHornVetoComparison")
REPOSITORY = Path(__file__).resolve().parents[1]
CAMPAIGNS_2025 = (
    ("2025 with horn veto", "WithHornVeto/Central_hadded/Run3_2025", "#e41a1c"),
    ("2025 without horn veto", "NoHornVeto/Central_hadded/Run3_2025", "#1746ff"),
)
CAMPAIGN_2024 = ("2024", "WithHornVeto/Central_hadded/Run3_2024", "#006400")
CAMPAIGNS_2026 = (
    ("2026 with horn veto", "WithHornVeto/Central_hadded/Run3_2026", "#e41a1c"),
    ("2026 without horn veto", "NoHornVeto/Central_hadded/Run3_2026", "#6a3d9a"),
)
LUMINOSITY_FB = {"2024": 109.94818, "2025": 110.73086, "2026": 25.843261130615}
REGION_LABELS = {
    "Signal_Fit_VBF": "VBF Signal Fit",
    "Z_sideband_VBF": "VBF Z",
    "Signal_Fit_ggF": "ggF Signal Fit",
    "Z_sideband_ggF": "ggF Z",
    "Signal_Fit_baseline": "Baseline Signal Fit",
    "Z_sideband_baseline": "Baseline Z",
}


def histogram_keys(path: Path) -> set[str]:
    with uproot.open(path) as root_file:
        return {
            key.split(";")[0]
            for key, classname in root_file.classnames(recursive=True).items()
            if classname.startswith("TH1")
        }


def read_histogram(path: Path, key: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    with uproot.open(path) as root_file:
        histogram = root_file[key]
        values = np.asarray(histogram.values(), dtype=float)
        edges = np.asarray(histogram.axis().edges(), dtype=float)
        variances = histogram.variances()
        errors = np.sqrt(np.maximum(0.0, variances)) if variances is not None else np.sqrt(np.maximum(0.0, values))
    return values, edges, errors


def rebin_histogram(
    histogram: tuple[np.ndarray, np.ndarray, np.ndarray],
    desired_binning: list[float] | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    values, edges, errors = histogram
    if not desired_binning:
        return histogram

    # Match RebinHisto/AdaptBinningToHistogram: snap every configured edge to
    # the nearest existing ROOT bin edge, discard duplicates, and do not fold
    # underflow/overflow into the visible range.
    adapted = sorted({
        float(edges[np.argmin(np.abs(edges - requested_edge))])
        for requested_edge in desired_binning
    })
    if len(adapted) < 2:
        raise RuntimeError(
            f"Configured rebinning has fewer than two usable edges: {adapted}"
        )

    indices = [int(np.flatnonzero(np.isclose(edges, edge))[0]) for edge in adapted]
    rebinned_values = np.asarray([
        np.sum(values[start:stop])
        for start, stop in zip(indices[:-1], indices[1:])
    ])
    rebinned_errors = np.asarray([
        np.sqrt(np.sum(np.square(errors[start:stop])))
        for start, stop in zip(indices[:-1], indices[1:])
    ])

    # Match FixNegativeContributions used by the generic plotter.
    negative = rebinned_values < 0
    rebinned_errors[negative] = np.sqrt(
        np.square(np.abs(rebinned_values[negative]))
        + np.square(rebinned_errors[negative])
    )
    rebinned_values[negative] = 0.0
    rebinned_edges = np.asarray(adapted)
    return rebinned_values, rebinned_edges, rebinned_errors


def safe_name(key: str) -> str:
    return key.replace("/", "__").replace(" ", "_")


def configured_rebinning(
    histogram_config: dict, variable: str, region: str
) -> list[float]:
    entry = findBinEntry(histogram_config, variable)
    if "x_rebin" in histogram_config[entry]:
        bins = findNewBins(histogram_config, entry, dir_name=region)
    else:
        bins = histogram_config[entry].get("x_bins", [])
    return [float(edge) for edge in getNewBins(bins)]


# Il DY da confrontare dipende dalla regione in massa, esattamente come nella
# produzione: 105-160 in Signal_Fit e H_sideband, inclusivo nelle sidebands.
# Cosi' le regioni che non usano il DY inclusivo si possono plottare anche
# quando quello inclusivo non e' ancora pronto.
DY_PROCESS_BY_GROUP = {
    "DY_amcatnlo": "DY",
    "DY_amcatnlo_105_160": "DYto2Mu_MLL105To160",
}


def dy_file_name(era: str, region: str, override: str | None = None) -> str:
    if override:
        return override if override.endswith(".root") else override + ".root"
    routing = load_routing(REPOSITORY / "config/histogram_sample_routing.yaml")
    mass_region = region.rsplit("_", 1)[0] if region.count("_") else region
    for candidate in ("Signal_Fit", "H_sideband", "Z_sideband", "mass_inclusive"):
        if region.startswith(candidate):
            mass_region = candidate
            break
    for group in groups_for_region(routing, f"Run3_{era}", mass_region):
        if group in DY_PROCESS_BY_GROUP:
            return DY_PROCESS_BY_GROUP[group] + ".root"
    raise RuntimeError(f"No DY group routed to {mass_region} in Run3_{era}")


def plot_one(
    base: Path, output: Path, key: str,
    campaigns: tuple[tuple[str, str, str], ...],
    histogram_config: dict | None = None,
    normalize_to_reference_data: bool = False,
    normalize_dy_to_data: bool = False,
    comparison: str = "2025-horn",
    dy_process: str | None = None,
) -> None:
    region, variable = key.rsplit("/", 1)
    era = "2026" if comparison.startswith("2026") else "2025"
    dy_name = dy_file_name(era, region, dy_process)
    desired_binning = (
        configured_rebinning(histogram_config, variable, region)
        if histogram_config is not None else None
    )
    payload = []
    for entry in campaigns:
        label, relative, color = entry[:3]
        name = entry[3] if len(entry) > 3 else dy_name
        folder = base / relative
        data = rebin_histogram(
            read_histogram(folder / "Data_Muon.root", key), desired_binning
        )
        dy = rebin_histogram(
            read_histogram(folder / name, key), desired_binning
        )
        if not np.array_equal(data[1], dy[1]):
            raise RuntimeError(f"Data/DY binning mismatch for {label}: {key}")
        payload.append((label, color, data, dy))

    reference_label = payload[0][0]
    reference = float(np.sum(payload[0][2][0]))
    if normalize_to_reference_data and reference <= 0:
        print(f"[SKIP] Empty {reference_label} Data histogram: {key}")
        return

    if normalize_to_reference_data or normalize_dy_to_data:
        invalid_integrals = []
        for label, _, data, dy in payload:
            data_integral = float(np.sum(data[0]))
            dy_integral = float(np.sum(dy[0]))
            if data_integral <= 0 or dy_integral <= 0:
                invalid_integrals.append(
                    f"{label}: Data={data_integral:.6g}, DY={dy_integral:.6g}"
                )
        if invalid_integrals:
            print(
                f"[SKIP] Cannot normalize {key}; non-positive integral(s): "
                + "; ".join(invalid_integrals)
            )
            return

    hep.style.use("CMS")
    # Skims use sentinel-valued bins for unavailable jet observables. Trim only
    # common empty edge bins, preserving every bin populated in any campaign.
    occupied = np.zeros_like(payload[0][2][0], dtype=bool)
    for _, _, data, dy in payload:
        occupied |= (data[0] != 0) | (dy[0] != 0)
    populated_bins = np.flatnonzero(occupied)
    if populated_bins.size == 0:
        print(f"[SKIP] All compared Data/DY histograms have empty visible bins: {key}")
        return
    first, last = populated_bins[[0, -1]]

    fig, (axis, ratio_axis) = plt.subplots(
        2, 1, figsize=(9, 8), sharex=True,
        gridspec_kw={"height_ratios": (3.1, 1), "hspace": 0.04},
    )

    displayed_ratios = []
    for label, color, data, dy in payload:
        data_values, edges, data_errors = data
        dy_values, _, _ = dy
        data_values = data_values[first:last + 1]
        data_errors = data_errors[first:last + 1]
        dy_values = dy_values[first:last + 1]
        edges = edges[first:last + 2]
        centers = 0.5 * (edges[:-1] + edges[1:])

        if normalize_to_reference_data:
            data_scale = reference / np.sum(data_values)
            dy_scale = reference / np.sum(dy_values)
        elif normalize_dy_to_data:
            data_scale = 1.0
            dy_scale = np.sum(data_values) / np.sum(dy_values)
        else:
            data_scale = 1.0
            dy_scale = 1.0
        shown_data = data_values * data_scale
        shown_dy = dy_values * dy_scale

        axis.stairs(shown_dy, edges, color=color, linewidth=1.8, label=f"DY {label}")
        axis.errorbar(
            centers, shown_data, yerr=data_errors * data_scale,
            color=color, marker=".", linestyle="none", markersize=5,
            linewidth=1, label=f"Data {label}",
        )

        ratio = np.divide(shown_data, shown_dy, out=np.full_like(shown_data, np.nan), where=shown_dy != 0)
        ratio_error = np.divide(
            np.abs(data_errors * data_scale),
            np.abs(shown_dy),
            out=np.zeros_like(data_errors),
            where=shown_dy != 0,
        )
        displayed_ratios.extend((ratio - ratio_error, ratio + ratio_error))
        ratio_axis.errorbar(
            centers, ratio, yerr=ratio_error, color=color, marker=".",
            linestyle="-", linewidth=1.2, markersize=4, label=label,
        )

    axis.set_yscale("log")
    positive = [entry[2][0][first:last + 1][entry[2][0][first:last + 1] > 0] for entry in payload]
    positive = np.concatenate([entry for entry in positive if entry.size])
    axis.set_ylim(max(0.1, positive.min() * 0.3), None)
    axis.set_ylabel(
        f"Events normalized to {reference_label} data"
        if normalize_to_reference_data else "Events",
        fontsize=18,
    )
    axis.legend(ncol=2, fontsize=11, loc="best")
    if comparison.startswith("2024-2025"):
        hep.cms.label("Preliminary", data=True, ax=axis, rlabel="13.6 TeV")
        campaign_label = (
            f"2024: {LUMINOSITY_FB['2024']:.1f} fb$^{{-1}}$\n"
            f"2025: {LUMINOSITY_FB['2025']:.1f} fb$^{{-1}}$\n"
            f"{REGION_LABELS.get(region, region)}"
        )
    else:
        year = "2026" if comparison in {"2026-horn", "2026-nohorn"} else "2025"
        hep.cms.label(
            "Preliminary", data=True, ax=axis,
            rlabel=f"{LUMINOSITY_FB[year]:.1f} fb$^{{-1}}$ (13.6 TeV)",
        )
        campaign_label = f"{year}\n{REGION_LABELS.get(region, region)}"
    axis.text(
        0.98, 0.96, campaign_label, transform=axis.transAxes,
        ha="right", va="top", fontsize=11,
    )

    ratio_axis.axhspan(0.8, 1.2, color="#9ecae1", alpha=0.25, label="20% variation")
    ratio_axis.axhline(1.0, color="black", linewidth=1)
    finite_ratios = [
        values[np.isfinite(values)] for values in displayed_ratios
        if np.any(np.isfinite(values))
    ]
    max_deviation = max(
        (float(np.max(np.abs(values - 1.0))) for values in finite_ratios),
        default=0.1,
    )
    # Keep unity at the centre and never let the upper edge exceed 1.8.
    # Outliers remain clipped instead of making the informative bulk illegible.
    half_range = min(0.8, max(0.1, 1.15 * max_deviation))
    ratio_axis.set_ylim(1.0 - half_range, 1.0 + half_range)
    ratio_axis.set_ylabel("Data / DY", fontsize=18)
    ratio_axis.set_xlabel(key.rsplit("/", 1)[-1], fontsize=18)
    ratio_axis.legend(ncol=2, fontsize=9, loc="upper center")
    ratio_axis.grid(axis="y", alpha=0.2)
    fig.subplots_adjust(left=0.16, right=0.97, top=0.91, bottom=0.12)

    destination = output / key.rsplit("/", 1)[0]
    destination.mkdir(parents=True, exist_ok=True)
    stem = destination / key.rsplit("/", 1)[-1]
    fig.savefig(stem.with_suffix(".png"), dpi=160, bbox_inches="tight")
    fig.savefig(stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)
    print(f"[PLOT] {stem}.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--output", type=Path, default=Path("plots/jet_horn_comparison"))
    parser.add_argument("--region", action="append", help="Only plot this region; repeatable")
    parser.add_argument(
        "--dy-compare",
        help="Overlay two DY processes from one variant instead of the two horn "
             "variants, e.g. 'DYto2Mu_MLL105To160,DY'",
    )
    parser.add_argument(
        "--variant", default="WithHornVeto",
        help="Variant directory used by --dy-compare (default: WithHornVeto)",
    )
    parser.add_argument(
        "--dy-process",
        help="Force one DY process file for every region; default: the routed one "
             "(DYto2Mu_MLL105To160 in Signal_Fit/H_sideband, DY in the sidebands)",
    )
    parser.add_argument("--variable", action="append", help="Only plot this variable; repeatable")
    parser.add_argument(
        "--include-2024", action="store_true",
        help="Deprecated alias for --comparison 2024-2025",
    )
    parser.add_argument(
        "--comparison",
        choices=("2025-horn", "2024-2025", "2024-2025-horn", "2026-horn", "2026-nohorn"),
        default="2025-horn",
        help="Campaign curves to draw (default: 2025-horn)",
    )
    normalization = parser.add_mutually_exclusive_group()
    normalization.add_argument(
        "--normalize-to-reference-data", action="store_true",
        help="Normalize every curve to 2025 with-horn-veto Data (off by default)",
    )
    normalization.add_argument(
        "--normalize-dy-to-data", action="store_true",
        help="Scale DY to Data independently in each campaign",
    )
    parser.add_argument(
        "--rebin", action="store_true",
        help="Use the same configured binning as the generic histogram plotter",
    )
    args = parser.parse_args()

    histogram_config = None
    if args.rebin:
        histogram_config = utilities.get_config(
            os.path.join(REPOSITORY, "config", "plot", "histograms.yaml")
        )

    comparison = "2024-2025" if args.include_2024 else args.comparison
    if comparison == "2025-horn":
        campaigns = CAMPAIGNS_2025
    elif comparison == "2024-2025":
        campaigns = (CAMPAIGN_2024, CAMPAIGNS_2025[1])
    elif comparison == "2024-2025-horn":
        # 2024 (sempre con veto) accanto alle due varianti 2025.
        campaigns = (CAMPAIGN_2024, *CAMPAIGNS_2025)
    else:
        campaigns = CAMPAIGNS_2026
    era = "2026" if comparison.startswith("2026") else "2025"
    if args.dy_compare:
        # Due campioni DY nella stessa variante: stessi dati, stesse selezioni,
        # cambia solo il campione simulato.
        processes = [x.strip() for x in args.dy_compare.split(",") if x.strip()]
        if len(processes) != 2:
            raise SystemExit("--dy-compare takes exactly two comma-separated DY processes")
        relative = f"{args.variant}/Central_hadded/Run3_{era}"
        colors = ("#e41a1c", "#1746ff")
        campaigns = tuple(
            (f"{process} ({args.variant})", relative, color,
             process if process.endswith(".root") else process + ".root")
            for process, color in zip(processes, colors)
        )
    data_files = [args.base / entry[1] / "Data_Muon.root" for entry in campaigns]
    missing = [path for path in data_files if not path.is_file()]
    if missing:
        raise FileNotFoundError("Missing required ROOT files:\n" + "\n".join(map(str, missing)))

    keys = set.intersection(*(histogram_keys(path) for path in data_files))

    # Ogni regione usa il proprio DY: si plottano quelle il cui DY e' pronto e
    # si riportano le altre, invece di bloccare tutto il confronto.
    dy_keys: dict[str, set] = {}
    skipped: dict[str, set] = {}
    routed = set()
    for key in sorted(keys):
        name = (campaigns[0][3] if len(campaigns[0]) > 3
                else dy_file_name(era, key.rsplit("/", 1)[0], args.dy_process))
        if name not in dy_keys and name not in skipped:
            paths = [args.base / entry[1] / (entry[3] if len(entry) > 3 else name)
                     for entry in campaigns]
            absent = [path for path in paths if not path.is_file()]
            if absent:
                skipped[name] = {str(path) for path in absent}
            else:
                dy_keys[name] = set.intersection(*(histogram_keys(path) for path in paths))
        if name in dy_keys and key in dy_keys[name]:
            routed.add(key)
    for name, absent in sorted(skipped.items()):
        print(f"[SKIP] {name} not available, its regions are not plotted: "
              + ", ".join(sorted(absent)))
    keys = routed
    if args.region:
        regions = set(args.region)
        keys = {key for key in keys if key.rsplit("/", 1)[0] in regions}
    if args.variable:
        variables = set(args.variable)
        keys = {key for key in keys if key.rsplit("/", 1)[-1] in variables}

    if not keys:
        raise RuntimeError("No common histograms match the requested comparison")
    print(f"Common one-dimensional histograms: {len(keys)}")
    for key in sorted(keys):
        try:
            plot_one(
                args.base,
                args.output,
                key,
                campaigns=campaigns,
                histogram_config=histogram_config,
                normalize_to_reference_data=args.normalize_to_reference_data,
                normalize_dy_to_data=args.normalize_dy_to_data,
                comparison=comparison,
                dy_process=args.dy_process,
            )
        except KeyError as error:
            print(f"[SKIP] {key}: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
