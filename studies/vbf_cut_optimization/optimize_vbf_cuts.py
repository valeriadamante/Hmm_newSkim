#!/usr/bin/env python3
"""Cut-based optimization of the VBF category on weighted skim events."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

import numpy as np
import yaml


VARIABLES = ("mjj", "detajj", "jet1_pt", "jet2_pt", "ptjj")
PAIRING_MODES = {
    "max_mjj": 0,
    "leading_pt": 1,
    "max_detajj": 2,
    "leading_pt_after_topology": 3,
    "max_ptjj": 4,
}
NJETS_BRANCH = "N_SelectedJets"


def parse_number_list(value):
    if isinstance(value, (list, tuple)):
        return np.asarray(value, dtype=float)
    return np.asarray([float(item) for item in str(value).split(",")], dtype=float)


def validate_thresholds(thresholds):
    parsed = {}
    for variable in VARIABLES:
        values = parse_number_list(thresholds[variable])
        if values.size == 0 or not np.all(np.isfinite(values)):
            raise ValueError(f"Invalid thresholds for {variable}")
        values = np.unique(values)
        if np.any(np.diff(values) <= 0):
            raise ValueError(f"Thresholds for {variable} must be increasing")
        parsed[variable] = values
    return parsed


def reverse_cumulative(values):
    """Inclusive cumulative sum from high to low on every axis."""
    result = np.asarray(values, dtype=float)
    for axis in range(result.ndim):
        result = np.flip(np.cumsum(np.flip(result, axis=axis), axis=axis), axis=axis)
    return result


def threshold_histogram(arrays, weights, thresholds):
    edges = [
        np.concatenate((thresholds[name], [np.inf]))
        for name in VARIABLES
    ]
    points = np.column_stack([np.asarray(arrays[name]) for name in VARIABLES])
    weights = np.asarray(weights, dtype=float)
    finite = np.isfinite(weights) & np.all(np.isfinite(points), axis=1)
    points = points[finite]
    weights = weights[finite]

    sumw, _ = np.histogramdd(points, bins=edges, weights=weights)
    sumw2, _ = np.histogramdd(points, bins=edges, weights=weights * weights)
    return reverse_cumulative(sumw), reverse_cumulative(sumw2)


def significance(signal, background, min_background=0.0):
    valid = (signal > 0.0) & (background > max(0.0, min_background))
    result = np.zeros_like(signal, dtype=float)
    np.divide(signal, np.sqrt(background), out=result, where=valid)
    return result


def declare_uncut_vbf_pair(ROOT):
    ROOT.gInterpreter.Declare(
        r"""
        #include <ROOT/RVec.hxx>
        #include <Math/Vector4D.h>
        #include <cmath>

        ROOT::VecOps::RVec<int> FindVBFPairForOptimization(
            const ROOT::VecOps::RVec<float>& pt,
            const ROOT::VecOps::RVec<float>& eta,
            const ROOT::VecOps::RVec<float>& phi,
            const ROOT::VecOps::RVec<float>& mass,
            const ROOT::VecOps::RVec<bool>& preselection,
            int mode,
            double topology_mjj,
            double topology_detajj)
        {
            ROOT::VecOps::RVec<int> result = {-1, -1};
            double best_score = -1.0;
            using P4 = ROOT::Math::PtEtaPhiMVector;

            for (std::size_t i = 0; i < pt.size(); ++i) {
                if (i >= preselection.size() || !preselection[i]) continue;
                for (std::size_t j = i + 1; j < pt.size(); ++j) {
                    if (j >= preselection.size() || !preselection[j]) continue;
                    const P4 p4_i(pt[i], eta[i], phi[i], mass[i]);
                    const P4 p4_j(pt[j], eta[j], phi[j], mass[j]);
                    const double mjj = (p4_i + p4_j).M();
                    const double detajj = std::abs(eta[i] - eta[j]);
                    if (mode == 3 && (mjj < topology_mjj || detajj < topology_detajj))
                        continue;

                    double score = mjj;
                    if (mode == 1 || mode == 3) score = pt[i] + pt[j];
                    if (mode == 2) score = detajj;
                    if (mode == 4) score = (p4_i + p4_j).Pt();

                    if (score > best_score) {
                        best_score = score;
                        result[0] = static_cast<int>(i);
                        result[1] = static_cast<int>(j);
                    }
                }
            }
            return result;
        }
        """
    )


def strategy_branches(strategy):
    return {
        variable: f"opt_{strategy}_{variable}"
        for variable in VARIABLES
    }


def define_optimization_columns(rdf, pairing_config):
    valid_columns = []
    for strategy in pairing_config["strategies"]:
        mode = PAIRING_MODES[strategy]
        pair = f"opt_{strategy}_pair"
        has_pair = f"opt_{strategy}_has_pair"
        p4_1 = f"opt_{strategy}_p4_1"
        p4_2 = f"opt_{strategy}_p4_2"
        rdf = rdf.Define(
            pair,
            "FindVBFPairForOptimization(SelectedJet_pt, SelectedJet_eta, "
            "SelectedJet_phi, SelectedJet_mass, SelectedJet_IsOutsideHorn, "
            f"{mode}, {float(pairing_config['topology_mjj'])}, "
            f"{float(pairing_config['topology_detajj'])})",
        )
        rdf = rdf.Define(has_pair, f"{pair}[0] >= 0 && {pair}[1] >= 0")
        rdf = rdf.Define(
            p4_1,
            f"{has_pair} ? ROOT::Math::PtEtaPhiMVector("
            f"SelectedJet_pt[{pair}[0]], SelectedJet_eta[{pair}[0]], "
            f"SelectedJet_phi[{pair}[0]], SelectedJet_mass[{pair}[0]]) : "
            "ROOT::Math::PtEtaPhiMVector(0., 0., 0., 0.)",
        )
        rdf = rdf.Define(
            p4_2,
            f"{has_pair} ? ROOT::Math::PtEtaPhiMVector("
            f"SelectedJet_pt[{pair}[1]], SelectedJet_eta[{pair}[1]], "
            f"SelectedJet_phi[{pair}[1]], SelectedJet_mass[{pair}[1]]) : "
            "ROOT::Math::PtEtaPhiMVector(0., 0., 0., 0.)",
        )
        branches = strategy_branches(strategy)
        rdf = rdf.Define(
            branches["mjj"],
            f"{has_pair} ? static_cast<float>(({p4_1} + {p4_2}).M()) : -1.f",
        )
        rdf = rdf.Define(
            branches["detajj"],
            f"{has_pair} ? static_cast<float>(std::abs({p4_1}.Eta() - {p4_2}.Eta())) : -1.f",
        )
        rdf = rdf.Define(
            branches["jet1_pt"],
            f"{has_pair} ? static_cast<float>(std::max({p4_1}.Pt(), {p4_2}.Pt())) : -1.f",
        )
        rdf = rdf.Define(
            branches["jet2_pt"],
            f"{has_pair} ? static_cast<float>(std::min({p4_1}.Pt(), {p4_2}.Pt())) : -1.f",
        )
        rdf = rdf.Define(
            branches["ptjj"],
            f"{has_pair} ? static_cast<float>(({p4_1} + {p4_2}).Pt()) : -1.f",
        )
        valid_columns.append(has_pair)
    rdf = rdf.Filter(
        " || ".join(valid_columns),
        "has_dijet_pair_for_at_least_one_strategy",
    )
    return rdf


def resolve_path(template, input_base, era, dataset):
    return str(template).format(input_base=input_base, era=era, dataset=dataset)


def sampling_stride(total_entries, max_events):
    if max_events is None or max_events <= 0 or total_entries <= max_events:
        return 1
    return int(np.ceil(float(total_entries) / float(max_events)))


def load_sample_arrays(sample, args, framework):
    ROOT, utilities, GetRdfForDataset, DefineHistogramSelections, configs = framework
    dataset = sample["name"]
    if dataset not in configs["samples"]:
        raise KeyError(f"Dataset '{dataset}' is not present in config/{args.era}/samples.yaml")

    path_template = sample.get("path", "{input_base}/{dataset}")
    input_path = resolve_path(path_template, args.input_base, args.era, dataset)
    if not Path(input_path).exists():
        raise FileNotFoundError(f"Input for {dataset} does not exist: {input_path}")

    rdf = GetRdfForDataset(
        input_dir=input_path,
        is_data=configs["samples"][dataset].get("is_data", False),
        weight_dict=configs["systematics"]["weights"],
        store_shifted_weights=False,
        treeName="Events",
        skip_validation=args.skip_file_validation,
        era=args.era,
    )
    if rdf is None:
        raise RuntimeError(f"No usable ROOT files found for {dataset}: {input_path}")

    stride = 1
    if args.max_events_per_sample:
        total_entries = int(rdf.Count().GetValue())
        stride = sampling_stride(total_entries, args.max_events_per_sample)
        if stride > 1:
            rdf = rdf.Filter(
                f"rdfentry_ % {stride} == 0",
                f"{dataset}_uniform_subsample_stride_{stride}",
            )
        estimated_entries = int(np.ceil(total_entries / stride))
        print(
            f"[INFO] {dataset}: sampling about {estimated_entries}/{total_entries} "
            f"events with stride {stride}; weights rescaled by {stride}"
        )

    rdf = DefineHistogramSelections(
        rdf,
        configs["selections"],
        syst_cfg=configs["systematics"],
        want_variations=False,
    )
    if sample.get("selection"):
        rdf = rdf.Filter(sample["selection"], f"{dataset}_sample_selection")
    rdf = rdf.Filter(args.preselection, f"{dataset}_optimization_preselection")
    rdf = define_optimization_columns(rdf, args.pairing_config)
    optimization_weight = "optimization_weight"
    rdf = rdf.Define(
        optimization_weight,
        f"static_cast<double>({args.weight}) * {stride}.0",
    )

    requested = [NJETS_BRANCH, optimization_weight]
    for strategy in args.pairing_config["strategies"]:
        requested.extend(strategy_branches(strategy).values())
    available = {str(column) for column in rdf.GetColumnNames()}
    missing = [column for column in requested if column not in available]
    if missing:
        raise RuntimeError(f"Missing columns for {dataset}: {', '.join(missing)}")

    print(f"[INFO] Reading weighted events for {dataset}")
    arrays = rdf.AsNumpy(requested)
    return (
        {
            strategy: {
                name: np.asarray(arrays[branch], dtype=float)
                for name, branch in strategy_branches(strategy).items()
            }
            for strategy in args.pairing_config["strategies"]
        },
        np.asarray(arrays[optimization_weight], dtype=float),
        np.asarray(arrays[NJETS_BRANCH], dtype=int),
    )


def load_framework(args):
    analysis_path = os.environ.get("ANALYSIS_PATH", str(Path(__file__).resolve().parents[2]))
    if analysis_path not in sys.path:
        sys.path.insert(0, analysis_path)

    import ROOT
    import common.utilities as utilities
    from common.add_vars_to_skim_tuples import DefineHistogramSelections
    from common.prepare_rdf import GetRdfForDataset

    ROOT.gROOT.SetBatch(True)
    if args.threads > 0:
        ROOT.EnableImplicitMT(args.threads)
    utilities.DeclareHeader(f"{analysis_path}/analysis/AnalysisTools.h")
    declare_uncut_vbf_pair(ROOT)

    cfg_dir = Path(analysis_path) / "config" / args.era
    configs = {
        "samples": utilities.get_config(cfg_dir / "samples.yaml"),
        "selections": utilities.get_config(cfg_dir / "selections.yaml"),
        "systematics": utilities.get_config(cfg_dir / "systematics.yaml"),
    }
    return ROOT, utilities, GetRdfForDataset, DefineHistogramSelections, configs


def group_samples(config):
    groups = config.get("groups", {})
    signal = []
    background = []
    for group_name, group in groups.items():
        role = group.get("role")
        if role not in {"signal", "background"}:
            raise ValueError(f"Group '{group_name}' needs role: signal or background")
        for entry in group.get("datasets", []):
            sample = {"name": entry} if isinstance(entry, str) else dict(entry)
            sample["group"] = group_name
            (signal if role == "signal" else background).append(sample)
    if not signal or not background:
        raise ValueError("The configuration needs at least one signal and one background dataset")
    return signal, background


def jet_categories(config):
    categories = config.get("jet_categories", {})
    if not categories:
        raise ValueError("The configuration needs a jet_categories section")
    for name, category in categories.items():
        if "min_njets" not in category:
            raise ValueError(f"Jet category '{name}' needs min_njets")
        if (
            category.get("max_njets") is not None
            and category["max_njets"] < category["min_njets"]
        ):
            raise ValueError(f"Invalid Njets range for category '{name}'")
    return categories


def category_mask(njets, category):
    mask = njets >= int(category["min_njets"])
    if category.get("max_njets") is not None:
        mask &= njets <= int(category["max_njets"])
    return mask


def add_sample_to_totals(sample, args, framework, thresholds, totals, diagnostics):
    arrays_by_strategy, weights, njets = load_sample_arrays(sample, args, framework)
    role = sample["role"]
    for strategy, arrays in arrays_by_strategy.items():
        valid_pair = arrays["mjj"] >= 0.0
        for category_name, category in args.jet_categories.items():
            mask = category_mask(njets, category) & valid_pair
            category_arrays = {name: values[mask] for name, values in arrays.items()}
            sumw, sumw2 = threshold_histogram(
                category_arrays,
                weights[mask],
                thresholds,
            )
            totals[strategy][category_name][role]["sumw"] += sumw
            totals[strategy][category_name][role]["sumw2"] += sumw2

    arrays = arrays_by_strategy["max_mjj"]
    valid_pair = arrays["mjj"] >= 0.0
    diagnostic, _, _ = np.histogram2d(
        arrays["mjj"][valid_pair],
        arrays["detajj"][valid_pair],
        bins=(diagnostics["mjj_edges"], diagnostics["detajj_edges"]),
        weights=weights[valid_pair],
    )
    diagnostics[role] += diagnostic
    diagnostic_pt, _, _ = np.histogram2d(
        arrays["jet1_pt"][valid_pair],
        arrays["jet2_pt"][valid_pair],
        bins=(diagnostics["jet1_pt_edges"], diagnostics["jet2_pt_edges"]),
        weights=weights[valid_pair],
    )
    diagnostics[f"{role}_jet_pt"] += diagnostic_pt
    print(
        f"[INFO] {sample['name']}: entries={len(weights)}, "
        f"weighted yield={np.sum(weights):.6g}"
    )


def ranked_rows(score, totals, thresholds):
    flat_order = np.argsort(score.ravel())[::-1]
    rows = []
    for flat_index in flat_order:
        index = np.unravel_index(flat_index, score.shape)
        if score[index] <= 0:
            break
        row = {
            variable: float(thresholds[variable][axis_index])
            for variable, axis_index in zip(VARIABLES, index)
        }
        row.update(
            signal=float(totals["signal"]["sumw"][index]),
            background=float(totals["background"]["sumw"][index]),
            signal_sumw2=float(totals["signal"]["sumw2"][index]),
            background_sumw2=float(totals["background"]["sumw2"][index]),
            significance=float(score[index]),
        )
        rows.append(row)
    return rows


def threshold_index(values, requested, name):
    matches = np.where(np.isclose(values, requested))[0]
    if len(matches) == 0:
        raise ValueError(
            f"Reference {name} cut {requested:g} is not in the configured thresholds"
        )
    return int(matches[0])


def display_edges(centers, lower=None, upper=None):
    centers = np.asarray(centers, dtype=float)
    if centers.size < 2:
        width = 1.0
        edges = np.array([centers[0] - width / 2.0, centers[0] + width / 2.0])
    else:
        midpoints = 0.5 * (centers[:-1] + centers[1:])
        edges = np.concatenate(
            (
                [centers[0] - 0.5 * (centers[1] - centers[0])],
                midpoints,
                [centers[-1] + 0.5 * (centers[-1] - centers[-2])],
            )
        )
    if lower is not None:
        edges[0] = float(lower)
    if upper is not None:
        edges[-1] = float(upper)
    return edges


def reference_heatmaps(args, config, thresholds, totals):
    reference = config["reference_plot"]
    selectors = []
    for variable in VARIABLES:
        if variable in {"mjj", "detajj"}:
            selectors.append(slice(None))
        else:
            selectors.append(
                threshold_index(
                    thresholds[variable],
                    float(reference[variable]),
                    variable,
                )
            )
    selection = tuple(selectors)
    heatmaps = {}
    for category_name, category_totals in totals.items():
        signal_2d = category_totals["signal"]["sumw"][selection]
        background_2d = category_totals["background"]["sumw"][selection]
        total_signal = float(signal_2d[0, 0]) if signal_2d.size else 0.0
        total_background = float(background_2d[0, 0]) if background_2d.size else 0.0
        score_2d = significance(signal_2d, background_2d, args.min_background)
        heatmaps[category_name] = {
            "signal": signal_2d,
            "background": background_2d,
            "signal_efficiency": np.divide(
                signal_2d,
                total_signal,
                out=np.zeros_like(signal_2d, dtype=float),
                where=total_signal > 0.0,
            ),
            "background_efficiency": np.divide(
                background_2d,
                total_background,
                out=np.zeros_like(background_2d, dtype=float),
                where=total_background > 0.0,
            ),
            "score": score_2d,
            "valid": (signal_2d > 0.0) & (
                background_2d > max(0.0, args.min_background)
            ),
        }
    return heatmaps


def best_2d_point(score, signal, background, thresholds, reference):
    if not np.any(score > 0):
        return None
    index = np.unravel_index(np.argmax(score), score.shape)
    return {
        "mjj": float(thresholds["mjj"][index[0]]),
        "detajj": float(thresholds["detajj"][index[1]]),
        **{
            variable: float(reference[variable])
            for variable in VARIABLES
            if variable not in {"mjj", "detajj"}
        },
        "signal": float(signal[index]),
        "background": float(background[index]),
        "significance": float(score[index]),
    }


def variable_subsets(config):
    configured = config.get("variable_subsets")
    if configured:
        subsets = [tuple(item) for item in configured]
    else:
        subsets = [
            ("mjj",),
            ("detajj",),
            ("jet1_pt",),
            ("jet2_pt",),
            ("mjj", "detajj"),
            ("jet1_pt", "jet2_pt"),
            ("mjj", "detajj", "jet1_pt", "jet2_pt"),
        ]
    for subset in subsets:
        unknown = set(subset) - set(VARIABLES)
        if unknown:
            raise ValueError(f"Unknown variables in subset {subset}: {sorted(unknown)}")
    return subsets


def optimize_variable_subset(category_totals, thresholds, subset, baseline_cuts, min_background):
    selectors = []
    active_axes = []
    for axis, variable in enumerate(VARIABLES):
        if variable in subset:
            selectors.append(slice(None))
            active_axes.append(axis)
        else:
            selectors.append(
                threshold_index(
                    thresholds[variable],
                    float(baseline_cuts[variable]),
                    variable,
                )
            )

    selection = tuple(selectors)
    signal = category_totals["signal"]["sumw"][selection]
    background = category_totals["background"]["sumw"][selection]
    score = significance(signal, background, min_background)
    if not np.any(score > 0):
        return None

    active_index = np.unravel_index(np.argmax(score), score.shape)
    full_index = []
    active_position = 0
    for selector in selectors:
        if isinstance(selector, slice):
            full_index.append(active_index[active_position])
            active_position += 1
        else:
            full_index.append(selector)
    full_index = tuple(full_index)
    return {
        "variables": "+".join(subset),
        **{
            variable: float(thresholds[variable][full_index[axis]])
            for axis, variable in enumerate(VARIABLES)
        },
        "signal": float(category_totals["signal"]["sumw"][full_index]),
        "background": float(category_totals["background"]["sumw"][full_index]),
        "significance": float(
            significance(
                np.asarray(category_totals["signal"]["sumw"][full_index]),
                np.asarray(category_totals["background"]["sumw"][full_index]),
                min_background,
            )
        ),
    }


def save_pairing_comparison(output, args, config, thresholds, strategy_totals):
    import matplotlib.pyplot as plt

    subsets = variable_subsets(config)
    baseline_cuts = config["comparison_baseline_cuts"]
    rows = []
    for strategy, category_totals_by_name in strategy_totals.items():
        for category_name, category_totals in category_totals_by_name.items():
            for subset in subsets:
                result = optimize_variable_subset(
                    category_totals,
                    thresholds,
                    subset,
                    baseline_cuts,
                    args.min_background,
                )
                if result is None:
                    continue
                result.update(strategy=strategy, jet_category=category_name)
                rows.append(result)

    fieldnames = [
        "strategy",
        "jet_category",
        "variables",
        *VARIABLES,
        "signal",
        "background",
        "significance",
    ]
    with (output / "pairing_and_variables_comparison.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    with (output / "pairing_and_variables_comparison.json").open("w") as handle:
        json.dump(rows, handle, indent=2)

    inclusive_category = next(iter(args.jet_categories))
    inclusive_rows = [row for row in rows if row["jet_category"] == inclusive_category]
    subset_names = ["+".join(subset) for subset in subsets]
    strategies = args.pairing_config["strategies"]
    matrix = np.full((len(strategies), len(subset_names)), np.nan)
    for row in inclusive_rows:
        matrix[
            strategies.index(row["strategy"]),
            subset_names.index(row["variables"]),
        ] = row["significance"]

    fig, ax = plt.subplots(figsize=(max(9, 1.25 * len(subset_names)), 5.5))
    mesh = ax.imshow(matrix, aspect="auto", cmap="viridis")
    fig.colorbar(mesh, ax=ax, label=r"best $S/\sqrt{B}$")
    ax.set_xticks(np.arange(len(subset_names)))
    ax.set_xticklabels(subset_names, rotation=35, ha="right")
    ax.set_yticks(np.arange(len(strategies)))
    ax.set_yticklabels(strategies)
    ax.set_xlabel("Optimized cut variables")
    ax.set_ylabel("Dijet-pair strategy")
    ax.set_title(
        "Pairing and cut-variable comparison "
        f"({args.jet_categories[inclusive_category].get('label', inclusive_category)})"
    )
    for row_idx in range(matrix.shape[0]):
        for col_idx in range(matrix.shape[1]):
            if np.isfinite(matrix[row_idx, col_idx]):
                ax.text(
                    col_idx,
                    row_idx,
                    f"{matrix[row_idx, col_idx]:.3g}",
                    ha="center",
                    va="center",
                    color="white",
                    fontsize=9,
                )
    fig.tight_layout()
    fig.savefig(output / "pairing_and_variables_comparison.png", dpi=200)
    fig.savefig(output / "pairing_and_variables_comparison.pdf")
    plt.close(fig)

    return rows


def plot_reference_figure(output, args, config, thresholds, heatmaps, best_by_category):
    import matplotlib.pyplot as plt

    category_items = list(args.jet_categories.items())
    fig, axes = plt.subplots(
        1,
        len(category_items),
        figsize=(6.3 * len(category_items), 6.2),
        constrained_layout=True,
    )
    axes = np.atleast_1d(axes)
    plot_range = config.get("reference_plot", {})
    detajj_max = float(plot_range.get("detajj_axis_max", thresholds["detajj"][-1]))
    mjj_max = float(plot_range.get("mjj_axis_max", thresholds["mjj"][-1]))
    detajj_edges = display_edges(thresholds["detajj"], lower=0.0, upper=detajj_max)
    mjj_edges = display_edges(thresholds["mjj"], lower=0.0, upper=mjj_max)
    annotation = plot_range.get("annotations", {})
    annotate = bool(annotation.get("enabled", True))
    annotation_fmt = annotation.get("format", ".3f")
    annotation_fontsize = float(annotation.get("fontsize", 2.5))
    annotation_mjj_stride = max(1, int(annotation.get("mjj_stride", 1)))
    annotation_detajj_stride = max(1, int(annotation.get("detajj_stride", 1)))
    cmap = plt.get_cmap("viridis").copy()
    cmap.set_bad("#d9d9d9")

    for ax, (category_name, category) in zip(axes, category_items):
        score = heatmaps[category_name]["score"]
        valid = heatmaps[category_name]["valid"]
        display_score = np.ma.array(score, mask=~valid)
        mesh = ax.pcolormesh(
            detajj_edges,
            mjj_edges,
            display_score,
            shading="flat",
            cmap=cmap,
        )
        fig.colorbar(mesh, ax=ax, label=r"$S/\sqrt{B}$")
        if annotate:
            norm = mesh.norm
            for i_mjj in range(0, score.shape[0], annotation_mjj_stride):
                for i_detajj in range(0, score.shape[1], annotation_detajj_stride):
                    if not valid[i_mjj, i_detajj]:
                        continue
                    value = score[i_mjj, i_detajj]
                    rgba = cmap(norm(value))
                    luminance = (
                        0.2126 * rgba[0] + 0.7152 * rgba[1] + 0.0722 * rgba[2]
                    )
                    ax.text(
                        thresholds["detajj"][i_detajj],
                        thresholds["mjj"][i_mjj],
                        format(value, annotation_fmt),
                        ha="center",
                        va="center",
                        fontsize=annotation_fontsize,
                        color="black" if luminance > 0.58 else "white",
                    )
        best = best_by_category[category_name]
        if best is not None:
            ax.scatter(
                best["detajj"],
                best["mjj"],
                marker="*",
                s=180,
                color="red",
                edgecolor="white",
                linewidth=0.8,
            )
            ax.text(
                0.03,
                0.03,
                (
                    rf"best: $m_{{jj}}>{best['mjj']:g}$ GeV"
                    "\n"
                    rf"$|\Delta\eta_{{jj}}|>{best['detajj']:g}$"
                    "\n"
                    rf"$S/\sqrt{{B}}={best['significance']:.4g}$"
                ),
                transform=ax.transAxes,
                va="bottom",
                ha="left",
                fontsize=10,
                bbox={"facecolor": "white", "alpha": 0.82, "edgecolor": "none"},
            )
        ax.set(
            xlabel=r"minimum $|\Delta\eta_{jj}|$",
            ylabel=r"minimum $m_{jj}$ [GeV]",
            title=category.get("label", category_name),
        )
        ax.set_xlim(0.0, detajj_max)
        ax.set_ylim(0.0, mjj_max)

    reference = config["reference_plot"]
    fig.suptitle(
        (
            "VBF cut-based optimization\n"
            rf"$p_T^{{j1}}>{float(reference['jet1_pt']):g}$ GeV, "
            rf"$p_T^{{j2}}>{float(reference['jet2_pt']):g}$ GeV, "
            rf"$p_T^{{jj}}>{float(reference['ptjj']):g}$ GeV"
        ),
        fontsize=18,
    )
    fig.text(
        0.5,
        0.005,
        (
            f"Grey cells: expected background "
            f"$B \\leq {args.min_background:g}$ (not evaluated)"
        ),
        ha="center",
        fontsize=10,
    )
    fig.savefig(output / "cut_based_optimization_njets.png", dpi=200)
    fig.savefig(output / "cut_based_optimization_njets.pdf")
    plt.close(fig)


def plot_efficiency_figure(output, args, config, thresholds, heatmaps):
    import matplotlib.pyplot as plt

    category_items = list(args.jet_categories.items())
    fig, axes = plt.subplots(
        2,
        len(category_items),
        figsize=(6.3 * len(category_items), 9.2),
        constrained_layout=True,
        squeeze=False,
    )
    plot_range = config.get("reference_plot", {})
    detajj_max = float(plot_range.get("detajj_axis_max", thresholds["detajj"][-1]))
    mjj_max = float(plot_range.get("mjj_axis_max", thresholds["mjj"][-1]))
    detajj_edges = display_edges(thresholds["detajj"], lower=0.0, upper=detajj_max)
    mjj_edges = display_edges(thresholds["mjj"], lower=0.0, upper=mjj_max)
    rows = (
        ("signal_efficiency", "Signal efficiency"),
        ("background_efficiency", "Background efficiency"),
    )

    for row_index, (key, label) in enumerate(rows):
        for ax, (category_name, category) in zip(axes[row_index], category_items):
            mesh = ax.pcolormesh(
                detajj_edges,
                mjj_edges,
                heatmaps[category_name][key],
                shading="flat",
                vmin=0.0,
                vmax=1.0,
                cmap="magma" if row_index == 0 else "cividis",
            )
            fig.colorbar(mesh, ax=ax, label=label)
            ax.set(
                xlabel=r"minimum $|\Delta\eta_{jj}|$",
                ylabel=r"minimum $m_{jj}$ [GeV]",
                title=f"{label}: {category.get('label', category_name)}",
            )
            ax.set_xlim(0.0, detajj_max)
            ax.set_ylim(0.0, mjj_max)

    reference = config["reference_plot"]
    fig.suptitle(
        (
            "Cumulative efficiencies for the reference VBF scan\n"
            rf"$p_T^{{j1}}>{float(reference['jet1_pt']):g}$ GeV, "
            rf"$p_T^{{j2}}>{float(reference['jet2_pt']):g}$ GeV, "
            rf"$p_T^{{jj}}>{float(reference['ptjj']):g}$ GeV"
        ),
        fontsize=16,
    )
    fig.savefig(output / "efficiency_mjj_detajj_njets.png", dpi=200)
    fig.savefig(output / "efficiency_mjj_detajj_njets.pdf")
    plt.close(fig)


def save_outputs(args, config, thresholds, totals, diagnostics, rows_by_category):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    top_rows_by_category = {}
    for category_name, rows in rows_by_category.items():
        top_rows = rows[: args.top_n]
        top_rows_by_category[category_name] = top_rows
        with (output / f"ranking_{category_name}.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=list(VARIABLES)
                + ["signal", "background", "significance", "signal_sumw2", "background_sumw2"],
            )
            writer.writeheader()
            writer.writerows(top_rows)

    heatmaps = reference_heatmaps(args, config, thresholds, totals)
    best_by_category = {
        category_name: best_2d_point(
            values["score"],
            values["signal"],
            values["background"],
            thresholds,
            config["reference_plot"],
        )
        for category_name, values in heatmaps.items()
    }

    payload = {
        "era": args.era,
        "metric": "S/sqrt(B)",
        "preselection": args.preselection,
        "weight": args.weight,
        "minimum_background": args.min_background,
        "jet_categories": args.jet_categories,
        "reference_jet_pt_cuts": config["reference_plot"],
        "best_reference_scan": best_by_category,
        "best_full_scan": {
            name: rows[0] if rows else None
            for name, rows in top_rows_by_category.items()
        },
        "groups": config["groups"],
    }
    with (output / "result.json").open("w") as handle:
        json.dump(payload, handle, indent=2)

    grid_payload = {
        f"threshold_{name}": values for name, values in thresholds.items()
    }
    for category_name, category_totals in totals.items():
        for role in ("signal", "background"):
            grid_payload[f"{category_name}_{role}"] = category_totals[role]["sumw"]
            grid_payload[f"{category_name}_{role}_sumw2"] = category_totals[role]["sumw2"]
    np.savez_compressed(output / "scan_grids.npz", **grid_payload)

    plot_reference_figure(
        output,
        args,
        config,
        thresholds,
        heatmaps,
        best_by_category,
    )
    plot_efficiency_figure(output, args, config, thresholds, heatmaps)

    for role, label in (("signal", "Signal: VBF + ggH"), ("background", "Background: DY + EWK")):
        fig, ax = plt.subplots(figsize=(8, 6))
        mesh = ax.pcolormesh(
            diagnostics["mjj_edges"],
            diagnostics["detajj_edges"],
            diagnostics[role].T,
            shading="auto",
        )
        fig.colorbar(mesh, ax=ax, label="Weighted events")
        ax.set(xlabel=r"$m_{jj}$ [GeV]", ylabel=r"$|\Delta\eta_{jj}|$", title=label)
        fig.tight_layout()
        fig.savefig(output / f"{role}_mjj_detajj.png", dpi=180)
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(8, 6))
        mesh = ax.pcolormesh(
            diagnostics["jet1_pt_edges"],
            diagnostics["jet2_pt_edges"],
            diagnostics[f"{role}_jet_pt"].T,
            shading="auto",
        )
        fig.colorbar(mesh, ax=ax, label="Weighted events")
        ax.set(
            xlabel=r"leading jet $p_T$ [GeV]",
            ylabel=r"subleading jet $p_T$ [GeV]",
            title=label,
        )
        fig.tight_layout()
        fig.savefig(output / f"{role}_jet1pt_jet2pt.png", dpi=180)
        plt.close(fig)

    inclusive_name = next(iter(args.jet_categories))
    inclusive_rows = top_rows_by_category[inclusive_name]
    inclusive_totals = totals[inclusive_name]
    if inclusive_rows:
        best = inclusive_rows[0]
        selectors = []
        for variable in VARIABLES:
            if variable in {"mjj", "detajj"}:
                selectors.append(slice(None))
            else:
                selectors.append(threshold_index(thresholds[variable], best[variable], variable))
        signal_2d = inclusive_totals["signal"]["sumw"][tuple(selectors)]
        background_2d = inclusive_totals["background"]["sumw"][tuple(selectors)]
        score_2d = significance(signal_2d, background_2d, args.min_background)

        fig, ax = plt.subplots(figsize=(8, 6))
        mesh = ax.pcolormesh(
            thresholds["mjj"],
            thresholds["detajj"],
            score_2d.T,
            shading="nearest",
        )
        fig.colorbar(mesh, ax=ax, label=r"$S/\sqrt{B}$")
        ax.scatter(best["mjj"], best["detajj"], marker="*", s=180, color="red")
        ax.set(
            xlabel=r"minimum $m_{jj}$ [GeV]",
            ylabel=r"minimum $|\Delta\eta_{jj}|$",
            title=(
                rf"$p_T^{{j1}}>{best['jet1_pt']:g}$ GeV, "
                rf"$p_T^{{j2}}>{best['jet2_pt']:g}$ GeV, "
                rf"$p_T^{{jj}}>{best['ptjj']:g}$ GeV"
            ),
        )
        fig.tight_layout()
        fig.savefig(output / "significance_mjj_detajj.png", dpi=180)
        plt.close(fig)

        i_mjj = int(np.where(thresholds["mjj"] == best["mjj"])[0][0])
        i_detajj = int(np.where(thresholds["detajj"] == best["detajj"])[0][0])
        i_ptjj = threshold_index(thresholds["ptjj"], best["ptjj"], "ptjj")
        signal_pt_2d = inclusive_totals["signal"]["sumw"][i_mjj, i_detajj, :, :, i_ptjj]
        background_pt_2d = inclusive_totals["background"]["sumw"][i_mjj, i_detajj, :, :, i_ptjj]
        score_pt_2d = significance(signal_pt_2d, background_pt_2d, args.min_background)

        fig, ax = plt.subplots(figsize=(8, 6))
        mesh = ax.pcolormesh(
            thresholds["jet1_pt"],
            thresholds["jet2_pt"],
            score_pt_2d.T,
            shading="nearest",
        )
        fig.colorbar(mesh, ax=ax, label=r"$S/\sqrt{B}$")
        ax.scatter(best["jet1_pt"], best["jet2_pt"], marker="*", s=180, color="red")
        ax.set(
            xlabel=r"minimum leading jet $p_T$ [GeV]",
            ylabel=r"minimum subleading jet $p_T$ [GeV]",
            title=(
                rf"$m_{{jj}}>{best['mjj']:g}$ GeV, "
                rf"$|\Delta\eta_{{jj}}|>{best['detajj']:g}$"
            ),
        )
        fig.tight_layout()
        fig.savefig(output / "significance_jet1pt_jet2pt.png", dpi=180)
        plt.close(fig)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--era", required=True)
    parser.add_argument("--input-base", required=True, help="Base directory containing dataset skim directories")
    parser.add_argument("--config", default=str(Path(__file__).with_name("config.yaml")))
    parser.add_argument("--output", default="vbf_cut_optimization")
    parser.add_argument(
        "--preselection",
        default="baseline && Signal_Fit && N_SelectedJets >= 2",
        help="RDataFrame expression applied before the VBF cut scan",
    )
    parser.add_argument("--weight", default="weight__Central")
    parser.add_argument("--min-background", type=float, default=0.0)
    parser.add_argument("--top-n", type=int, default=50)
    parser.add_argument("--threads", type=int, default=0, help="ROOT threads; 0 uses ROOT default")
    parser.add_argument(
        "--max-events-per-sample",
        type=int,
        default=None,
        help=(
            "Process at most approximately this many entries per dataset using "
            "uniform stride sampling; event weights are rescaled automatically"
        ),
    )
    parser.add_argument("--skip-file-validation", action="store_true")
    return parser


def main():
    args = build_parser().parse_args()
    with open(args.config) as handle:
        config = yaml.safe_load(handle)
    thresholds = validate_thresholds(config["thresholds"])
    args.jet_categories = jet_categories(config)
    args.pairing_config = config["pairing"]
    unknown_strategies = (
        set(args.pairing_config["strategies"]) - set(PAIRING_MODES)
    )
    if unknown_strategies:
        raise ValueError(f"Unknown pairing strategies: {sorted(unknown_strategies)}")
    signal_samples, background_samples = group_samples(config)
    for sample in signal_samples:
        sample["role"] = "signal"
    for sample in background_samples:
        sample["role"] = "background"

    shape = tuple(len(thresholds[name]) for name in VARIABLES)
    strategy_totals = {
        strategy: {
            category_name: {
                role: {"sumw": np.zeros(shape), "sumw2": np.zeros(shape)}
                for role in ("signal", "background")
            }
            for category_name in args.jet_categories
        }
        for strategy in args.pairing_config["strategies"]
    }
    diagnostics = {
        "mjj_edges": np.asarray(config["diagnostics"]["mjj_edges"], dtype=float),
        "detajj_edges": np.asarray(config["diagnostics"]["detajj_edges"], dtype=float),
        "jet1_pt_edges": np.asarray(config["diagnostics"]["jet1_pt_edges"], dtype=float),
        "jet2_pt_edges": np.asarray(config["diagnostics"]["jet2_pt_edges"], dtype=float),
        "signal": np.zeros(
            (
                len(config["diagnostics"]["mjj_edges"]) - 1,
                len(config["diagnostics"]["detajj_edges"]) - 1,
            )
        ),
        "background": np.zeros(
            (
                len(config["diagnostics"]["mjj_edges"]) - 1,
                len(config["diagnostics"]["detajj_edges"]) - 1,
            )
        ),
        "signal_jet_pt": np.zeros(
            (
                len(config["diagnostics"]["jet1_pt_edges"]) - 1,
                len(config["diagnostics"]["jet2_pt_edges"]) - 1,
            )
        ),
        "background_jet_pt": np.zeros(
            (
                len(config["diagnostics"]["jet1_pt_edges"]) - 1,
                len(config["diagnostics"]["jet2_pt_edges"]) - 1,
            )
        ),
    }

    framework = load_framework(args)
    for sample in signal_samples + background_samples:
        add_sample_to_totals(
            sample,
            args,
            framework,
            thresholds,
            strategy_totals,
            diagnostics,
        )

    totals = strategy_totals["max_mjj"]
    rows_by_category = {}
    for category_name, category_totals in totals.items():
        score = significance(
            category_totals["signal"]["sumw"],
            category_totals["background"]["sumw"],
            args.min_background,
        )
        rows_by_category[category_name] = ranked_rows(
            score,
            category_totals,
            thresholds,
        )
    save_outputs(args, config, thresholds, totals, diagnostics, rows_by_category)
    save_pairing_comparison(
        Path(args.output),
        args,
        config,
        thresholds,
        strategy_totals,
    )

    if not any(rows_by_category.values()):
        raise RuntimeError("No scan point has positive signal and background yields")
    heatmaps = reference_heatmaps(args, config, thresholds, totals)
    for category_name, category in args.jet_categories.items():
        values = heatmaps[category_name]
        best = best_2d_point(
            values["score"],
            values["signal"],
            values["background"],
            thresholds,
            config["reference_plot"],
        )
        if best is None:
            print(f"[RESULT] {category.get('label', category_name)}: no valid point")
            continue
        print(
            f"[RESULT] {category.get('label', category_name)}: "
            f"mjj >= {best['mjj']:g} GeV, "
            f"|detajj| >= {best['detajj']:g}; "
            f"S={best['signal']:.6g}, B={best['background']:.6g}, "
            f"S/sqrt(B)={best['significance']:.6g}"
        )
    print(f"[RESULT] outputs written to {Path(args.output).resolve()}")


if __name__ == "__main__":
    main()
