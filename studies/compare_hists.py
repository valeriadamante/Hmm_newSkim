#!/usr/bin/env python3

import os
import sys
import argparse
import array
import ROOT
import numpy as np
import matplotlib.pyplot as plt
import mplhep as hep

plt.style.use(hep.style.CMS)

ANALYSIS_PATH = os.environ.get(
    "ANALYSIS_PATH",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..")),
)

if __name__ == "__main__":
    sys.path.append(ANALYSIS_PATH)

import common.utilities as utilities
from common.utilities import findBinEntry, findNewBins, getNewBins


def get_hist(root_file, region, variable):
    f = ROOT.TFile.Open(root_file, "READ")
    if not f or f.IsZombie():
        raise RuntimeError(f"Cannot open file: {root_file}")

    h = f.Get(f"{region}/{variable}")
    if not h:
        f.Close()
        raise RuntimeError(f"Histogram not found: {region}/{variable} in {root_file}")

    h = h.Clone(f"{os.path.basename(root_file)}_{region}_{variable}_clone")
    h.SetDirectory(0)
    f.Close()

    return h


def parse_rebin_edges(edges_string):
    if edges_string is None:
        return None

    edges = [float(x.strip()) for x in edges_string.split(",") if x.strip()]

    if len(edges) < 2:
        raise RuntimeError("--rebin-edges requires at least two edges")

    if any(edges[i] >= edges[i + 1] for i in range(len(edges) - 1)):
        raise RuntimeError("--rebin-edges must be strictly increasing")

    return edges


def get_rebin_edges_from_config(config_path, variable, region):
    hist_cfg = utilities.get_config(config_path)
    var_entry = findBinEntry(hist_cfg, variable)
    bins_to_compute = findNewBins(hist_cfg, var_entry, dir_name=region)
    edges = [float(edge) for edge in getNewBins(bins_to_compute)]

    if len(edges) < 2:
        raise RuntimeError(
            f"Histogram config for '{variable}' did not provide usable bin edges."
        )

    return edges


def apply_rebin(hist, rebin=None, rebin_edges=None):
    hist = hist.Clone(f"{hist.GetName()}_before_rebin")
    hist.SetDirectory(0)

    if rebin_edges is not None:
        edges = array.array("d", rebin_edges)
        rebinned = hist.Rebin(
            len(rebin_edges) - 1,
            f"{hist.GetName()}_variable_rebin",
            edges,
        )
        rebinned.SetDirectory(0)
        return rebinned

    if rebin is not None and rebin > 1:
        rebinned = hist.Rebin(rebin, f"{hist.GetName()}_rebin{rebin}")
        rebinned.SetDirectory(0)
        return rebinned

    return hist


def hist_to_numpy(hist, overflow=True, divide_by_bin_width=False):
    nbins = hist.GetNbinsX()

    edges = np.array(
        [hist.GetBinLowEdge(i) for i in range(1, nbins + 2)],
        dtype=float,
    )

    values = np.array(
        [hist.GetBinContent(i) for i in range(1, nbins + 1)],
        dtype=float,
    )

    errors = np.array(
        [hist.GetBinError(i) for i in range(1, nbins + 1)],
        dtype=float,
    )

    if overflow and nbins > 0:
        values[0] += hist.GetBinContent(0)
        errors[0] = np.sqrt(errors[0] ** 2 + hist.GetBinError(0) ** 2)

        values[-1] += hist.GetBinContent(nbins + 1)
        errors[-1] = np.sqrt(errors[-1] ** 2 + hist.GetBinError(nbins + 1) ** 2)

    if divide_by_bin_width:
        widths = np.diff(edges)

        values = np.divide(
            values,
            widths,
            out=np.zeros_like(values),
            where=widths != 0,
        )

        errors = np.divide(
            errors,
            widths,
            out=np.zeros_like(errors),
            where=widths != 0,
        )

    centers = 0.5 * (edges[:-1] + edges[1:])

    return centers, edges, values, errors


def safe_max(*arrays, default=1.0):
    vals = []

    for arr in arrays:
        arr = np.asarray(arr, dtype=float)
        finite = arr[np.isfinite(arr)]
        if len(finite):
            vals.append(np.max(finite))

    if not vals:
        return default

    return max(vals)


def ratio_and_unc(num, num_err, den, den_err):
    ratio = np.full_like(num, np.nan, dtype=float)
    ratio_num_err = np.full_like(num, np.nan, dtype=float)
    ratio_den_rel_err = np.full_like(num, np.nan, dtype=float)

    valid = (
        np.isfinite(num)
        & np.isfinite(num_err)
        & np.isfinite(den)
        & np.isfinite(den_err)
        & (den != 0)
    )

    ratio[valid] = num[valid] / den[valid]
    ratio_num_err[valid] = np.abs(num_err[valid] / den[valid])
    ratio_den_rel_err[valid] = np.abs(den_err[valid] / den[valid])

    return ratio, ratio_num_err, ratio_den_rel_err


def extend_to_bin_edges(values):
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return values
    return np.r_[values, values[-1]]


def plot_compare(
    file_a,
    file_b,
    region,
    variable,
    label_a,
    label_b,
    output,
    ratio_label=None,
    rebin=None,
    rebin_edges=None,
    rebin_from_config=False,
    hist_config=None,
    overflow=True,
    divide_by_bin_width=False,
    normalize=False,
    logy=True,
    ratio_ylim=(0.5, 1.5),
    lumi=109.99,
    year="2024",
    energy=13.6,
    cms_label="Preliminary",
    xlabel=None,
    ylabel=None,
):
    h_a = get_hist(file_a, region, variable)
    h_b = get_hist(file_b, region, variable)

    if rebin_edges is None and rebin_from_config:
        rebin_edges = get_rebin_edges_from_config(hist_config, variable, region)
        print(f"[INFO] Using {len(rebin_edges) - 1} bins from {hist_config}")

    h_a = apply_rebin(h_a, rebin=rebin, rebin_edges=rebin_edges)
    h_b = apply_rebin(h_b, rebin=rebin, rebin_edges=rebin_edges)

    if normalize:
        if h_a.Integral() != 0:
            h_a.Scale(1.0 / h_a.Integral())
        if h_b.Integral() != 0:
            h_b.Scale(1.0 / h_b.Integral())

    x, edges, y_a, e_a = hist_to_numpy(
        h_a,
        overflow=overflow,
        divide_by_bin_width=divide_by_bin_width,
    )

    _, edges_b, y_b, e_b = hist_to_numpy(
        h_b,
        overflow=overflow,
        divide_by_bin_width=divide_by_bin_width,
    )

    if len(edges) != len(edges_b) or not np.allclose(edges, edges_b):
        raise RuntimeError("Histograms have different binning after rebinning.")

    ratio, ratio_num_err, ratio_den_rel_err = ratio_and_unc(y_a, e_a, y_b, e_b)

    fig, (ax, rax) = plt.subplots(
        2,
        1,
        figsize=(20, 10),
        sharex=True,
        gridspec_kw={
            "height_ratios": [3, 1],
            "hspace": 0.05,
        },
    )

    color_a = "C0"
    color_b = "C1"

    ax.errorbar(
        x,
        y_a,
        yerr=np.abs(e_a),
        fmt="o",
        color=color_a,
        markersize=3,
        label=f"{label_a} [{h_a.Integral():.2f}]",
    )

    hep.histplot(
        y_b,
        bins=edges,
        yerr=np.abs(e_b),
        histtype="step",
        color=color_b,
        linewidth=1.5,
        label=f"{label_b} [{h_b.Integral():.2f}]",
        ax=ax,
    )

    ax.set_ylabel(ylabel if ylabel else ("Events / bin width" if divide_by_bin_width else "Events"))
    ax.legend(frameon=True, fontsize=12)
    ax.grid(False)

    if logy:
        ax.set_yscale("log")
        ymax = safe_max(y_a + e_a, y_b + e_b)
        ax.set_ylim(max(1e-3, ymax * 1e-6), ymax * 20)
    else:
        ymax = safe_max(y_a + e_a, y_b + e_b)
        ax.set_ylim(0.0, ymax * 1.35)

    hep.cms.label(
        label=cms_label,
        data=False,
        lumi=float(lumi),
        year=year,
        com=float(energy),
        ax=ax,
        loc=0,

    )

    valid_ratio = (
        np.isfinite(ratio)
        & np.isfinite(ratio_num_err)
        & (ratio_num_err >= 0)
    )

    rax.axhline(1.0, linestyle="--", linewidth=1.0)

    ratio_band_valid = np.isfinite(ratio_den_rel_err)
    ratio_band_low = np.where(
        ratio_band_valid,
        np.maximum(1.0 - ratio_den_rel_err, 0.0),
        np.nan,
    )
    ratio_band_high = np.where(
        ratio_band_valid,
        1.0 + ratio_den_rel_err,
        np.nan,
    )

    rax.fill_between(
        edges,
        extend_to_bin_edges(ratio_band_low),
        extend_to_bin_edges(ratio_band_high),
        step="post",
        color=color_b,
        alpha=0.25,
        linewidth=0,
        label=f"{label_b} stat. unc.",
        zorder=1,
    )

    rax.errorbar(
        x[valid_ratio],
        ratio[valid_ratio],
        yerr=ratio_num_err[valid_ratio],
        fmt="o",
        color=color_a,
        markersize=3,
        label=f"{label_a} stat. unc.",
        zorder=2,
    )

    # I nomi di processo sono lunghi (EWK_2Mu2J_MLL_105to160_herwig_Flashsim e
    # simili) e sull'asse del rapporto diventano illeggibili. La legenda sopra
    # li riporta per intero, qui basta dire quale rapporto e'.
    # Il pannello del rapporto e' alto un quarto della figura: un'etichetta
    # lunga viene tagliata ai bordi, quindi il corpo si riduce con la lunghezza.
    rax_label = ratio_label if ratio_label else f"{label_a} / {label_b}"
    rax.set_ylabel(
        rax_label,
        fontsize=min(
            plt.rcParams["axes.labelsize"]
            if isinstance(plt.rcParams["axes.labelsize"], (int, float))
            else 20.0,
            max(9.0, 260.0 / max(len(rax_label), 1)),
        ),
    )
    rax.set_xlabel(xlabel if xlabel else variable)
    rax.set_ylim(*ratio_ylim)
    rax.grid(False)

    output_base, output_ext = os.path.splitext(output)

    if output_ext:
        fig.savefig(output, bbox_inches="tight")
        print(f"Saved: {output}")
    else:
        fig.savefig(f"{output}.png", bbox_inches="tight")
        fig.savefig(f"{output}.pdf", bbox_inches="tight")
        print(f"Saved: {output}.png")
        print(f"Saved: {output}.pdf")

    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(
        description="Flexible comparison plotter for two ROOT histograms."
    )

    parser.add_argument("file_a")
    parser.add_argument("file_b")

    parser.add_argument("-r", "--region", required=True)
    parser.add_argument("-v", "--variable", required=True)

    parser.add_argument("--label-a", default="Sample A")
    parser.add_argument("--label-b", default="Sample B")
    parser.add_argument(
        "--ratio-label",
        default=None,
        help="Etichetta dell'asse y del pannello rapporto; default: '<label-a> / <label-b>'.",
    )

    parser.add_argument("-o", "--output", default="comparison")

    parser.add_argument(
        "--rebin",
        type=int,
        default=None,
        help="Fixed rebin factor, e.g. --rebin 5",
    )

    parser.add_argument(
        "--rebin-edges",
        default=None,
        help="Variable bin edges, e.g. 0,0.1,0.2,0.4,0.6,0.8,1.0",
    )

    parser.add_argument(
        "--rebin-from-config",
        action="store_true",
        help="Use bin edges from config/plot/histograms.yaml for --variable.",
    )

    parser.add_argument(
        "--hist-config",
        default=None,
        help="Histogram config path used with --rebin-from-config.",
    )

    parser.add_argument(
        "--no-overflow",
        action="store_true",
        help="Do not add underflow/overflow to first/last visible bins.",
    )

    parser.add_argument(
        "--divide-by-bin-width",
        action="store_true",
        help="Divide contents and errors by bin width.",
    )

    parser.add_argument(
        "--normalize",
        action="store_true",
        help="Normalize both histograms to unit area before plotting.",
    )

    parser.add_argument(
        "--linear",
        action="store_true",
        help="Use linear y-axis instead of log.",
    )

    parser.add_argument("--ratio-min", type=float, default=0.5)
    parser.add_argument("--ratio-max", type=float, default=1.5)

    parser.add_argument("--lumi", type=float, default=109.99)
    parser.add_argument("--year", default="2024")
    parser.add_argument("--energy", type=float, default=13.6)
    parser.add_argument("--cms-label", default="Preliminary")

    parser.add_argument("--xlabel", default=None)
    parser.add_argument("--ylabel", default=None)

    args = parser.parse_args()

    rebin_edges = parse_rebin_edges(args.rebin_edges)
    hist_config = args.hist_config or os.path.join(
        ANALYSIS_PATH,
        "config",
        "plot",
        "histograms.yaml",
    )

    plot_compare(
        file_a=args.file_a,
        file_b=args.file_b,
        region=args.region,
        variable=args.variable,
        label_a=args.label_a,
        label_b=args.label_b,
        ratio_label=args.ratio_label,
        output=args.output,
        rebin=args.rebin,
        rebin_edges=rebin_edges,
        rebin_from_config=args.rebin_from_config,
        hist_config=hist_config,
        overflow=not args.no_overflow,
        divide_by_bin_width=args.divide_by_bin_width,
        normalize=args.normalize,
        logy=not args.linear,
        ratio_ylim=(args.ratio_min, args.ratio_max),
        lumi=args.lumi,
        year=args.year,
        energy=args.energy,
        cms_label=f"{args.cms_label} VBF H",
        xlabel=args.xlabel,
        ylabel=args.ylabel,
    )


if __name__ == "__main__":
    main()
