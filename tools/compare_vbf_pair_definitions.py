#!/usr/bin/env python3
"""Confronta le definizioni della coppia VBF su Data/MC, DY da pile-up e sensibilita'.

Legge gli hadd della campagna config/campaigns/vbf_pair_definition.sh
(<base>/<definizione>/Central_hadded/Run3_<era>) e, per ogni era e per la somma
delle ere, calcola nella categoria VBF:

  Z_sideband, H_sideband   Data/MC in resa e chi2/ndf di forma (MC normalizzato
                           ai dati) sulle variabili dei jet VBF e sul DNN
  tutte le regioni         frazione del DY con almeno un jet VBF da pile-up
                           (componenti 2J_PU1 + 2J_PU2), cioe' il DY 0J/1J
  Signal_Fit               S, B, S/sqrt(B) e Z di Asimov binnata sul DNN; i dati
                           in Signal_Fit non si leggono (blinding)

Esempio:

    python3 tools/compare_vbf_pair_definitions.py --eras 2024,2025,2026
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import uproot

REPO = Path(__file__).resolve().parents[1]
DEFAULT_BASE = Path("/eos/user/v/vdamante/H_mumu/skim_v4/post_dy/vbf_pair_definition")
DEFAULT_OUTPUT = REPO / "results" / "skim_v4" / "vbf_pair_definition" / "data_mc"
DEFAULT_PLOTS = Path("/eos/user/v/vdamante/www/H_mumu/updates_September23/studies/"
                     "vbf_pair_definition/data_mc")
ALL_ERAS = ("2022", "2022EE", "2023", "2023BPix", "2024", "2025", "2026")

DEFINITIONS = ("maxmjj", "hardest", "leading")
LABEL = {
    "maxmjj": "max m(jj) pair (production)",
    "hardest": "hardest preselected pair",
    "leading": "two leading jets",
}
# Palette validata (dataviz validate_palette.js, light, all pairs): identita'
# fissa per definizione, piu' marker diversi perche' l'acqua ha poco contrasto.
COLOR = {"maxmjj": "#2a78d6", "hardest": "#1baf7a", "leading": "#eb6834"}
MARKER = {"maxmjj": "o", "hardest": "s", "leading": "^"}

SIGNAL = ("VBFHto2Mu_M125_powheg", "GluGluHto2Mu")
OTHER_BACKGROUNDS = ("EWK", "TT", "ST", "TW", "VV", "VVV", "W", "TTX")
DY_PROCESS = {"Z_sideband": "DY", "H_sideband": "DYto2Mu_MLL105To160",
              "Signal_Fit": "DYto2Mu_MLL105To160"}
DY_COMPONENTS = ("2J_Hard", "2J_PU1", "2J_PU2")
CONTROL_REGIONS = ("Z_sideband", "H_sideband")
SHAPE_VARIABLES = ("vbfjet1_eta", "vbfjet2_eta", "m_jj", "delta_eta_jj", "DNN_NNOutput")
YIELD_VARIABLE = "m_jj"   # tutti gli eventi VBF hanno m_jj >= 400: niente underflow


def arguments():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base", type=Path, default=DEFAULT_BASE)
    parser.add_argument("--definitions", default=",".join(DEFINITIONS))
    parser.add_argument("--eras", default=",".join(ALL_ERAS))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="json and markdown tables")
    parser.add_argument("--plot-output", type=Path, default=DEFAULT_PLOTS)
    return parser.parse_args()


class Reader:
    """Istogrammi (valori, varianze, bordi) con cache; None se mancano."""

    def __init__(self):
        self.files = {}
        self.missing = set()

    def get(self, folder, process, key):
        path = folder / f"{process}.root"
        if path not in self.files:
            self.files[path] = uproot.open(path) if path.is_file() else None
        handle = self.files[path]
        if handle is None or key not in handle:
            self.missing.add(f"{path.name}:{key}")
            return None
        hist = handle[key]
        values, edges = hist.to_numpy(flow=True)
        variances = hist.variances(flow=True)
        return np.asarray(values, float), np.asarray(variances, float), np.asarray(edges, float)


def total(reader, folder, processes, key):
    out = None
    for process in processes:
        h = reader.get(folder, process, key)
        if h is None:
            continue
        out = [h[0], h[1], h[2]] if out is None else [out[0] + h[0], out[1] + h[1], out[2]]
    return out


def add(a, b):
    if a is None:
        return b
    if b is None:
        return a
    return [a[0] + b[0], a[1] + b[1], a[2]]


def chi2_shape(data, mc):
    """chi2/ndf fra dati e MC normalizzato ai dati, sui bin popolati."""
    d, dv = data[0], data[1]
    m, mv = mc[0], mc[1]
    if m.sum() <= 0 or d.sum() <= 0:
        return None
    scale = d.sum() / m.sum()
    m, mv = m * scale, mv * scale ** 2
    err = dv + mv
    good = (err > 0) & ((d > 0) | (m > 0))
    if good.sum() < 2:
        return None
    return float(np.sum((d[good] - m[good]) ** 2 / err[good]) / (good.sum() - 1))


def asimov(s, b):
    good = (s > 0) & (b > 0)
    s, b = s[good], b[good]
    return float(np.sqrt(np.sum(2.0 * ((s + b) * np.log1p(s / b) - s))))


def collect(reader, folder):
    """Istogrammi grezzi di una (definizione, era): si sommano fra le ere."""
    out = {}
    for region, dy in DY_PROCESS.items():
        mc_processes = (dy, *OTHER_BACKGROUNDS, *SIGNAL)
        for variable in SHAPE_VARIABLES:
            key = f"{region}_VBF/{variable}"
            entry = out.setdefault((region, variable), {})
            entry["mc"] = total(reader, folder, mc_processes, key)
            entry["background"] = total(reader, folder, (dy, *OTHER_BACKGROUNDS), key)
            entry["signal"] = total(reader, folder, SIGNAL, key)
            entry["dy"] = total(reader, folder, (dy,), key)
            for component in DY_COMPONENTS:
                entry[component] = total(reader, folder, (f"{dy}_{component}",), key)
            # Signal_Fit resta blinded: i dati non si leggono nemmeno.
            entry["data"] = (total(reader, folder, ("Data_Muon",), key)
                             if region in CONTROL_REGIONS else None)
    return out


def merge(a, b):
    return {key: {name: add(a[key].get(name), b[key].get(name)) for name in a[key]} for key in a}


def metrics(hists):
    out = {}
    for region in DY_PROCESS:
        entry = hists[(region, YIELD_VARIABLE)]
        m = {}
        if entry["mc"] is not None:
            m["mc"] = float(entry["mc"][0].sum())
        components = [entry[c] for c in DY_COMPONENTS]
        if all(c is not None for c in components):
            sums = [float(c[0].sum()) for c in components]
            dy_sum = sum(sums)
            if dy_sum > 0:
                m["dy_pu_fraction"] = (sums[1] + sums[2]) / dy_sum
                m["dy_pu2_fraction"] = sums[2] / dy_sum
            m["dy"] = dy_sum
        if entry["data"] is not None and entry["mc"] is not None:
            m["data"] = float(entry["data"][0].sum())
            m["data_over_mc"] = m["data"] / m["mc"] if m["mc"] else None
            m["chi2_ndf"] = {}
            for variable in SHAPE_VARIABLES:
                e = hists[(region, variable)]
                if e["data"] is not None and e["mc"] is not None:
                    m["chi2_ndf"][variable] = chi2_shape(e["data"], e["mc"])
        if region == "Signal_Fit" and entry["signal"] is not None and entry["background"] is not None:
            s, b = float(entry["signal"][0].sum()), float(entry["background"][0].sum())
            m.update(signal=s, background=b, s_over_sqrt_b=s / np.sqrt(b) if b > 0 else None)
            dnn = hists[(region, "DNN_NNOutput")]
            if dnn["signal"] is not None and dnn["background"] is not None:
                m["dnn_binned_z"] = asimov(dnn["signal"][0], dnn["background"][0])
        out[region] = m
    return out


def ratio_plot(hists_by_def, region, variable, title, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure, (top, bottom) = plt.subplots(2, 1, figsize=(7.5, 6.5), sharex=True,
                                         gridspec_kw={"height_ratios": (2.2, 1), "hspace": 0.05})
    drawn = False
    for definition, hists in hists_by_def.items():
        e = hists[(region, variable)]
        if e["data"] is None or e["mc"] is None:
            continue
        values, dvar, edges = e["data"]
        mc, mcvar = e["mc"][0], e["mc"][1]
        # flow=True: il primo e l'ultimo bordo sono +-inf, si tolgono i bin di flow.
        values, dvar, mc, mcvar = values[1:-1], dvar[1:-1], mc[1:-1], mcvar[1:-1]
        edges = edges[1:-1]
        centres = 0.5 * (edges[:-1] + edges[1:])
        keep = (values > 0) | (mc > 0)
        if not keep.any():
            continue
        colour, marker = COLOR[definition], MARKER[definition]
        top.stairs(mc, edges, color=colour, linewidth=2, label=f"MC, {LABEL[definition]}")
        top.errorbar(centres[keep], values[keep], yerr=np.sqrt(dvar[keep]), fmt=marker,
                     color=colour, markersize=5, linewidth=1, label=f"Data, {LABEL[definition]}")
        ratio = np.divide(values, mc, out=np.full_like(values, np.nan), where=mc > 0)
        error = np.divide(np.sqrt(dvar), mc, out=np.zeros_like(values), where=mc > 0)
        bottom.errorbar(centres[keep], ratio[keep], yerr=error[keep], fmt=marker + "-",
                        color=colour, markersize=5, linewidth=1.5, label=LABEL[definition])
        drawn = True
    if not drawn:
        plt.close(figure)
        return False
    top.set_yscale("log")
    top.set_ylabel("Events")
    top.legend(fontsize=7, ncol=2)
    top.set_title(title, fontsize=10)
    bottom.axhline(1.0, color="#555555", linewidth=1)
    bottom.set_ylim(0.5, 1.5)
    bottom.set_ylabel("Data / MC")
    bottom.set_xlabel(variable)
    for axis in (top, bottom):
        axis.grid(True, alpha=0.25, linewidth=0.6)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        figure.savefig(path.with_suffix(f".{extension}"), dpi=150)
    plt.close(figure)
    return True


def summary_plot(results, definitions, labels, path):
    """Piccoli multipli, una cifra di merito per pannello, un punto per era."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    panels = (
        ("Z_sideband", "data_over_mc", "Data/MC yield, Z sideband VBF"),
        ("H_sideband", "data_over_mc", "Data/MC yield, H sideband VBF"),
        ("Signal_Fit", "dy_pu_fraction", "DY fraction with >= 1 PU VBF jet, Signal Fit VBF"),
        ("Signal_Fit", "dnn_binned_z", "Binned Asimov Z on the DNN, Signal Fit VBF"),
    )
    figure, axes = plt.subplots(2, 2, figsize=(12, 8))
    x = np.arange(len(labels))
    for axis, (region, key, title) in zip(axes.flat, panels):
        for offset, definition in zip((-0.2, 0.0, 0.2), definitions):
            y = [results[label][definition].get(region, {}).get(key, np.nan) for label in labels]
            y = [np.nan if v is None else v for v in y]
            axis.plot(x + offset, y, MARKER[definition], color=COLOR[definition],
                      markersize=8, label=LABEL[definition])
        if key == "data_over_mc":
            axis.axhline(1.0, color="#555555", linewidth=1)
        axis.set_xticks(x)
        axis.set_xticklabels(labels, rotation=30, fontsize=8)
        axis.set_title(title, fontsize=10)
        axis.grid(True, alpha=0.25, linewidth=0.6)
    axes.flat[0].legend(fontsize=8)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    for extension in ("png", "pdf"):
        figure.savefig(path.with_suffix(f".{extension}"), dpi=150)
    plt.close(figure)


def markdown(results, definitions, labels):
    lines = []
    head = "| era | definition | Data/MC Z_sb | Data/MC H_sb | chi2/ndf vbfjet1_eta (Z_sb / H_sb) | chi2/ndf vbfjet2_eta (Z_sb / H_sb) | DY PU frac. Z_sb | DY PU frac. SF | S | B | S/sqrt(B) | Z (DNN) |"
    lines += [head, "|" + "|".join(["---"] * (head.count("|") - 1)) + "|"]

    def fmt(v, spec=".3f"):
        return "-" if v is None or (isinstance(v, float) and np.isnan(v)) else format(v, spec)

    for label in labels:
        for definition in definitions:
            r = results[label][definition]
            z, h, sf = r.get("Z_sideband", {}), r.get("H_sideband", {}), r.get("Signal_Fit", {})
            chi = lambda region, var: fmt(region.get("chi2_ndf", {}).get(var), ".2f")
            lines.append(
                f"| {label} | {definition} | {fmt(z.get('data_over_mc'))} | {fmt(h.get('data_over_mc'))} | "
                f"{chi(z, 'vbfjet1_eta')} / {chi(h, 'vbfjet1_eta')} | {chi(z, 'vbfjet2_eta')} / {chi(h, 'vbfjet2_eta')} | "
                f"{fmt(z.get('dy_pu_fraction'))} | {fmt(sf.get('dy_pu_fraction'))} | {fmt(sf.get('signal'), '.2f')} | "
                f"{fmt(sf.get('background'), '.0f')} | {fmt(sf.get('s_over_sqrt_b'))} | {fmt(sf.get('dnn_binned_z'))} |")
    return "\n".join(lines) + "\n"


def main():
    args = arguments()
    definitions = [d.strip() for d in args.definitions.split(",") if d.strip()]
    eras = [e.strip().removeprefix("Run3_") for e in args.eras.split(",") if e.strip()]
    reader = Reader()
    hists, available = {}, []
    for era in eras:
        folders = {d: args.base / d / "Central_hadded" / f"Run3_{era}" for d in definitions}
        absent = [str(f) for f in folders.values() if not f.is_dir()]
        if absent:
            print(f"WARNING: Run3_{era} skipped, missing hadd output: {', '.join(absent)}")
            continue
        hists[era] = {d: collect(reader, folders[d]) for d in definitions}
        available.append(era)
    if not available:
        raise SystemExit("No era with all definitions hadded")
    labels = list(available)
    if len(available) > 1:
        combined = "Run 3 combined" if len(available) == len(ALL_ERAS) else "+".join(available)
        hists[combined] = {}
        for d in definitions:
            total_hists = hists[available[0]][d]
            for era in available[1:]:
                total_hists = merge(total_hists, hists[era][d])
            hists[combined][d] = total_hists
        labels.append(combined)

    results = {label: {d: metrics(hists[label][d]) for d in definitions} for label in labels}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "summary.json").write_text(json.dumps(results, indent=2) + "\n")
    table = markdown(results, definitions, labels)
    (args.output / "summary.md").write_text(table)
    print(table)

    for label in labels:
        tag = label.replace(" ", "_").replace("+", "_")
        for region in CONTROL_REGIONS:
            for variable in SHAPE_VARIABLES:
                ratio_plot(hists[label], region, variable,
                           f"{label} - {region} VBF - DY without custom reweights",
                           args.plot_output / tag / f"{region}_VBF_{variable}")
    summary_plot(results, definitions, labels, args.plot_output / "summary")
    missing = sorted(reader.missing)
    if missing:
        print(f"WARNING: {len(missing)} histograms not found, e.g. {missing[:5]}")
    print(f"JSON and tables in {args.output}")
    print(f"Images in {args.plot_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
