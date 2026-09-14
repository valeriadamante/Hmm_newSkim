#!/usr/bin/env python3
"""Sequentially fit the six DY reco/PU components in the 2J, 1J and 0J regions.

Fits use ROOT Minuit2/Migrad with non-negative scale factors. Each gen-matching
category gets its own scale: 0J has 1 parameter, 1J has 2 (Hard, PU), 2J has 3
(Hard, PU1, PU2) and VBF has 3. The joint 1J+2J fallback below still shares one
PU parameter across 1J and 2J, by construction of that model.

For the relation between 1JPU and 2JPU use:
  --pu-1j2j separate : 2J and 1J are fitted in disjoint reco-jet regions
  --pu-1j2j shared   : 2J and 1J are fitted jointly with one common PU parameter
  --pu-1j2j auto     : try separate first; if Minuit fails or a PU parameter hits
                       the lower boundary, refit 1J and 2J together

The default is auto.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("MPLCONFIGDIR", "/tmp/vdamante/matplotlib")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import ROOT
import yaml
from matplotlib.lines import Line2D

try:
    import mplhep as hep
except ImportError:
    hep = None

ROOT.gROOT.SetBatch(True)
if hep:
    plt.style.use(hep.style.CMS)

COMPONENTS = {
    "0J": "0J", "1JHard": "1J_Hard", "1JPU": "1J_PU",
    "2JHard": "2J_Hard", "2JPU1": "2J_PU1", "2JPU2": "2J_PU2",
    "VBFHard": "2J_Hard", "VBFPU1": "2J_PU1", "VBFPU2": "2J_PU2",
}
GGF_COMPONENTS = tuple(name for name in COMPONENTS if not name.startswith("VBF"))
VBF_COMPONENTS = ("VBFHard", "VBFPU1", "VBFPU2")

# Each ggF observable uses an exclusive reconstructed-jet category in data and
# non-DY backgrounds. DY templates are additionally split by gen matching.
GGF_OBSERVABLES = {
    "2J": "eta_signed_vs_pt_subleadingjet",
    "1J": "eta_signed_vs_pt_leadingjet",
    "0J": "m_mumu",
}
# The 2J stage is inclusive in reco jet multiplicity: with an exclusive
# ggF_2J the >=3 jet events fall outside every component and keep weight 1,
# which is ~18-20% of the >=2 jet DY yield. ggF_0J/1J/ge2J partition ggF.
GGF_RECO_CATEGORIES = {"2J": "ggF_ge2J", "1J": "ggF_1J", "0J": "ggF_0J"}
GGF_ACTIVE_COMPONENTS = {
    "2J": {"2JHard", "2JPU1", "2JPU2"},
    "1J": {"1JHard", "1JPU"},
    "0J": {"0J"},
}
VBF_OBSERVABLE = "eta_signed_vs_pt_vbfjet1"

# One free scale per gen-matching category: 1 parameter in 0J, 2 in 1J, 3 in
# 2J and 3 in VBF. PU1 (one of the two jets from pile-up) and PU2 (both) are
# fitted independently: they are different physical configurations and PU2
# carries 5-12% of the 2J yield and up to 20% of the VBF yield, enough to
# constrain its own scale.
SEPARATE_MODELS = {
    "2J": (
        ("2JHard", "2JPU1", "2JPU2"),
        {"2JHard": "2JHard", "2JPU1": "2JPU1", "2JPU2": "2JPU2"},
    ),
    "1J": (("1JHard", "1JPU"), {"1JHard": "1JHard", "1JPU": "1JPU"}),
    "0J": (("0J",), {"0J": "0J"}),
}
VBF_MODEL = (
    ("VBFHard", "VBFPU1", "VBFPU2"),
    {"VBFHard": "VBFHard", "VBFPU1": "VBFPU1", "VBFPU2": "VBFPU2"},
)

# Joint 1J+2J fit: one PU parameter shared by 1JPU, 2JPU1 and 2JPU2.  The 1J
# observables are disjoint in reconstructed-jet multiplicity, so one data
# event contributes to exactly one row of the joint design matrix.
JOINT_PARAMETERS = ("1JHard", "2JHard", "PU")
JOINT_MAPS = {
    "2J": {"2JHard": "2JHard", "2JPU1": "PU", "2JPU2": "PU"},
    "1J": {
        "1JHard": "1JHard", "1JPU": "PU",
        "2JHard": "2JHard", "2JPU1": "PU", "2JPU2": "PU",
    },
}

# Plot format: CMS label + region, stacked components, DY composition and ratio.
STAGE_LABELS = {
    "0J": "ggF-Z 0J",
    "1J": "ggF-Z 1J",
    "2J": "ggF-Z 2J",
    "VBF": "VBF-Z",
}
X_TITLES = {
    "m_mumu": r"$m_{\mu\mu}$ [GeV]",
    "eta_signed_vs_pt_leadingjet": r"flattened (signed $\eta$, $p_{T}$) bin, leading jet",
    "eta_signed_vs_pt_subleadingjet": r"flattened (signed $\eta$, $p_{T}$) bin, subleading jet",
    "eta_signed_vs_pt_vbfjet1": r"flattened (signed $\eta$, $p_{T}$) bin, VBF jet 1",
}
DEFAULT_COMPONENT_COLORS = {
    "0J": "aqua",
    "1J Hard": "skyblue",
    "1J PU": "deepskyblue",
    "2J Hard": "cornflowerblue",
    "2J PU1": "royalblue",
    "2J PU2": "navy",
    "VBF Hard": "lightsteelblue",
    "VBF PU1": "steelblue",
    "VBF PU2": "midnightblue",
}
BACKGROUND_COLOR = "0.72"
RATIO_LIMITS = (0.5, 1.5)
RATIO_GUIDES = (0.8, 1.2)
DEFAULT_SUBTRACT = (
    # Canonical, non-overlapping Run-3 process files in the Z sideband.
    "EWK", "SingleH", "ST", "TT", "TTX", "TW", "VV", "VVV", "W_NJets",
)

SUBTRACT_ALIASES = {
    # The hadded process was renamed in the 2024/2025 configurations.
    "W_NJets": ("W_NJets", "W"),
}


def open_hist(path: Path, root_path: str, clone_name: str):
    root_file = ROOT.TFile.Open(str(path), "READ")
    if not root_file or root_file.IsZombie():
        raise RuntimeError(f"Cannot open {path}")
    hist = root_file.Get(root_path)
    if not hist or not hist.InheritsFrom("TH1"):
        root_file.Close()
        raise KeyError(f"Missing histogram {root_path} in {path}")
    clone = hist.Clone(clone_name)
    clone.SetDirectory(0)
    root_file.Close()
    return clone


def hist_arrays(hist):
    values, variances = [], []
    for ix in range(1, hist.GetNbinsX() + 1):
        for iy in range(1, hist.GetNbinsY() + 1):
            values.append(hist.GetBinContent(ix, iy))
            variances.append(hist.GetBinError(ix, iy) ** 2)
    return np.asarray(values, float), np.asarray(variances, float)


def sum_hists(paths, root_path, reference):
    total = reference.Clone("non_dy")
    total.Reset("ICES")
    total.SetDirectory(0)
    used = []
    for path in paths:
        try:
            hist = open_hist(path, root_path, f"non_dy_{path.stem}")
        except KeyError:
            continue
        total.Add(hist)
        used.append(path.stem)
    return total, used


def subtraction_paths(input_dir, samples):
    """Resolve one file per background, including era-dependent aliases."""
    paths = []
    for sample in samples:
        candidates = SUBTRACT_ALIASES.get(sample, (sample,))
        selected = next(
            (
                input_dir / f"{candidate}.root"
                for candidate in candidates
                if (input_dir / f"{candidate}.root").is_file()
            ),
            None,
        )
        if selected is not None:
            paths.append(selected)
    return paths


# Previous Poisson implementation, retained for reference (disabled).
# def solve_nonnegative_poisson(data, background, templates, solver="slsqp"):
#     """Fit non-negative DY scales with a binned Poisson likelihood.
#
#     The expectation in every retained bin is
#         mu = fixed non-DY/fitted-DY background + templates @ theta.
#     MC templates are treated as fixed predictions; the likelihood is Poisson
#     in the observed data counts.
#     """
#     npar = templates.shape[1]
#     valid = (
#         np.isfinite(data)
#         & (data >= 0)
#         & np.isfinite(background)
#         & np.all(np.isfinite(templates), axis=1)
#         & ((background + np.sum(templates, axis=1)) > 0)
#     )
#     observed = data[valid]
#     fixed = background[valid]
#     matrix = templates[valid]
#     if matrix.shape[0] <= npar or np.linalg.matrix_rank(matrix) < npar:
#         raise RuntimeError(
#             "The DY component templates are linearly dependent in the valid "
#             f"fit bins; {npar} independent normalizations cannot be identified."
#         )
#
#     epsilon = 1.0e-12
#
#     def expectation(theta):
#         return fixed + matrix @ theta
#
#     def nll(theta):
#         mu = expectation(theta)
#         if np.any(mu <= 0):
#             return np.inf
#         return float(np.sum(mu - observed * np.log(mu)))
#
#     def gradient(theta):
#         mu = expectation(theta)
#         return matrix.T @ (1.0 - observed / mu)
#
#     objective_scale = max(float(np.sum(observed)), 1.0)
#     if solver == "scaled-slsqp":
#         result = minimize(
#             lambda theta: nll(theta) / objective_scale,
#             np.ones(npar),
#             jac=lambda theta: gradient(theta) / objective_scale,
#             method="SLSQP",
#             bounds=Bounds(np.zeros(npar), np.full(npar, np.inf)),
#             constraints=LinearConstraint(matrix, epsilon - fixed, np.inf),
#             options={"ftol": 1.0e-12, "maxiter": 5000},
#         )
#     else:
#         result = minimize(
#             nll,
#             np.ones(npar),
#             jac=gradient,
#             method="SLSQP",
#             bounds=Bounds(np.zeros(npar), np.full(npar, np.inf)),
#             constraints=LinearConstraint(matrix, epsilon - fixed, np.inf),
#             options={"ftol": 1.0e-10, "maxiter": 2000},
#         )
#     if not result.success or not np.all(np.isfinite(result.x)):
#         raise RuntimeError(f"Poisson likelihood fit failed: {result.message}")
#
#     theta = np.maximum(result.x, 0.0)
#     mu = expectation(theta)
#     hessian = matrix.T @ ((observed / mu**2)[:, np.newaxis] * matrix)
#     covariance = np.linalg.pinv(hessian)
#     positive = observed > 0
#     deviance_terms = np.array(mu, copy=True)
#     deviance_terms[positive] = (
#         mu[positive]
#         - observed[positive]
#         + observed[positive] * np.log(observed[positive] / mu[positive])
#     )
#     deviance = float(2.0 * np.sum(deviance_terms))
#     ndof = max(int(np.count_nonzero(valid) - npar), 0)
#     return theta, covariance, deviance, ndof, valid, float(result.fun)
#
def valid_fit_bins(data, background, templates, variance):
    """Bins entering the chi2: finite everywhere and with a positive variance."""
    return (np.isfinite(data) & np.isfinite(background)
            & np.isfinite(variance) & (variance > 0)
            & np.all(np.isfinite(templates), axis=1))


def chi2_value(data, background, templates, variance, theta):
    valid = valid_fit_bins(data, background, templates, variance)
    residual = data[valid] - background[valid] - templates[valid] @ theta
    return float(np.sum(residual**2 / variance[valid]))


def fit_minuit_chi2(data, background, templates, variance, parameter_names):
    """Minimise the fixed-variance chi2 with Minuit2/Migrad and theta >= 0.

    Variance includes data, subtracted backgrounds and nominal active DY MC.
    Previously fitted DY components contribute their scaled histogram errors;
    uncertainty/correlations of their fitted scales are not propagated here.
    """
    valid = valid_fit_bins(data, background, templates, variance)
    target = data[valid] - background[valid]
    matrix = templates[valid]
    spread = variance[valid]
    npar = len(parameter_names)

    if len(target) <= npar or np.linalg.matrix_rank(matrix) < npar:
        raise RuntimeError("Insufficient independent DY templates in valid chi2 bins")

    def chi2(par):
        theta = np.array([par[i] for i in range(npar)], dtype=float)
        residual = target - matrix @ theta
        return float(np.sum(residual**2 / spread))

    chi2_prefit = chi2(np.ones(npar))

    minimizer = ROOT.Math.Factory.CreateMinimizer("Minuit2", "Migrad")
    minimizer.SetMaxFunctionCalls(100000)
    minimizer.SetMaxIterations(10000)
    minimizer.SetTolerance(1e-6)
    minimizer.SetPrintLevel(0)

    functor = ROOT.Math.Functor(chi2, npar)
    minimizer.SetFunction(functor)
    for index, name in enumerate(parameter_names):
        minimizer.SetLowerLimitedVariable(index, name, 1.0, 0.01, 0.0)

    success = bool(minimizer.Minimize())
    theta = np.array([minimizer.X()[i] for i in range(npar)], float)
    errors = np.array([minimizer.Errors()[i] for i in range(npar)], float)
    covariance = np.array(
        [[minimizer.CovMatrix(i, j) for j in range(npar)] for i in range(npar)], float
    )

    return {
        "parameters": tuple(parameter_names),
        "theta": theta,
        "errors": errors,
        "covariance": covariance,
        "chi2_prefit": float(chi2_prefit),
        "chi2_postfit": float(minimizer.MinValue()),
        "ndof": int(np.count_nonzero(valid) - npar),
        "n_fit_bins": int(np.count_nonzero(valid)),
        "success": success,
        "status": int(minimizer.Status()),
        "edm": float(minimizer.Edm()),
        "valid": valid,
    }


def correlation(covariance):
    sigma = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    denominator = np.outer(sigma, sigma)
    return np.divide(
        covariance, denominator, out=np.zeros_like(covariance), where=denominator > 0
    )


def fit_failure_reasons(result, boundary, pu_parameters=()):
    """Reasons why a fit should be considered unusable in --pu-1j2j auto."""
    reasons = []
    if not result["success"]:
        reasons.append("Minuit returned success=False")
    if result["status"] != 0:
        reasons.append(f"Minuit status={result['status']}")
    if not np.isfinite(result["chi2_postfit"]):
        reasons.append("non-finite post-fit chi2")
    if not np.isfinite(result["edm"]):
        reasons.append("non-finite EDM")
    if not np.all(np.isfinite(result["errors"])):
        reasons.append("non-finite parameter uncertainty")
    index = {name: position for position, name in enumerate(result["parameters"])}
    for name in pu_parameters:
        value = result["theta"][index[name]]
        if value <= boundary:
            reasons.append(f"{name} at lower boundary ({value:.3g} <= {boundary:.3g})")
    return reasons


def stage_system(observable, parameters, component_map, fixed):
    """Background, design matrix and variance for one observable.

    `fixed` holds already-determined component scales that move into the
    background; every component mapped to a parameter becomes a free template.
    """
    background = observable["non_dy"].copy()
    variance = observable["data_variance"] + observable["non_dy_variance"]

    for component, scale in fixed.items():
        background = background + scale * observable["components"][component]
        variance = variance + scale**2 * observable["component_variances"][component]

    columns = []
    for parameter in parameters:
        column = np.zeros_like(background)
        for component, mapped in component_map.items():
            if mapped != parameter:
                continue
            column = column + observable["components"][component]
            variance = variance + observable["component_variances"][component]
        columns.append(column)

    return background, np.column_stack(columns), variance


def merged_background(observable, fixed, tag):
    """ROOT background histogram for the plots: non-DY plus the fixed DY scales."""
    hist = observable["merged_non_dy"].Clone(f"background_{tag}")
    hist.SetDirectory(0)
    for component, scale in fixed.items():
        hist.Add(observable["merged_components"][component], scale)
    return hist


def component_scales(result, component_map):
    """Map each component onto the value of the parameter it shares."""
    index = {name: position for position, name in enumerate(result["parameters"])}
    return {
        component: float(result["theta"][index[parameter]])
        for component, parameter in component_map.items()
    }



def correction_payload(era, theta, covariance):
    content = dict(zip(COMPONENTS, map(float, theta)))
    return {
        "schema_version": 2,
        "description": f"Data-driven DY hard-jet component fit for {era}",
        "corrections": [{
            "name": "dy_012j_reweight",
            "description": (
                "Separate DY normalizations for six ggF reco/PU components "
                "and three VBF hard/PU components."
            ),
            "version": 1,
            "inputs": [{
                "name": "component", "type": "string",
                "description": "Exclusive reco/PU jet component.",
            }],
            "output": {"name": "weight", "type": "real"},
            "data": {
                "nodetype": "category", "input": "component",
                "content": [{"key": name, "value": value} for name, value in content.items()],
                "default": 1.0,
            },
        }],
    }


def load_observable(args, input_dirs, root_path, tag, components, *,
                    component_root_path=None, active_components=None):
    """Data, non-DY background and every component template for one observable.

    Input directories are concatenated bin-by-bin, so eras sharing a payload are
    fitted together, and the merged ROOT histograms are kept for the plots.
    """
    data_parts, data_var_parts = [], []
    non_dy_parts, non_dy_var_parts = [], []
    value_parts = {name: [] for name in components}
    variance_parts = {name: [] for name in components}
    merged_data = merged_non_dy = None
    merged_components = {}
    used = set()

    for period_index, input_dir in enumerate(input_dirs):
        data = open_hist(
            input_dir / f"{args.data_sample}.root", root_path,
            f"data_{tag}_{period_index}",
        )
        non_dy, used_here = sum_hists(
            subtraction_paths(input_dir, args.subtract_samples), root_path, data,
        )
        used.update(f"{input_dir.name}:{name}" for name in used_here)

        values, variances = hist_arrays(data)
        data_parts.append(values)
        data_var_parts.append(variances)
        values, variances = hist_arrays(non_dy)
        non_dy_parts.append(values)
        non_dy_var_parts.append(variances)

        hists = {}
        for component in components:
            if active_components is not None and component not in active_components:
                hist = data.Clone(f"dy_{tag}_{component}_{period_index}")
                hist.Reset()
                hist.SetDirectory(0)
            else:
                hist = open_hist(
                    input_dir / f"{args.dy_process}_{COMPONENTS[component]}.root",
                    component_root_path or root_path,
                    f"dy_{tag}_{component}_{period_index}",
                )
            hists[component] = hist
            values, variances = hist_arrays(hist)
            value_parts[component].append(values)
            variance_parts[component].append(variances)

        if merged_data is None:
            merged_data = data.Clone(f"data_{tag}")
            merged_non_dy = non_dy.Clone(f"non_dy_{tag}")
            merged_data.SetDirectory(0)
            merged_non_dy.SetDirectory(0)
            merged_components = {
                name: hists[name].Clone(f"dy_{tag}_{name}") for name in components
            }
            for hist in merged_components.values():
                hist.SetDirectory(0)
        else:
            merged_data.Add(data)
            merged_non_dy.Add(non_dy)
            for name in components:
                merged_components[name].Add(hists[name])

    return {
        "tag": tag,
        "root_path": root_path,
        "data": np.concatenate(data_parts),
        "data_variance": np.concatenate(data_var_parts),
        "non_dy": np.concatenate(non_dy_parts),
        "non_dy_variance": np.concatenate(non_dy_var_parts),
        "components": {n: np.concatenate(p) for n, p in value_parts.items()},
        "component_variances": {n: np.concatenate(p) for n, p in variance_parts.items()},
        "merged_data": merged_data,
        "merged_non_dy": merged_non_dy,
        "merged_components": merged_components,
        "used": used,
    }


def repo_root():
    return Path(os.environ.get("ANALYSIS_PATH", REPO))


def configured_luminosity(era):
    """Integrated luminosity in fb^-1 from config/plot/<era>.yaml, or None."""
    path = repo_root() / "config" / "plot" / f"{era}.yaml"
    if not path.is_file():
        return None
    cfg = yaml.safe_load(path.read_text()) or {}
    match = re.match(r"\s*([0-9]*\.?[0-9]+)", str(cfg.get("lumi_text", {}).get("text", "")))
    return float(match.group(1)) if match else None


def era_luminosity(era):
    """Luminosity for one era, or the sum over a combined payload era."""
    direct = configured_luminosity(era)
    if direct is not None:
        return direct
    # Combined eras such as Run3_2022_2022EE have no plot configuration of
    # their own; the fit uses both periods together, so add their luminosities.
    parts = era.removeprefix("Run3_").split("_")
    values = [configured_luminosity(f"Run3_{part}") for part in parts]
    if len(parts) > 1 and all(value is not None for value in values):
        return float(sum(values))
    print(f"[WARNING] No plot luminosity for {era}: CMS label without luminosity")
    return None


def component_colors(era, dy_process):
    """Component colors from process_names.yaml, falling back to the defaults."""
    path = repo_root() / "config" / era / "process_names.yaml"
    styles = {}
    if path.is_file():
        cfg = yaml.safe_load(path.read_text()) or {}
        styles = (cfg.get(dy_process) or {}).get("jet_component_styles") or {}
    return {**DEFAULT_COMPONENT_COLORS, **styles}


def plot_axis_edges(hist, variable):
    """Real bin edges for a 1D observable, flattened bin index for a 2D one."""
    if hist.InheritsFrom("TH2"):
        n_bins = hist.GetNbinsX() * hist.GetNbinsY()
        return np.arange(n_bins + 1, dtype=float), X_TITLES.get(
            variable, "flattened fit bin"
        )
    axis = hist.GetXaxis()
    edges = np.array(
        [axis.GetBinLowEdge(i) for i in range(1, hist.GetNbinsX() + 2)], float
    )
    return edges, X_TITLES.get(variable, variable)


def draw_stack(ax, edges, values, colors, labels=None):
    """Stack filled steps bottom-up and return the running total."""
    bottom = np.zeros(len(edges) - 1)
    for index, (content, color) in enumerate(zip(values, colors)):
        top = bottom + content
        ax.stairs(
            top, edges, baseline=bottom, fill=True, color=color,
            linewidth=0, label=None if labels is None else labels[index],
        )
        bottom = top
    return bottom


def make_plots(output_dir, entry, *, era, lumi, colors):
    """Pre-fit and post-fit Data/MC plots in the analysis plotting format."""
    output_dir.mkdir(parents=True, exist_ok=True)

    stage = entry["stage"]
    components = list(entry["components"])
    component_labels = [COMPONENTS[c].replace("_", " ") for c in components]
    component_colors_ = [
        colors.get(label, DEFAULT_COMPONENT_COLORS.get(label, "royalblue"))
        for label in component_labels
    ]

    data_hist = entry["merged_data"]
    data_v, data_var = hist_arrays(data_hist)
    bkg_v, bkg_var = hist_arrays(entry["merged_background"])
    nominal = [hist_arrays(entry["merged_components"][c]) for c in components]
    nominal_v = [values for values, _ in nominal]
    nominal_var = [variances for _, variances in nominal]

    edges, x_title = plot_axis_edges(data_hist, entry["variable"])
    centers = 0.5 * (edges[:-1] + edges[1:])
    # Zoom onto the populated range: the stored axis is wider than the selection.
    occupancy = data_v + bkg_v + np.sum(nominal_v, axis=0)
    filled = np.flatnonzero(occupancy > 0)
    x_limits = (
        (edges[filled[0]], edges[filled[-1] + 1]) if filled.size
        else (edges[0], edges[-1])
    )
    ndof = entry["ndof"]
    era_label = era.removeprefix("Run3_").replace("_", "+")

    scales = np.array([entry["scales"][c] for c in components], float)
    for tag, theta in (("prefit", np.ones(len(components))), ("postfit", scales)):
        scaled = [values * scale for values, scale in zip(nominal_v, theta)]
        scaled_var = [var * scale**2 for var, scale in zip(nominal_var, theta)]
        chi2 = entry["chi2_prefit"] if tag == "prefit" else entry["chi2_postfit"]

        fig, (ax, cax, rax) = plt.subplots(
            3, 1, figsize=(11, 12), sharex=True,
            gridspec_kw={"height_ratios": [3, 1, 1], "hspace": 0.06},
        )

        # ---- main panel: stacked non-DY + DY components, data on top
        stack_labels = [f"non-DY: [{bkg_v.sum():.2f}]"] + [
            f"DY {label}: [{values.sum():.2f}]"
            for label, values in zip(component_labels, scaled)
        ]
        total = draw_stack(
            ax, edges, [bkg_v, *scaled], [BACKGROUND_COLOR, *component_colors_],
            stack_labels,
        )
        ax.errorbar(
            centers, data_v, yerr=np.sqrt(np.maximum(data_var, 0.0)),
            fmt=".", color="black", markersize=8,
            label=f"Data: [{data_v.sum():.2f}]",
        )

        ax.set_yscale("log")
        positive = np.concatenate([array[array > 0] for array in (total, data_v)]) \
            if np.any(total > 0) or np.any(data_v > 0) else np.array([1.0])
        ax.set_ylim(positive.min() / 10.0, positive.max() * 1.0e2)
        ax.set_xlim(*x_limits)
        ax.set_ylabel("Events")
        ax.legend(ncol=3, fontsize=11, loc="upper center", frameon=True, framealpha=0.8)

        if hep is not None:
            label_kwargs = {"year": era_label} if lumi is None else {
                "lumi": round(lumi, 2), "year": era_label
            }
            hep.cms.label(
                ax=ax, data=True, label=STAGE_LABELS.get(stage, stage),
                com=13.6, loc=0, fontsize=20, **label_kwargs,
            )

        # ---- composition panel: DY component fractions
        dy_total = np.sum(scaled, axis=0)
        fractions = [
            np.divide(values, dy_total, out=np.zeros_like(values), where=dy_total > 0)
            for values in scaled
        ]
        draw_stack(cax, edges, fractions, component_colors_)
        cax.set_ylim(0.0, 1.0)
        cax.set_ylabel("DY Comp.")

        # ---- ratio panel: Data/MC with the MC statistical band and chi2/ndf
        ratio = np.divide(
            data_v, total, out=np.full_like(data_v, np.nan), where=total > 0
        )
        ratio_err = np.divide(
            np.sqrt(np.maximum(data_var, 0.0)), total,
            out=np.full_like(data_v, np.nan), where=total > 0,
        )
        mc_var = bkg_var + np.sum(scaled_var, axis=0)
        mc_rel = np.divide(
            np.sqrt(np.maximum(mc_var, 0.0)), total,
            out=np.zeros_like(total), where=total > 0,
        )
        rax.fill_between(
            edges, np.append(1.0 - mc_rel, (1.0 - mc_rel)[-1]),
            np.append(1.0 + mc_rel, (1.0 + mc_rel)[-1]),
            step="post", color="0.6", alpha=0.5, linewidth=0,
            label="MC stat. unc.",
        )
        rax.errorbar(centers, ratio, yerr=ratio_err, fmt=".", color="black", markersize=8)
        rax.axhline(1.0, color="black", linestyle="--", linewidth=1.5)
        for guide in RATIO_GUIDES:
            rax.axhline(guide, color="red", linestyle="--", linewidth=1.2)
        rax.set_ylim(*RATIO_LIMITS)
        rax.set_ylabel("Data/MC")
        rax.set_xlabel(x_title)

        chi2_text = (
            rf"$\chi^2$/ndf = {chi2 / ndof:.2f}" if ndof > 0
            else rf"$\chi^2$ = {chi2:.2f} (ndf $\leq$ 0)"
        )
        handles, band_labels = rax.get_legend_handles_labels()
        rax.legend(
            [Line2D([], [], linestyle="none"), *handles],
            [chi2_text, *band_labels],
            loc="upper right", fontsize=12, frameon=True, framealpha=0.8,
        )

        for extension in ("png", "pdf"):
            fig.savefig(
                output_dir / f"dy_012j_{stage}_{tag}.{extension}", bbox_inches="tight"
            )
        plt.close(fig)
        print(
            f"[PLOT] {stage} {tag}: chi2={chi2:.3f}, ndf={ndof}, "
            f"{output_dir / f'dy_012j_{stage}_{tag}.png'}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--era", required=True)
    parser.add_argument(
        "--input-dir", required=True, type=Path, nargs="+",
        help="One or more era directories; multiple inputs are fitted jointly.",
    )
    parser.add_argument("--region", default="Z_sideband_ggF")
    parser.add_argument("--vbf-region", default="Z_sideband_VBF")
    parser.add_argument(
        "--variable",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--data-sample", default="Data_Muon")
    parser.add_argument("--dy-process", default="DY")
    parser.add_argument("--subtract-samples", nargs="+", default=list(DEFAULT_SUBTRACT))
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--output-json", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument(
        "--pu-1j2j", choices=("separate", "shared", "auto"), default="auto",
        help=("separate: fit disjoint 2J and 1J reco regions; "
              "shared: fit 1J and 2J together with one common PU scale factor; "
              "auto (default): try separate and fall back to shared if Minuit "
              "fails or a PU parameter hits the lower boundary"),
    )
    parser.add_argument(
        "--auto-pu-boundary", type=float, default=1.0e-6,
        help="In --pu-1j2j auto, PU values <= this count as hitting the lower limit.",
    )
    args = parser.parse_args()

    input_dirs = args.input_dir
    used = set()
    component_names = list(COMPONENTS)
    component_index = {name: index for index, name in enumerate(component_names)}
    theta = np.full(len(COMPONENTS), np.nan)
    covariance = np.zeros((len(COMPONENTS), len(COMPONENTS)))
    stage_summaries = []
    plot_inputs = []

    def record(result, component_map):
        """Copy parameter values and covariance onto every component sharing them."""
        index = {name: position for position, name in enumerate(result["parameters"])}
        for component, parameter in component_map.items():
            theta[component_index[component]] = result["theta"][index[parameter]]
        for first, first_parameter in component_map.items():
            for second, second_parameter in component_map.items():
                covariance[component_index[first], component_index[second]] = (
                    result["covariance"][index[first_parameter], index[second_parameter]]
                )

    def summary(stage, variable, region, result, component_map, fixed, extra=None):
        entry = {
            "stage": stage,
            "region": region,
            "variable": variable,
            "parameters": list(result["parameters"]),
            "component_parameter_map": dict(component_map),
            "fixed_components": sorted(fixed),
            "values": result["theta"].tolist(),
            "errors": result["errors"].tolist(),
            "covariance": result["covariance"].tolist(),
            "correlation": correlation(result["covariance"]).tolist(),
            "chi2_prefit": result["chi2_prefit"],
            "chi2_postfit": result["chi2_postfit"],
            "ndof": result["ndof"],
            "n_fit_bins": result["n_fit_bins"],
            "minuit_success": result["success"],
            "minuit_status": result["status"],
            "edm": result["edm"],
        }
        entry.update(extra or {})
        return entry

    def report(label, result):
        print(
            f"[FIT] {label}: chi2 {result['chi2_prefit']:.3f} -> "
            f"{result['chi2_postfit']:.3f}, ndof={result['ndof']}, "
            f"status={result['status']}, EDM={result['edm']:.3g}"
        )
        for name, value, error in zip(
            result["parameters"], result["theta"], result["errors"]
        ):
            print(f"      DY {name}: {value:.6g} +/- {error:.6g}")

    # Load the three ggF observables once; every stage reuses the same templates.
    ggf = {}
    for stage, variable in GGF_OBSERVABLES.items():
        reco_region = args.region.removesuffix("_ggF") + "_" + GGF_RECO_CATEGORIES[stage]
        observable = load_observable(
            args, input_dirs, f"{reco_region}/{variable}", stage, GGF_COMPONENTS,
            component_root_path=f"{args.region}/{variable}",
            active_components=GGF_ACTIVE_COMPONENTS[stage],
        )
        used.update(observable["used"])
        ggf[stage] = observable

    # ---- 2J and 1J: sequential separate fits, or one joint fit with shared PU
    auto_reasons = []
    result_2j = result_1j = None

    if args.pu_1j2j in ("separate", "auto"):
        parameters, map_2j = SEPARATE_MODELS["2J"]
        background, matrix, variance = stage_system(ggf["2J"], parameters, map_2j, {})
        result_2j = fit_minuit_chi2(
            ggf["2J"]["data"], background, matrix, variance, parameters
        )
        auto_reasons += [
            f"2J: {reason}" for reason in
            fit_failure_reasons(result_2j, args.auto_pu_boundary, ("2JPU1", "2JPU2"))
        ]

        parameters, map_1j = SEPARATE_MODELS["1J"]
        background, matrix, variance = stage_system(
            ggf["1J"], parameters, map_1j, {}
        )
        result_1j = fit_minuit_chi2(
            ggf["1J"]["data"], background, matrix, variance, parameters
        )
        auto_reasons += [
            f"1J: {reason}" for reason in
            fit_failure_reasons(result_1j, args.auto_pu_boundary, ("1JPU",))
        ]

    effective_pu_mode = args.pu_1j2j
    if args.pu_1j2j == "auto":
        effective_pu_mode = "shared" if auto_reasons else "separate"
        if auto_reasons:
            print("[AUTO] Separate 1J/2J fits rejected; refitting them together "
                  "with one shared PU parameter:")
            for reason in auto_reasons:
                print(f"       - {reason}")
        else:
            print("[AUTO] Separate 1J/2J fits accepted; keeping PU parameters separate")

    if effective_pu_mode == "shared":
        order = ("2J", "1J")
        systems = {
            stage: stage_system(ggf[stage], JOINT_PARAMETERS, JOINT_MAPS[stage], {})
            for stage in order
        }
        result = fit_minuit_chi2(
            np.concatenate([ggf[stage]["data"] for stage in order]),
            np.concatenate([systems[stage][0] for stage in order]),
            np.concatenate([systems[stage][1] for stage in order], axis=0),
            np.concatenate([systems[stage][2] for stage in order]),
            JOINT_PARAMETERS,
        )
        record(result, JOINT_MAPS["1J"])

        per_observable = {}
        ones = np.ones(len(JOINT_PARAMETERS))
        for stage in order:
            background, matrix, variance = systems[stage]
            data = ggf[stage]["data"]
            per_observable[stage] = {
                "prefit": chi2_value(data, background, matrix, variance, ones),
                "postfit": chi2_value(
                    data, background, matrix, variance, result["theta"]
                ),
                "n_fit_bins": int(np.count_nonzero(
                    valid_fit_bins(data, background, matrix, variance)
                )),
            }

        stage_summaries.append(summary(
            "1J+2J", "+".join(GGF_OBSERVABLES[stage] for stage in order),
            args.region, result, JOINT_MAPS["1J"], {},
            {
                "requested_pu_mode": args.pu_1j2j,
                "effective_pu_mode": "shared",
                "auto_fallback_reasons": auto_reasons,
                "chi2_by_observable": per_observable,
            },
        ))
        report("1J+2J (shared PU)", result)
        for stage in order:
            print(
                f"      {stage} contribution: "
                f"{per_observable[stage]['prefit']:.3f} -> "
                f"{per_observable[stage]['postfit']:.3f}"
            )

        for stage in order:
            n_parameters = len(set(JOINT_MAPS[stage].values()))
            plot_inputs.append({
                "stage": stage,
                "variable": GGF_OBSERVABLES[stage],
                "merged_data": ggf[stage]["merged_data"],
                "merged_background": merged_background(ggf[stage], {}, stage),
                "merged_components": ggf[stage]["merged_components"],
                "components": list(JOINT_MAPS[stage]),
                "scales": component_scales(result, JOINT_MAPS[stage]),
                "chi2_prefit": per_observable[stage]["prefit"],
                "chi2_postfit": per_observable[stage]["postfit"],
                "ndof": per_observable[stage]["n_fit_bins"] - n_parameters,
            })
    else:
        for stage, result, fixed in (
            ("2J", result_2j, {}), ("1J", result_1j, {}),
        ):
            component_map = SEPARATE_MODELS[stage][1]
            record(result, component_map)
            stage_summaries.append(summary(
                stage, GGF_OBSERVABLES[stage], args.region, result, component_map, fixed,
                {"requested_pu_mode": args.pu_1j2j, "effective_pu_mode": "separate"},
            ))
            report(stage, result)
            plot_inputs.append({
                "stage": stage,
                "variable": GGF_OBSERVABLES[stage],
                "merged_data": ggf[stage]["merged_data"],
                "merged_background": merged_background(ggf[stage], fixed, stage),
                "merged_components": ggf[stage]["merged_components"],
                "components": list(component_map),
                "scales": component_scales(result, component_map),
                "chi2_prefit": result["chi2_prefit"],
                "chi2_postfit": result["chi2_postfit"],
                "ndof": result["ndof"],
            })

    # ---- 0J has its own disjoint reconstructed-jet data region.
    fixed_ggf = {}
    parameters, map_0j = SEPARATE_MODELS["0J"]
    background, matrix, variance = stage_system(ggf["0J"], parameters, map_0j, fixed_ggf)
    result = fit_minuit_chi2(ggf["0J"]["data"], background, matrix, variance, parameters)
    record(result, map_0j)
    stage_summaries.append(summary(
        "0J", GGF_OBSERVABLES["0J"], args.region, result, map_0j, fixed_ggf,
    ))
    report("0J", result)
    plot_inputs.append({
        "stage": "0J",
        "variable": GGF_OBSERVABLES["0J"],
        "merged_data": ggf["0J"]["merged_data"],
        "merged_background": merged_background(ggf["0J"], fixed_ggf, "0J"),
        "merged_components": ggf["0J"]["merged_components"],
        "components": list(map_0j),
        "scales": component_scales(result, map_0j),
        "chi2_prefit": result["chi2_prefit"],
        "chi2_postfit": result["chi2_postfit"],
        "ndof": result["ndof"],
    })

    # ---- VBF: independent fit, VBFPU1 and VBFPU2 share one scale factor
    vbf = load_observable(
        args, input_dirs, f"{args.vbf_region}/{VBF_OBSERVABLE}", "VBF", VBF_COMPONENTS,
    )
    used.update(vbf["used"])
    parameters, map_vbf = VBF_MODEL
    background, matrix, variance = stage_system(vbf, parameters, map_vbf, {})
    result = fit_minuit_chi2(vbf["data"], background, matrix, variance, parameters)
    record(result, map_vbf)
    stage_summaries.append(summary(
        "VBF", VBF_OBSERVABLE, args.vbf_region, result, map_vbf, {},
    ))
    report("VBF", result)
    plot_inputs.append({
        "stage": "VBF",
        "variable": VBF_OBSERVABLE,
        "merged_data": vbf["merged_data"],
        "merged_background": merged_background(vbf, {}, "VBF"),
        "merged_components": vbf["merged_components"],
        "components": list(map_vbf),
        "scales": component_scales(result, map_vbf),
        "chi2_prefit": result["chi2_prefit"],
        "chi2_postfit": result["chi2_postfit"],
        "ndof": result["ndof"],
    })

    if not used:
        raise RuntimeError("No non-DY samples with the requested histograms were found")
    if not np.all(np.isfinite(theta)):
        missing = [
            name for name in component_names
            if not np.isfinite(theta[component_index[name]])
        ]
        raise RuntimeError(f"Components left unfitted: {', '.join(missing)}")

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_root.parent.mkdir(parents=True, exist_ok=True)
    payload = correction_payload(args.era, theta, covariance)
    fit_summary = {
        "era": args.era,
        "parameter_order": component_names,
        "values": theta.tolist(),
        "errors": np.sqrt(np.maximum(np.diag(covariance), 0.0)).tolist(),
        "covariance": covariance.tolist(),
        "correlation": correlation(covariance).tolist(),
        "region": args.region,
        "vbf_region": args.vbf_region,
        "input_dirs": [str(path) for path in input_dirs],
        "solver": "ROOT Minuit2/Migrad",
        "fit_statistic": "chi2",
        "pu_1j2j_requested": args.pu_1j2j,
        "pu_1j2j_effective": effective_pu_mode,
        "auto_pu_boundary": args.auto_pu_boundary,
        "auto_fallback_reasons": auto_reasons,
        "variance": "data + fixed background + nominal active DY histogram variances",
        "fit_order": (
            (["1J+2J"] if effective_pu_mode == "shared" else ["2J", "1J"]) + ["0J", "VBF"]
        ),
        "stages": stage_summaries,
        "subtracted_samples": sorted(used),
    }

    args.output_json.write_text(json.dumps(payload, indent=2) + "\n")
    fit_summary_path = args.output_json.with_name(
        f"{args.output_json.stem}_fit.json"
    )
    fit_summary_path.write_text(json.dumps(fit_summary, indent=2) + "\n")

    output = ROOT.TFile.Open(str(args.output_root), "RECREATE")
    for entry in plot_inputs:
        stage = entry["stage"]
        entry["merged_data"].Write(f"data_{stage}")
        entry["merged_background"].Write(f"background_{stage}")
        for component in entry["components"]:
            entry["merged_components"][component].Write(f"dy_{stage}_{component}")
    n_components = len(COMPONENTS)
    covariance_hist = ROOT.TH2D("covariance", "covariance", n_components, 0, n_components, n_components, 0, n_components)
    for ix in range(n_components):
        for iy in range(n_components):
            covariance_hist.SetBinContent(ix + 1, iy + 1, covariance[ix, iy])
    covariance_hist.Write()
    output.Close()

    lumi = era_luminosity(args.era)
    colors = component_colors(args.era, args.dy_process)
    for entry in plot_inputs:
        make_plots(args.output_dir, entry, era=args.era, lumi=lumi, colors=colors)

    errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))
    for component, value, error in zip(COMPONENTS, theta, errors):
        print(f"[FIT] DY {component}: {value:.6g} +/- {error:.6g}")
    for entry in stage_summaries:
        print(
            f"[FIT] {entry['stage']} chi2/ndof = "
            f"{entry['chi2_postfit']:.3f}/{entry['ndof']}"
        )
    print(f"[OUTPUT] {args.output_json}")
    print(f"[OUTPUT] {fit_summary_path}")
    print(f"[OUTPUT] {args.output_root}")


if __name__ == "__main__":
    main()
