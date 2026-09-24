#!/usr/bin/env python3

from __future__ import annotations

import argparse
import math
import os
import sys
from array import array
from pathlib import Path
from typing import Iterable

import ROOT

ANALYSIS_PATH = os.environ.get(
    "ANALYSIS_PATH", str(Path(__file__).resolve().parents[1])
)
if ANALYSIS_PATH not in sys.path:
    sys.path.insert(0, ANALYSIS_PATH)

from common.dnn_studies import (  # noqa: E402
    background_processes,
    object_path,
    signal_processes,
)

ROOT.gROOT.SetBatch(True)
ROOT.TH1.SetDefaultSumw2(True)


HISTOGRAM_PATH = object_path()

# Process composition comes from config/dnn_studies.yaml, shared with
# tools/optimize_dnn_binning.py and tools/compare_dnn_performance.py, so the
# three studies cannot drift apart. The names are process names, i.e. the file
# stems in Central_hadded/<era>/.
BACKGROUND_FILES = [f"{name}.root" for name in background_processes()]
POWHEG_SIGNAL_FILES = [f"{name}.root" for name in signal_processes("powheg")]
AMCATNLO_SIGNAL_FILES = [f"{name}.root" for name in signal_processes("amcatnlo")]


def resolve_existing(
    directory: Path,
    filenames: Iterable[str],
    label: str,
) -> list[str]:
    """Keep the files that exist, reporting the ones that do not.

    The shared process list covers every era: W exists from Run3_2024 onwards
    and W_NJets before it, VH_inclusive and TTH_inclusive are absent in
    Run3_2023BPix. Missing entries are reported rather than silently dropped.
    """
    filenames = list(filenames)
    present = [name for name in filenames if (directory / name).is_file()]
    missing = [name for name in filenames if name not in present]
    if missing:
        print(f"{label}: not present in {directory}: {', '.join(sorted(missing))}")
    if not present:
        raise FileNotFoundError(f"{label}: no input file found in {directory}")
    print(f"{label} ({len(present)}): {', '.join(present)}")
    return present


def load_histogram(
    filename: Path,
    histogram_path: str,
    unique_name: str,
) -> ROOT.TH1:
    """Load and detach one ROOT histogram."""

    root_file = ROOT.TFile.Open(str(filename), "READ")
    if not root_file or root_file.IsZombie():
        raise OSError(f"Could not open ROOT file: {filename}")

    histogram = root_file.Get(histogram_path)
    if not histogram:
        root_file.Close()
        raise KeyError(
            f"Histogram '{histogram_path}' was not found in {filename}"
        )

    histogram = histogram.Clone(unique_name)
    histogram.SetDirectory(0)
    histogram.Sumw2()
    root_file.Close()

    return histogram
def find_optimal_binning(
    signal,
    background,
    minimum_background=10.0,
    maximum_n_bins=None,
):
    """
    Trova il binning che massimizza:

        Z^2 = sum_k S_k^2 / B_k

    usando esclusivamente i bordi dell'istogramma originale e imponendo:

        B_k >= minimum_background

    per ogni bin finale.

    Restituisce il miglior risultato per ogni numero di bin.
    """

    n_original_bins = background.GetNbinsX()

    if signal.GetNbinsX() != n_original_bins:
        raise ValueError("Signal and background have different binning")

    if maximum_n_bins is None:
        maximum_n_bins = n_original_bins

    maximum_n_bins = min(maximum_n_bins, n_original_bins)

    # Prefix sums:
    # prefix_s[j] = somma dei bin originali da 1 a j
    prefix_s = [0.0] * (n_original_bins + 1)
    prefix_b = [0.0] * (n_original_bins + 1)

    for i_bin in range(1, n_original_bins + 1):
        prefix_s[i_bin] = (
            prefix_s[i_bin - 1] + signal.GetBinContent(i_bin)
        )
        prefix_b[i_bin] = (
            prefix_b[i_bin - 1] + background.GetBinContent(i_bin)
        )

    def interval_yields(first_index, last_index):
        """
        Intervallo di bin originali [first_index, last_index),
        con indici 0-based sui bordi.
        """
        s = prefix_s[last_index] - prefix_s[first_index]
        b = prefix_b[last_index] - prefix_b[first_index]
        return s, b

    # dp[n][j] = massimo Z^2 ottenibile dividendo i primi j bin
    # originali in esattamente n bin finali.
    minus_infinity = float("-inf")

    dp = [
        [minus_infinity] * (n_original_bins + 1)
        for _ in range(maximum_n_bins + 1)
    ]

    # previous[n][j] contiene il bordo precedente della soluzione ottimale.
    previous = [
        [None] * (n_original_bins + 1)
        for _ in range(maximum_n_bins + 1)
    ]

    dp[0][0] = 0.0

    for n_bins in range(1, maximum_n_bins + 1):
        for right_edge in range(1, n_original_bins + 1):

            # Servono almeno n_bins bin originali per costruire n_bins finali.
            if right_edge < n_bins:
                continue

            # L'ultimo bin finale parte da left_edge e termina a right_edge.
            for left_edge in range(n_bins - 1, right_edge):

                if dp[n_bins - 1][left_edge] == minus_infinity:
                    continue

                signal_yield, background_yield = interval_yields(
                    left_edge,
                    right_edge,
                )

                if background_yield < minimum_background:
                    continue

                if background_yield <= 0.0:
                    continue

                contribution = signal_yield**2 / background_yield

                candidate = (
                    dp[n_bins - 1][left_edge] + contribution
                )

                if candidate > dp[n_bins][right_edge]:
                    dp[n_bins][right_edge] = candidate
                    previous[n_bins][right_edge] = left_edge

    original_edges = get_bin_edges(background)

    results = []

    for n_bins in range(1, maximum_n_bins + 1):
        best_z_squared = dp[n_bins][n_original_bins]

        if best_z_squared == minus_infinity:
            continue

        # Ricostruzione dei bordi ottimali.
        edge_indices = [n_original_bins]
        right_edge = n_original_bins
        current_n_bins = n_bins

        while current_n_bins > 0:
            left_edge = previous[current_n_bins][right_edge]

            if left_edge is None:
                raise RuntimeError(
                    "Could not reconstruct optimal binning"
                )

            edge_indices.append(left_edge)
            right_edge = left_edge
            current_n_bins -= 1

        edge_indices.reverse()

        optimal_edges = [
            original_edges[index]
            for index in edge_indices
        ]

        rebinned_signal = rebin_histogram(
            signal,
            optimal_edges,
            f"optimal_signal_{n_bins}",
        )
        rebinned_background = rebin_histogram(
            background,
            optimal_edges,
            f"optimal_background_{n_bins}",
        )

        sensitivity, sensitivity_error = calculate_sensitivity(
            rebinned_signal,
            rebinned_background,
        )

        minimum_b = min(
            rebinned_background.GetBinContent(i_bin)
            for i_bin in range(
                1,
                rebinned_background.GetNbinsX() + 1,
            )
        )

        results.append(
            {
                "n_bins": n_bins,
                "sensitivity": sensitivity,
                "sensitivity_error": sensitivity_error,
                "minimum_background": minimum_b,
                "edges": optimal_edges,
            }
        )

    return results

def validate_compatible_binning(
    reference: ROOT.TH1,
    candidate: ROOT.TH1,
    candidate_name: str,
    tolerance: float = 1.0e-10,
) -> None:
    """Check that two histograms have the same original binning."""

    if reference.GetNbinsX() != candidate.GetNbinsX():
        raise ValueError(
            f"Incompatible number of bins for {candidate_name}: "
            f"{candidate.GetNbinsX()} versus {reference.GetNbinsX()}"
        )

    reference_axis = reference.GetXaxis()
    candidate_axis = candidate.GetXaxis()

    for i_edge in range(1, reference.GetNbinsX() + 2):
        reference_edge = reference_axis.GetBinLowEdge(i_edge)
        candidate_edge = candidate_axis.GetBinLowEdge(i_edge)

        if not math.isclose(
            reference_edge,
            candidate_edge,
            rel_tol=0.0,
            abs_tol=tolerance,
        ):
            raise ValueError(
                f"Incompatible bin edge {i_edge} for {candidate_name}: "
                f"{candidate_edge} versus {reference_edge}"
            )


def sum_histograms(
    directory: Path,
    filenames: Iterable[str],
    histogram_path: str,
    output_name: str,
) -> ROOT.TH1:
    """Read and sum a collection of histograms."""

    filenames = list(filenames)
    if not filenames:
        raise ValueError(f"No files were provided for '{output_name}'")

    summed_histogram = None

    for index, filename in enumerate(filenames):
        full_path = directory / filename

        histogram = load_histogram(
            full_path,
            histogram_path,
            f"{output_name}_{index}",
        )

        if summed_histogram is None:
            summed_histogram = histogram.Clone(output_name)
            summed_histogram.SetDirectory(0)
            summed_histogram.Sumw2()
        else:
            validate_compatible_binning(
                summed_histogram,
                histogram,
                filename,
            )
            summed_histogram.Add(histogram)

    return summed_histogram


def get_bin_edges(histogram: ROOT.TH1) -> list[float]:
    """Return all visible-bin edges from a TH1."""

    axis = histogram.GetXaxis()
    n_bins = histogram.GetNbinsX()

    edges = [axis.GetBinLowEdge(i_bin) for i_bin in range(1, n_bins + 1)]
    edges.append(axis.GetBinUpEdge(n_bins))

    return edges


def build_adaptive_edges(
    background: ROOT.TH1,
    requested_n_bins: int,
    minimum_background: float,
) -> list[float] | None:
    """
    Construct at most requested_n_bins contiguous bins.

    Each final bin must contain at least minimum_background expected background
    events. Boundaries are chosen using approximately equal cumulative
    background yield.

    The method only uses the original histogram edges.
    """

    original_n_bins = background.GetNbinsX()
    original_edges = get_bin_edges(background)

    if requested_n_bins < 1 or requested_n_bins > original_n_bins:
        return None

    yields = [
        background.GetBinContent(i_bin)
        for i_bin in range(1, original_n_bins + 1)
    ]

    # Negative MC bins cannot sensibly be used for the minimum-yield condition.
    # They are retained later in the actual rebinned histogram, but zeroed for
    # the purpose of defining cumulative-statistics boundaries.
    yields_for_binning = [max(0.0, value) for value in yields]

    total_background = sum(yields_for_binning)

    if total_background < requested_n_bins * minimum_background:
        return None

    if requested_n_bins == 1:
        return [original_edges[0], original_edges[-1]]

    cumulative = []
    running_sum = 0.0
    for value in yields_for_binning:
        running_sum += value
        cumulative.append(running_sum)

    selected_edge_indices = [0]
    previous_edge_index = 0

    for boundary_number in range(1, requested_n_bins):
        target = total_background * boundary_number / requested_n_bins

        # A boundary after original bin j corresponds to original edge j + 1.
        edge_index = previous_edge_index + 1

        while (
            edge_index < original_n_bins
            and cumulative[edge_index - 1] < target
        ):
            edge_index += 1

        # Keep enough original bins available for all remaining final bins.
        maximum_allowed_edge = (
            original_n_bins - (requested_n_bins - boundary_number)
        )
        edge_index = min(edge_index, maximum_allowed_edge)
        edge_index = max(edge_index, previous_edge_index + 1)

        selected_edge_indices.append(edge_index)
        previous_edge_index = edge_index

    selected_edge_indices.append(original_n_bins)

    edges = [original_edges[index] for index in selected_edge_indices]

    if len(edges) != requested_n_bins + 1:
        return None

    if any(right <= left for left, right in zip(edges[:-1], edges[1:])):
        return None

    return edges


def rebin_histogram(
    histogram: ROOT.TH1,
    edges: list[float],
    output_name: str,
) -> ROOT.TH1:
    """Rebin a TH1 using explicit bin edges."""

    edge_array = array("d", edges)

    rebinned = histogram.Rebin(
        len(edges) - 1,
        output_name,
        edge_array,
    )
    rebinned.SetDirectory(0)
    rebinned.Sumw2()

    return rebinned


def all_bins_pass_minimum(
    histogram: ROOT.TH1,
    minimum_yield: float,
    tolerance: float = 1.0e-9,
) -> bool:
    return all(
        histogram.GetBinContent(i_bin) + tolerance >= minimum_yield
        for i_bin in range(1, histogram.GetNbinsX() + 1)
    )


def calculate_sensitivity(
    signal: ROOT.TH1,
    background: ROOT.TH1,
) -> tuple[float, float]:
    r"""
    Calculate

        Z = sqrt(sum_i s_i^2 / b_i)

    and propagate uncorrelated statistical errors from both s_i and b_i.

    For A = sum_i s_i^2 / b_i,

        dA/ds_i = 2 s_i / b_i
        dA/db_i = -s_i^2 / b_i^2
        Z = sqrt(A)
        sigma_Z = sigma_A / (2 Z)

    Bin errors are taken from TH1::GetBinError, so weighted MC Sumw2
    uncertainties are supported.
    """

    if signal.GetNbinsX() != background.GetNbinsX():
        raise ValueError("Signal and background have different bin counts")

    sensitivity_squared = 0.0
    sensitivity_squared_variance = 0.0

    for i_bin in range(1, signal.GetNbinsX() + 1):
        signal_yield = signal.GetBinContent(i_bin)
        background_yield = background.GetBinContent(i_bin)

        signal_error = signal.GetBinError(i_bin)
        background_error = background.GetBinError(i_bin)

        if background_yield <= 0.0:
            raise ValueError(
                f"Non-positive background yield in rebinned bin {i_bin}: "
                f"{background_yield}"
            )

        sensitivity_squared += signal_yield**2 / background_yield

        derivative_signal = 2.0 * signal_yield / background_yield
        derivative_background = (
            -(signal_yield**2) / background_yield**2
        )

        sensitivity_squared_variance += (
            derivative_signal * signal_error
        ) ** 2
        sensitivity_squared_variance += (
            derivative_background * background_error
        ) ** 2

    if sensitivity_squared <= 0.0:
        return 0.0, 0.0

    sensitivity = math.sqrt(sensitivity_squared)
    sensitivity_squared_error = math.sqrt(
        sensitivity_squared_variance
    )
    sensitivity_error = sensitivity_squared_error / (2.0 * sensitivity)

    return sensitivity, sensitivity_error


def scan_sensitivity(
    signal: ROOT.TH1,
    background: ROOT.TH1,
    minimum_background: float,
    maximum_n_bins: int | None,
) -> list[dict]:
    """Evaluate sensitivity for all allowed numbers of bins."""

    original_n_bins = background.GetNbinsX()

    if maximum_n_bins is None:
        maximum_n_bins = original_n_bins

    maximum_n_bins = min(maximum_n_bins, original_n_bins)

    results = []

    for requested_n_bins in range(1, maximum_n_bins + 1):
        edges = build_adaptive_edges(
            background=background,
            requested_n_bins=requested_n_bins,
            minimum_background=minimum_background,
        )

        if edges is None:
            continue

        rebinned_background = rebin_histogram(
            background,
            edges,
            f"background_rebinned_{requested_n_bins}",
        )
        rebinned_signal = rebin_histogram(
            signal,
            edges,
            f"signal_rebinned_{requested_n_bins}",
        )

        if not all_bins_pass_minimum(
            rebinned_background,
            minimum_background,
        ):
            continue

        sensitivity, sensitivity_error = calculate_sensitivity(
            rebinned_signal,
            rebinned_background,
        )

        minimum_observed_background = min(
            rebinned_background.GetBinContent(i_bin)
            for i_bin in range(1, rebinned_background.GetNbinsX() + 1)
        )

        results.append(
            {
                "n_bins": rebinned_background.GetNbinsX(),
                "sensitivity": sensitivity,
                "sensitivity_error": sensitivity_error,
                "minimum_background": minimum_observed_background,
                "edges": edges,
            }
        )

    return results


def make_plot(
    results: list[dict],
    output_prefix: Path,
    signal_label: str,
    minimum_background: float,
) -> None:
    """Create ROOT, PDF and PNG outputs."""

    if not results:
        raise RuntimeError(
            "No valid binning satisfies the minimum-background requirement"
        )

    x_values = array("d", [float(result["n_bins"]) for result in results])
    y_values = array(
        "d",
        [float(result["sensitivity"]) for result in results],
    )
    x_errors = array("d", [0.0] * len(results))
    y_errors = array(
        "d",
        [float(result["sensitivity_error"]) for result in results],
    )

    graph = ROOT.TGraphErrors(
        len(results),
        x_values,
        y_values,
        x_errors,
        y_errors,
    )
    graph.SetName("sensitivity_vs_nbins")
    graph.SetTitle(
        f"{signal_label};Number of rebinned bins;"
        "#sqrt{#Sigma_{i} s_{i}^{2}/b_{i}}"
    )
    graph.SetMarkerStyle(20)
    graph.SetMarkerSize(1.0)
    graph.SetLineWidth(2)

    canvas = ROOT.TCanvas(
        "canvas_sensitivity",
        "Sensitivity versus number of bins",
        900,
        700,
    )
    canvas.SetLeftMargin(0.13)
    canvas.SetBottomMargin(0.12)
    canvas.SetGridx()
    canvas.SetGridy()

    graph.Draw("AP")

    graph.GetXaxis().SetNdivisions(510)
    graph.GetXaxis().SetTitleSize(0.045)
    graph.GetYaxis().SetTitleSize(0.045)
    graph.GetXaxis().SetLabelSize(0.040)
    graph.GetYaxis().SetLabelSize(0.040)
    graph.GetYaxis().SetTitleOffset(1.25)

    latex = ROOT.TLatex()
    latex.SetNDC(True)
    latex.SetTextSize(0.035)
    latex.DrawLatex(
        0.15,
        0.92,
        f"Minimum expected background per bin: {minimum_background:g}",
    )
    latex.DrawLatex(
        0.15,
        0.875,
        "Error bars: propagated signal and background MC statistics",
    )

    canvas.Update()

    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    canvas.SaveAs(str(output_prefix.with_suffix(".pdf")))
    canvas.SaveAs(str(output_prefix.with_suffix(".png")))

    output_root = ROOT.TFile.Open(
        str(output_prefix.with_suffix(".root")),
        "RECREATE",
    )
    graph.Write()
    canvas.Write()
    output_root.Close()


def print_results(results: list[dict]) -> None:
    print()
    print(
        f"{'N bins':>8}  {'Sensitivity':>14}  "
        f"{'Stat. error':>14}  {'Min. b/bin':>14}"
    )
    print("-" * 60)

    for result in results:
        print(
            f"{result['n_bins']:8d}  "
            f"{result['sensitivity']:14.6f}  "
            f"{result['sensitivity_error']:14.6f}  "
            f"{result['minimum_background']:14.6f}"
        )

    best_result = max(results, key=lambda result: result["sensitivity"])

    print()
    print("Best sensitivity:")
    print(
        f"  N bins = {best_result['n_bins']}\n"
        f"  Z      = {best_result['sensitivity']:.6f} "
        f"+/- {best_result['sensitivity_error']:.6f}\n"
        f"  edges  = {best_result['edges']}"
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Plot sqrt(sum_i s_i^2 / b_i) as a function of the number "
            "of adaptively rebinned DNN bins."
        )
    )

    parser.add_argument(
        "--input-dir",
        type=Path,
        default=Path(
            "/eos/user/v/vdamante/H_mumu/"
            "Hists_Signal_Fit_VBF_Central_hadded/Run3_2024/"
        ),
        help="Directory containing the ROOT files.",
    )
    parser.add_argument(
        "--histogram",
        default=HISTOGRAM_PATH,
        help="Histogram path inside each ROOT file.",
    )
    parser.add_argument(
        "--signal-generator",
        choices=("powheg", "amcatnlo", "all"),
        default="powheg",
        help=(
            "Signal samples to sum. 'all' sums POWHEG and aMC@NLO, "
            "which is normally not appropriate if they represent alternative "
            "generators of the same processes."
        ),
    )
    parser.add_argument(
        "--minimum-background",
        type=float,
        default=10.0,
        help="Minimum expected summed background yield in every final bin.",
    )
    parser.add_argument(
        "--maximum-n-bins",
        type=int,
        default=None,
        help="Maximum number of final bins to test.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("sensitivity_vs_nbins"),
        help="Output prefix, without extension.",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_arguments()

    if not args.input_dir.is_dir():
        raise NotADirectoryError(
            f"Input directory does not exist: {args.input_dir}"
        )

    if args.minimum_background <= 0.0:
        raise ValueError("--minimum-background must be positive")

    if args.maximum_n_bins is not None and args.maximum_n_bins < 1:
        raise ValueError("--maximum-n-bins must be at least 1")

    if args.signal_generator == "powheg":
        signal_files = POWHEG_SIGNAL_FILES
        signal_label = "POWHEG ggH + VBF signal"
    elif args.signal_generator == "amcatnlo":
        signal_files = AMCATNLO_SIGNAL_FILES
        signal_label = "aMC@NLO ggH + VBF signal"
    else:
        signal_files = POWHEG_SIGNAL_FILES + AMCATNLO_SIGNAL_FILES
        signal_label = "POWHEG + aMC@NLO signal sum"

    print(f"Input directory: {args.input_dir}")
    print(f"Histogram:      {args.histogram}")
    print(f"Signal files:   {', '.join(signal_files)}")

    background = sum_histograms(
        directory=args.input_dir,
        filenames=resolve_existing(
            args.input_dir, BACKGROUND_FILES, "Background files"
        ),
        histogram_path=args.histogram,
        output_name="background_sum",
    )

    signal = sum_histograms(
        directory=args.input_dir,
        filenames=resolve_existing(args.input_dir, signal_files, "Signal files"),
        histogram_path=args.histogram,
        output_name="signal_sum",
    )

    validate_compatible_binning(
        background,
        signal,
        "summed signal",
    )

    # results = scan_sensitivity(
    #     signal=signal,
    #     background=background,
    #     minimum_background=args.minimum_background,
    #     maximum_n_bins=args.maximum_n_bins,
    # )
    results = find_optimal_binning(
        signal=signal,
        background=background,
        minimum_background=args.minimum_background,
        maximum_n_bins=args.maximum_n_bins,
    )
    print_results(results)

    make_plot(
        results=results,
        output_prefix=args.output,
        signal_label=signal_label,
        minimum_background=args.minimum_background,
    )

    print()
    print(f"Created {args.output.with_suffix('.pdf')}")
    print(f"Created {args.output.with_suffix('.png')}")
    print(f"Created {args.output.with_suffix('.root')}")


if __name__ == "__main__":
    main()