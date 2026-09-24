#!/usr/bin/env python3
"""Come conviene scegliere la coppia di jet VBF quando piu' di due jet passano?

Confronta due definizioni, a parita' di tutto il resto:

  leading   i due jet di pT piu' alto fra quelli preselezionati
  maxmjj    la coppia con la massa invariante piu' alta (quella del framework,
            analysis/AnalysisTools.h:FindVBFJets)

Le due definizioni sono implementate qui **senza** soglie su m_jj e |Delta eta|,
altrimenti la scansione partirebbe gia' tagliata a 400/2.5 e non si vedrebbe
niente.  Le soglie vengono applicate dopo, in numpy, cosi' si ottengono le
efficienze in funzione del taglio.

Il punto di lavoro dell'analisi resta pT 35/25 sui due jet, m_jj >= 400 GeV,
|Delta eta_jj| >= 2.5 (config/<era>/selections.yaml, categoria VBF_def).

La coppia viene ridefinita **a monte** di prepare_rdf, sovrascrivendo HasVBF e
VBFJetIdx_1/2 nel nodo grezzo: tutto il resto (m_jj, delta_eta_jj, vbfjet1_*,
Zeppenfeld_Var, la soft activity ripulita contro i jet VBF, e quindi anche il
punteggio del DNN che le usa come input) viene ricalcolato dal framework.
Nessuna di quelle variabili e' riscritta a mano qui.

Segnale e fondo per regione:

  Signal_Fit   S = VBFHto2Mu_M125_powheg        B = DY 105-160 (le due meta'
                                                   GenVBFFilter 0 e 1)
  Z_sideband   S = EWK_2L2J_madgraph_herwig     B = DYto2Mu_M_50_amcatnloFXFX

Esempio:

    source env.sh
    python3 studies/vbf_pair_definition/compare_vbf_pair_definitions.py \\
        --era Run3_2024 --max-files-background 60

Un'era per invocazione: read_dataset tira tutto in numpy e due ere insieme
riempiono la memoria.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import yaml

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
os.environ.setdefault("ANALYSIS_PATH", str(REPO))

DEFAULT_INPUT = Path("/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4")
DEFAULT_OUTPUT = REPO / "results" / "skim_v4" / "vbf_pair_definition"
# Dal 23/09/2026 le immagini stanno sul web, non nel repo; json e root restano
# accanto al codice.  Vedi la memoria plot-sul-web-updates-sep23.
DEFAULT_PLOT_OUTPUT = Path(
    "/eos/user/v/vdamante/www/H_mumu/updates_September23/studies/vbf_pair_definition")

STRATEGIES = ("leading", "maxmjj")
STRATEGY_LABEL = {
    "leading": "leading + subleading in pT",
    "maxmjj": "max m(jj) pair",
}
# Tinte categoriche in ordine fisso, una per strategia: l'identita' non cambia
# colore da un pannello all'altro.
STRATEGY_COLOR = {"leading": "#eb6834", "maxmjj": "#2a78d6"}

REGIONS = {
    "Signal_Fit": {
        "signal": ["VBFHto2Mu_M125_powheg"],
        "background": [
            "DYto2Mu_MLL_105to160_amcatnloFXFX",
            "DYto2Mu_MLL_105to160_amcatnloFXFX_Fil_VBF",
        ],
        "signal_label": "VBF H->mumu",
        "background_label": "DY 105-160",
    },
    "Z_sideband": {
        "signal": ["EWK_2L2J_madgraph_herwig"],
        "background": ["DYto2Mu_M_50_amcatnloFXFX"],
        "signal_label": "EWK Z",
        "background_label": "DY incl.",
    },
}

# Punto di lavoro dell'analisi.
WP_LEADING_PT = 35.0
WP_SUBLEADING_PT = 25.0
WP_MJJ = 400.0
WP_DETA = 2.5

PAIR_FINDERS = r"""
namespace vbfpair {

using P4 = ROOT::Math::LorentzVector<ROOT::Math::PtEtaPhiM4D<double>>;

// I due jet preselezionati di pT piu' alto.  Non si assume che la collezione
// sia gia' ordinata in pT: SelectedJet_sortIdx esiste proprio perche' l'ordine
// non e' garantito ovunque.
ROOT::VecOps::RVec<int> Leading(const ROOT::VecOps::RVec<float>& pt,
                                const ROOT::VecOps::RVec<int>& presel) {
    ROOT::VecOps::RVec<int> out{-1, -1};
    int i1 = -1, i2 = -1;
    float p1 = -1.f, p2 = -1.f;
    for (size_t i = 0; i < pt.size(); ++i) {
        if (!presel[i]) continue;
        if (pt[i] > p1) { p2 = p1; i2 = i1; p1 = pt[i]; i1 = static_cast<int>(i); }
        else if (pt[i] > p2) { p2 = pt[i]; i2 = static_cast<int>(i); }
    }
    if (i1 >= 0 && i2 >= 0) { out[0] = i1; out[1] = i2; }
    return out;
}

// La coppia con m(jj) massima, senza soglie: la selezione la fa il chiamante.
ROOT::VecOps::RVec<int> MaxMjj(const ROOT::VecOps::RVec<float>& pt,
                               const ROOT::VecOps::RVec<float>& eta,
                               const ROOT::VecOps::RVec<float>& phi,
                               const ROOT::VecOps::RVec<float>& mass,
                               const ROOT::VecOps::RVec<int>& presel) {
    ROOT::VecOps::RVec<int> out{-1, -1};
    double best = -1.;
    for (size_t i = 0; i < pt.size(); ++i) {
        if (!presel[i]) continue;
        for (size_t j = i + 1; j < pt.size(); ++j) {
            if (!presel[j]) continue;
            const P4 pi(pt[i], eta[i], phi[i], mass[i]);
            const P4 pj(pt[j], eta[j], phi[j], mass[j]);
            const double m = (pi + pj).M();
            if (m > best) {
                best = m;
                out[0] = static_cast<int>(i);
                out[1] = static_cast<int>(j);
            }
        }
    }
    // Leg 1 e' il jet di pT piu' alto, come in FindVBFJets: vbfjet1_* e
    // vbfjet2_* entrano nel DNN in quell'ordine.
    if (out[0] >= 0 && pt[out[0]] < pt[out[1]]) std::swap(out[0], out[1]);
    return out;
}

}
"""

PAIR_EXPRESSION = {
    "leading": "vbfpair::Leading(SelectedJet_pt, {presel})",
    "maxmjj": ("vbfpair::MaxMjj(SelectedJet_pt, SelectedJet_eta, SelectedJet_phi, "
               "SelectedJet_mass, {presel})"),
}

COLUMNS = ["weight__Central", "HasVBF", "m_jj", "delta_eta_jj",
           "vbfjet1_pt", "vbfjet2_pt", "N_SelectedJets"]


# Il DNN e' un modello unico per tutte le ere, ma prende l'era_code fra gli
# input e il 2026 non ne ha uno: si usa quello del 2025.
DNN_ERA_TAG_FALLBACK = "Run3_2025"


def keep_plots_apart(args):
    """--plot-output '' arriva come Path('.'): vuol dire immagini accanto ai json."""
    return str(args.plot_output) not in ("", ".")


def era_label(era):
    """Etichetta leggibile per i titoli dei plot."""
    label = era.replace("Run3_", "")
    return "Run 3 combined" if label == "combined" else label


def arguments():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--era", default="Run3_2024")
    parser.add_argument("--input-dir", type=Path, default=DEFAULT_INPUT,
                        help="skim base directory (default: %(default)s)")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT,
                        help="base directory for json and root; one subdirectory per era")
    parser.add_argument("--plot-output", type=Path, default=DEFAULT_PLOT_OUTPUT,
                        help="base directory for images (default: web area); "
                             "use --plot-output '' to keep them next to the json")
    parser.add_argument("--regions", default=",".join(REGIONS),
                        help="subset of " + ",".join(REGIONS))
    parser.add_argument("--strategies", default=",".join(STRATEGIES))
    parser.add_argument("--max-files-signal", type=int, default=0,
                        help="0 = all files")
    parser.add_argument("--max-files-background", type=int, default=60,
                        help="DY samples are large; 0 = all files")
    parser.add_argument("--threads", type=int, default=4,
                        help="RDataFrame threads; more than 4 on lxplus risks OOM")
    parser.add_argument("--no-dnn", action="store_true",
                        help="skip ONNX inference and the DNN-dependent plots")
    parser.add_argument("--no-horn-preselection", action="store_true",
                        help="ignore SelectedJet_IsOutsideHorn when choosing the pair")
    parser.add_argument("--combine", default="",
                        help="comma-separated eras: sum their existing json outputs instead of "
                             "reading skims (e.g. Run3_2022,...,Run3_2026)")
    parser.add_argument("--combined-name", default="Run3_combined",
                        help="output subdirectory and plot label for --combine")
    parser.add_argument("--dnn-bins", type=int, default=20,
                        help="uniform DNN bins for the binned Z versus the cuts")
    parser.add_argument("--dnn-points", type=int, default=50,
                        help="points of the DNN score scan")
    return parser.parse_args()


def load_yaml(path):
    with open(path) as stream:
        return yaml.safe_load(stream)


def pick_files(all_files, max_files):
    """Sottoinsieme a passo costante, piu' il fattore di riscalatura dei pesi.

    Il denominatore di normalizzazione viene dai report di **tutto** il dataset,
    quindi leggere meno file sottostima le rese di esattamente n_tutti/n_usati.
    Il passo copre l'intero dataset e non i primi file, cosi' nessun intervallo
    di run e' privilegiato.
    """
    if not max_files or len(all_files) <= max_files:
        return list(all_files), 1.0
    stride = len(all_files) / max_files
    picked = sorted({int(index * stride) for index in range(max_files)})
    return [all_files[index] for index in picked], len(all_files) / len(picked)


_WARNED_ERA_TAG = set()


def read_dataset(dataset, *, strategy, era, args, selections_cfg, systematics_cfg,
                 samples_cfg, region, presel_expression):
    """Array per evento di un dataset, con la coppia VBF ridefinita."""
    import ROOT
    from common.dnn_application import clear_prediction_registry
    from common.prepare_rdf import prepare_rdf
    from common.utilities import (get_segmentation_dict, list_root_files,
                                  report_path_for_root)

    dataset_dir = args.input_dir / era / dataset
    if dataset not in samples_cfg and not dataset_dir.is_dir():
        # Nel 2022-2023 il DY 105-160 e' un campione unico, senza la meta' Fil_VBF.
        print(f"    WARNING: {dataset} is not defined for {era}, skipped", flush=True)
        return None
    if not dataset_dir.is_dir():
        raise FileNotFoundError(f"Skim directory not found: {dataset_dir}")
    all_files = sorted(list_root_files(str(dataset_dir)))
    if not all_files:
        raise FileNotFoundError(f"No ROOT files under {dataset_dir}")

    reports = [path for path in (report_path_for_root(f) for f in all_files)
               if os.path.isfile(path)]
    if not reports:
        raise FileNotFoundError(f"No report_*.json next to the ROOT files in {dataset_dir}")
    seg_dict = get_segmentation_dict(reports)
    if not seg_dict:
        raise RuntimeError(f"Empty normalization for {dataset}")

    max_files = (args.max_files_signal if dataset in REGIONS[region]["signal"]
                 else args.max_files_background)
    files, weight_scale = pick_files(all_files, max_files)

    sample_info = samples_cfg.get(dataset)
    if sample_info is None:
        raise KeyError(f"{dataset} is missing from config/{era}/samples.yaml")
    # Le due meta' del DY 105-160 si separano con GenVBFFilter==0/1: senza
    # questo taglio si contano due volte gli stessi eventi generati.
    additional_cuts = sample_info.get("additional_cuts")

    vector = ROOT.std.vector("string")()
    for path in files:
        vector.push_back(path)
    rdf = ROOT.RDataFrame("Events", vector)
    if rdf.Count().GetValue() == 0:
        print(f"    {dataset}: 0 events, skipped", flush=True)
        return None

    if not args.no_dnn:
        from common.dnn_application import DNNApplication
        if era not in DNNApplication.ERA_CODES:
            if dataset not in _WARNED_ERA_TAG:
                print(f"    WARNING: no DNN era_code for {era}; using the "
                      f"{DNN_ERA_TAG_FALLBACK} tag ({DNNApplication.ERA_CODES[DNN_ERA_TAG_FALLBACK]})",
                      flush=True)
                _WARNED_ERA_TAG.add(dataset)
            rdf = rdf.Define("era_code", str(DNNApplication.ERA_CODES[DNN_ERA_TAG_FALLBACK]))

    expression = PAIR_EXPRESSION[strategy].format(presel=presel_expression)
    rdf = rdf.Define("VBFPairIdx__study", expression)
    rdf = rdf.Redefine("VBFJetIdx_1", "VBFPairIdx__study[0]")
    rdf = rdf.Redefine("VBFJetIdx_2", "VBFPairIdx__study[1]")
    rdf = rdf.Redefine("HasVBF", "VBFPairIdx__study[0] >= 0")

    prepared = prepare_rdf(
        rdf=rdf, dataset_name=dataset, era=era,
        selections_cfg=selections_cfg, systematics_cfg=systematics_cfg,
        is_data=False, seg_dict=seg_dict,
        dnn_payloads=None if args.no_dnn else ["DNN"],
        additional_cuts=additional_cuts, skip_validation=True,
    )
    node = prepared.get("inclusive")
    if node is None:
        raise RuntimeError(f"prepare_rdf returned no inclusive node for {dataset}")

    columns = list(COLUMNS)
    if not args.no_dnn:
        columns.append("DNN_NNOutput")
    arrays = node.Filter(f"baseline && {region}").AsNumpy(columns)
    result = {name: np.asarray(arrays[name]) for name in columns}
    result["weight__Central"] = result["weight__Central"].astype(np.float64) * weight_scale
    result["HasVBF"] = result["HasVBF"].astype(bool)
    if not args.no_dnn:
        clear_prediction_registry()
    print(f"    {dataset} [{strategy}]: {result['weight__Central'].size} events, "
          f"sum w = {result['weight__Central'].sum():.4g}"
          + (f", {len(files)}/{len(all_files)} files (weights x{weight_scale:.3g})"
             if weight_scale != 1.0 else ""), flush=True)
    return result


def stack(parts):
    parts = [p for p in parts if p is not None]
    if not parts:
        return None
    return {key: np.concatenate([p[key] for p in parts]) for key in parts[0]}


def working_point_mask(sample):
    """pT 35/25 sui due jet della coppia, piu' l'esistenza della coppia."""
    return (sample["HasVBF"]
            & (sample["vbfjet1_pt"] >= WP_LEADING_PT)
            & (sample["vbfjet2_pt"] >= WP_SUBLEADING_PT))


def scan(sample, variable, thresholds, base_mask):
    """Somma dei pesi sopra ogni soglia, a partire da base_mask."""
    values = sample[variable]
    weights = sample["weight__Central"]
    return np.array([weights[base_mask & (values >= t)].sum() for t in thresholds])


def significance(signal_yield, background_yield):
    """S/sqrt(B), zero dove il fondo si annulla."""
    signal_yield = np.asarray(signal_yield, dtype=np.float64)
    background_yield = np.asarray(background_yield, dtype=np.float64)
    out = np.zeros_like(signal_yield)
    good = background_yield > 0
    out[good] = signal_yield[good] / np.sqrt(background_yield[good])
    return out


def binned_significance(signal_counts, background_counts):
    """Asimov Z sommato in quadratura sui bin del DNN, dove S e B sono positivi."""
    signal_counts = np.asarray(signal_counts, dtype=np.float64)
    background_counts = np.asarray(background_counts, dtype=np.float64)
    good = (signal_counts > 0) & (background_counts > 0)
    s, b = signal_counts[good], background_counts[good]
    return float(np.sqrt(np.sum(2.0 * ((s + b) * np.log1p(s / b) - s))))


def dnn_scan(signal, background, variable, thresholds, masks, bins):
    """Z binnato sul DNN per ogni soglia di `variable`: cio' che vede il fit.

    Restituisce anche gli istogrammi per soglia, cosi' --combine puo' sommare
    le ere e ricalcolare la Z sulla somma.
    """
    out, histograms = [], {"signal": [], "background": []}
    for threshold in thresholds:
        counts = []
        for sample, mask in ((signal, masks["signal"]), (background, masks["background"])):
            keep = mask & (sample[variable] >= threshold)
            counts.append(np.histogram(sample["DNN_NNOutput"][keep], bins=bins,
                                       range=(0.0, 1.0),
                                       weights=sample["weight__Central"][keep])[0])
        out.append(binned_significance(*counts))
        histograms["signal"].append(counts[0].tolist())
        histograms["background"].append(counts[1].tolist())
    return out, histograms


def analyse_region(region, args, cfgs, output_dir, plot_dir):
    import ROOT

    info = REGIONS[region]
    presel = ("ROOT::VecOps::RVec<int>(SelectedJet_pt.size(), 1)"
              if args.no_horn_preselection else "SelectedJet_IsOutsideHorn")
    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]

    samples = {}
    for strategy in strategies:
        print(f"  strategy {strategy}", flush=True)
        for role in ("signal", "background"):
            parts = [read_dataset(dataset, strategy=strategy, era=args.era, args=args,
                                  region=region, presel_expression=presel, **cfgs)
                     for dataset in info[role]]
            merged = stack(parts)
            if merged is None:
                raise RuntimeError(f"No events for {role} in {region}")
            samples[(strategy, role)] = merged

    mjj_grid = np.arange(0.0, 1550.0, 50.0)
    deta_grid = np.arange(0.0, 6.2, 0.2)
    dnn_grid = np.linspace(0.0, 1.0, args.dnn_points, endpoint=False)

    summary = {"era": args.era, "region": region,
               "signal": info["signal"], "background": info["background"],
               "working_point": {"leading_pt": WP_LEADING_PT,
                                 "subleading_pt": WP_SUBLEADING_PT,
                                 "mjj": WP_MJJ, "delta_eta_jj": WP_DETA},
               "horn_preselection": not args.no_horn_preselection,
               "strategies": {}}
    curves = {}

    for strategy in strategies:
        signal = samples[(strategy, "signal")]
        background = samples[(strategy, "background")]
        # Denominatore delle efficienze: baseline + regione di massa, prima di
        # qualunque richiesta sulla coppia VBF.
        denominator = {"signal": signal["weight__Central"].sum(),
                       "background": background["weight__Central"].sum()}

        base = {"signal": working_point_mask(signal),
                "background": working_point_mask(background)}
        # Per la scansione in m_jj si tiene fisso il taglio in eta e viceversa,
        # altrimenti la curva mescola due effetti.
        deta_fixed = {role: base[role] & (samples[(strategy, role)]["delta_eta_jj"] >= WP_DETA)
                      for role in base}
        mjj_fixed = {role: base[role] & (samples[(strategy, role)]["m_jj"] >= WP_MJJ)
                     for role in base}

        entry = {}
        entry["mjj"] = {
            "thresholds": mjj_grid.tolist(),
            "signal": scan(signal, "m_jj", mjj_grid, deta_fixed["signal"]).tolist(),
            "background": scan(background, "m_jj", mjj_grid, deta_fixed["background"]).tolist(),
        }
        entry["deta"] = {
            "thresholds": deta_grid.tolist(),
            "signal": scan(signal, "delta_eta_jj", deta_grid, mjj_fixed["signal"]).tolist(),
            "background": scan(background, "delta_eta_jj", deta_grid, mjj_fixed["background"]).tolist(),
        }

        wp = {role: (base[role]
                     & (samples[(strategy, role)]["m_jj"] >= WP_MJJ)
                     & (samples[(strategy, role)]["delta_eta_jj"] >= WP_DETA))
              for role in base}
        wp_yield = {"signal": signal["weight__Central"][wp["signal"]].sum(),
                    "background": background["weight__Central"][wp["background"]].sum()}

        if not args.no_dnn:
            entry["dnn"] = {
                "thresholds": dnn_grid.tolist(),
                "signal": scan(signal, "DNN_NNOutput", dnn_grid, wp["signal"]).tolist(),
                "background": scan(background, "DNN_NNOutput", dnn_grid, wp["background"]).tolist(),
            }
            entry["dnn_histograms"] = {
                role: np.histogram(samples[(strategy, role)]["DNN_NNOutput"][wp[role]],
                                   bins=25, range=(0.0, 1.0),
                                   weights=samples[(strategy, role)]["weight__Central"][wp[role]]
                                   )[0].tolist()
                for role in ("signal", "background")
            }

        if not args.no_dnn:
            # Il fit e' sul DNN, che ha gia' m_jj e |Delta eta| fra gli input:
            # un taglio conviene solo se alza la Z binnata, non S/sqrt(B).
            for key, variable, masks, grid in (("mjj", "m_jj", deta_fixed, mjj_grid),
                                               ("deta", "delta_eta_jj", mjj_fixed, deta_grid)):
                values, histograms = dnn_scan(signal, background, variable, grid,
                                              masks, args.dnn_bins)
                entry[key]["dnn_binned_significance"] = values
                entry[key]["dnn_binned_histograms"] = histograms

        entry["denominator"] = denominator
        entry["working_point_yield"] = wp_yield
        entry["working_point_efficiency"] = {
            role: (wp_yield[role] / denominator[role] if denominator[role] else 0.0)
            for role in wp_yield
        }
        entry["working_point_significance"] = float(
            significance([wp_yield["signal"]], [wp_yield["background"]])[0])
        entry["pair_exists_yield"] = {
            role: float(samples[(strategy, role)]["weight__Central"][base[role]].sum())
            for role in base
        }
        entry["pair_exists_efficiency"] = {
            role: float(samples[(strategy, role)]["weight__Central"][base[role]].sum()
                        / denominator[role]) if denominator[role] else 0.0
            for role in base
        }
        summary["strategies"][strategy] = entry
        curves[strategy] = entry

    return finalize(region, info, summary, curves, strategies, args, output_dir, plot_dir)


def finalize(region, info, summary, curves, strategies, args, output_dir, plot_dir):
    """Miglior taglio sul DNN, poi json, plot e root: comune a era singola e --combine."""
    for strategy in strategies:
        entry = summary["strategies"][strategy]
        if "dnn" not in entry:
            continue
        dnn_grid = np.asarray(entry["dnn"]["thresholds"])
        values = significance(entry["dnn"]["signal"], entry["dnn"]["background"])
        best = int(np.argmax(values)) if values.size else 0
        entry["best_dnn_cut"] = {
            "threshold": float(dnn_grid[best]) if values.size else 0.0,
            "significance": float(values[best]) if values.size else 0.0,
            "signal": float(entry["dnn"]["signal"][best]) if values.size else 0.0,
            "background": float(entry["dnn"]["background"][best]) if values.size else 0.0,
        }

    output_dir.mkdir(parents=True, exist_ok=True)
    plot_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / f"{region}.json").write_text(json.dumps(summary, indent=2) + "\n")
    make_plots(region, info, summary, curves, strategies, args, plot_dir)
    write_root(region, summary, strategies, args, output_dir)
    return summary


def make_plots(region, info, summary, curves, strategies, args, output_dir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    def finish(figure, stem):
        for axis in figure.axes:
            axis.grid(True, alpha=0.25, linewidth=0.6)
            axis.set_axisbelow(True)
        figure.tight_layout()
        for extension in ("png", "pdf"):
            figure.savefig(output_dir / f"{region}_{stem}.{extension}", dpi=150)
        plt.close(figure)
        print(f"    wrote {output_dir / f'{region}_{stem}.png'}", flush=True)

    for key, xlabel, stem, fixed in (
        ("mjj", "m(jj) threshold [GeV]", "efficiency_vs_mjj",
         rf"$|\Delta\eta_{{jj}}| \geq$ {WP_DETA}"),
        ("deta", r"$|\Delta\eta(jj)|$ threshold", "efficiency_vs_deta",
         rf"$m_{{jj}} \geq$ {WP_MJJ:.0f} GeV"),
    ):
        figure, (left, right) = plt.subplots(1, 2, figsize=(12, 4.8))
        for strategy in strategies:
            entry = curves[strategy]
            thresholds = np.array(entry[key]["thresholds"])
            colour = STRATEGY_COLOR[strategy]
            for role, style in (("signal", "-"), ("background", "--")):
                efficiency = (np.array(entry[key][role])
                              / entry["denominator"][role]) if entry["denominator"][role] else thresholds * 0
                left.plot(thresholds, efficiency, style, color=colour, linewidth=2,
                          label=f"{STRATEGY_LABEL[strategy]} - "
                                f"{info['signal_label'] if role == 'signal' else info['background_label']}")
            right.plot(thresholds,
                       significance(entry[key]["signal"], entry[key]["background"]),
                       "-", color=colour, linewidth=2, label=STRATEGY_LABEL[strategy])
        left.set_xlabel(xlabel)
        left.set_ylabel("efficiency (w.r.t. baseline + mass region)")
        left.set_yscale("log")
        left.legend(fontsize=8)
        left.set_title(f"{era_label(args.era)} {region} - efficiencies ({fixed})", fontsize=10)
        right.set_xlabel(xlabel)
        right.set_ylabel(r"S/$\sqrt{B}$")
        right.legend(fontsize=8)
        right.set_title(f"{era_label(args.era)} {region} - sensitivity ({fixed})", fontsize=10)
        finish(figure, stem)

    if args.no_dnn:
        return

    edges = np.linspace(0.0, 1.0, 26)
    centres = 0.5 * (edges[:-1] + edges[1:])
    figure, (left, right) = plt.subplots(1, 2, figsize=(12, 4.8))
    for strategy in strategies:
        entry = curves[strategy]
        colour = STRATEGY_COLOR[strategy]
        for role, style in (("signal", "-"), ("background", "--")):
            counts = np.array(entry["dnn_histograms"][role], dtype=float)
            total = counts.sum()
            left.step(centres, counts / total if total else counts, style, where="mid",
                      color=colour, linewidth=2,
                      label=f"{STRATEGY_LABEL[strategy]} - "
                            f"{info['signal_label'] if role == 'signal' else info['background_label']}")
        right.plot(np.array(entry["dnn"]["thresholds"]),
                   significance(entry["dnn"]["signal"], entry["dnn"]["background"]),
                   "-", color=colour, linewidth=2, label=STRATEGY_LABEL[strategy])
    left.set_xlabel("DNN score")
    left.set_ylabel("fraction of events (unit area)")
    left.set_yscale("log")
    left.legend(fontsize=8)
    left.set_title(f"{era_label(args.era)} {region} - DNN at the VBF working point", fontsize=10)
    right.set_xlabel("DNN score threshold")
    right.set_ylabel(r"S/$\sqrt{B}$")
    right.legend(fontsize=8)
    right.set_title(f"{era_label(args.era)} {region} - sensitivity with the DNN", fontsize=10)
    finish(figure, "dnn")

    if not all("dnn_binned_significance" in curves[s]["mjj"] for s in strategies):
        return
    figure, axes = plt.subplots(1, 2, figsize=(12, 4.8))
    for axis, (key, xlabel, fixed) in zip(axes, (
        ("mjj", "m(jj) threshold [GeV]", rf"$|\Delta\eta_{{jj}}| \geq$ {WP_DETA}"),
        ("deta", r"$|\Delta\eta(jj)|$ threshold", rf"$m_{{jj}} \geq$ {WP_MJJ:.0f} GeV"),
    )):
        for strategy in strategies:
            entry = curves[strategy][key]
            axis.plot(entry["thresholds"], entry["dnn_binned_significance"], "-",
                      color=STRATEGY_COLOR[strategy], linewidth=2,
                      label=STRATEGY_LABEL[strategy])
        axis.set_xlabel(xlabel)
        axis.set_ylabel(f"binned Asimov Z on the DNN ({args.dnn_bins} bins)")
        axis.legend(fontsize=8)
        axis.set_title(f"{era_label(args.era)} {region} - DNN-fit sensitivity ({fixed})",
                       fontsize=10)
    finish(figure, "dnn_binned_vs_cuts")


def write_root(region, summary, strategies, args, output_dir):
    import ROOT

    path = output_dir / f"{region}.root"
    handle = ROOT.TFile.Open(str(path), "RECREATE")
    for strategy in strategies:
        entry = summary["strategies"][strategy]
        for key in ("mjj", "deta", "dnn"):
            if key not in entry:
                continue
            thresholds = np.array(entry[key]["thresholds"], dtype=float)
            if thresholds.size < 2:
                continue
            width = thresholds[1] - thresholds[0]
            edges = np.append(thresholds, thresholds[-1] + width) - 0.5 * width
            for role in ("signal", "background"):
                name = f"{strategy}_{key}_{role}"
                histogram = ROOT.TH1D(name, f"{name};threshold;sum w", thresholds.size, edges)
                for index, value in enumerate(entry[key][role], start=1):
                    histogram.SetBinContent(index, value)
                histogram.Write()
            values = significance(entry[key]["signal"], entry[key]["background"])
            name = f"{strategy}_{key}_significance"
            histogram = ROOT.TH1D(name, f"{name};threshold;S/sqrt(B)", thresholds.size, edges)
            for index, value in enumerate(values, start=1):
                histogram.SetBinContent(index, value)
            histogram.Write()
    handle.Close()
    print(f"    wrote {path}", flush=True)


def report(summaries, strategies):
    print("\n" + "=" * 78)
    print("VBF working point: pT >= 35/25, m_jj >= 400 GeV, |Delta eta_jj| >= 2.5")
    print("=" * 78)
    header = f"{'region':<12}{'strategy':<26}{'eff S':>9}{'eff B':>10}{'S/sqrt(B)':>12}"
    print(header)
    print("-" * len(header))
    for region, summary in summaries.items():
        for strategy in strategies:
            entry = summary["strategies"][strategy]
            print(f"{region:<12}{STRATEGY_LABEL[strategy]:<26}"
                  f"{entry['working_point_efficiency']['signal']:>9.4f}"
                  f"{entry['working_point_efficiency']['background']:>10.5f}"
                  f"{entry['working_point_significance']:>12.4f}")
    if all("best_dnn_cut" in summary["strategies"][strategies[0]] for summary in summaries.values()):
        print("\nBest DNN score cut, on top of the working point:")
        header = f"{'region':<12}{'strategy':<26}{'cut':>9}{'S/sqrt(B)':>12}"
        print(header)
        print("-" * len(header))
        for region, summary in summaries.items():
            for strategy in strategies:
                best = summary["strategies"][strategy]["best_dnn_cut"]
                print(f"{region:<12}{STRATEGY_LABEL[strategy]:<26}"
                      f"{best['threshold']:>9.3f}{best['significance']:>12.4f}")


def combine(args, regions, strategies):
    """Somma le uscite json di piu' ere e rifa' plot e tabelle sulla somma.

    Si sommano solo rese (e istogrammi): efficienze e significativita' si
    ricalcolano dopo, perche' non sono additive.
    """
    eras = [era.strip() for era in args.combine.split(",") if era.strip()]
    args.era = args.combined_name
    output_dir = args.output / args.combined_name
    plot_dir = (Path(args.plot_output) / args.combined_name) if keep_plots_apart(args) else output_dir

    def add(total, part):
        if isinstance(part, dict):
            return {key: add(total[key], part[key]) if key in total else part[key]
                    for key in part}
        if isinstance(part, list):
            return [add(a, b) for a, b in zip(total, part)]
        return total + part

    summaries = {}
    for region in regions:
        inputs = []
        for era in eras:
            path = args.output / era / f"{region}.json"
            if not path.is_file():
                raise SystemExit(f"Missing input for --combine: {path}")
            inputs.append(json.loads(path.read_text()))
        summary = {key: value for key, value in inputs[0].items() if key != "strategies"}
        summary.update({"era": args.combined_name, "combined_eras": eras,
                        "background": sorted({b for i in inputs for b in i["background"]}),
                        "strategies": {}})
        additive = ("mjj", "deta", "dnn", "dnn_histograms", "denominator",
                    "working_point_yield", "pair_exists_yield")
        for strategy in strategies:
            parts = [i["strategies"][strategy] for i in inputs]
            entry = {}
            for key in additive:
                if not all(key in part for part in parts):
                    continue
                total = parts[0][key]
                for part in parts[1:]:
                    total = add(total, part[key])
                entry[key] = total
            # Le soglie non si sommano: si rimettono quelle di un'era.
            for key in ("mjj", "deta", "dnn"):
                if key in entry:
                    entry[key]["thresholds"] = parts[0][key]["thresholds"]
            for key in ("mjj", "deta"):
                histograms = entry.get(key, {}).get("dnn_binned_histograms")
                if histograms:
                    entry[key]["dnn_binned_significance"] = [
                        binned_significance(s, b)
                        for s, b in zip(histograms["signal"], histograms["background"])]
            den, wp = entry["denominator"], entry["working_point_yield"]
            entry["working_point_efficiency"] = {r: wp[r] / den[r] if den[r] else 0.0 for r in wp}
            entry["working_point_significance"] = float(
                significance([wp["signal"]], [wp["background"]])[0])
            if "pair_exists_yield" in entry:
                entry["pair_exists_efficiency"] = {
                    r: entry["pair_exists_yield"][r] / den[r] if den[r] else 0.0 for r in den}
            summary["strategies"][strategy] = entry
        print(f"\n=== {args.combined_name} {region} ({', '.join(eras)})", flush=True)
        summaries[region] = finalize(region, REGIONS[region], summary, summary["strategies"],
                                     strategies, args, output_dir, plot_dir)
    report(summaries, strategies)
    print(f"\nJSON and ROOT in {output_dir}")
    print(f"Images in {plot_dir}")
    return 0


def main():
    args = arguments()
    if args.combine:
        strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
        regions = [r.strip() for r in args.regions.split(",") if r.strip()]
        return combine(args, regions, strategies)
    import ROOT
    from common.utilities import initialize_root_runtime

    initialize_root_runtime()
    if args.threads > 1:
        ROOT.EnableImplicitMT(args.threads)
    ROOT.gInterpreter.Declare(PAIR_FINDERS)

    unknown = sorted(set(s.strip() for s in args.strategies.split(",")) - set(STRATEGIES))
    if unknown:
        raise SystemExit(f"Unknown strategies: {unknown}; available {list(STRATEGIES)}")
    regions = [r.strip() for r in args.regions.split(",") if r.strip()]
    unknown = sorted(set(regions) - set(REGIONS))
    if unknown:
        raise SystemExit(f"Unknown regions: {unknown}; available {list(REGIONS)}")

    config_dir = REPO / "config" / args.era
    cfgs = {
        "selections_cfg": load_yaml(config_dir / "selections.yaml"),
        "systematics_cfg": load_yaml(config_dir / "systematics.yaml"),
        "samples_cfg": load_yaml(config_dir / "samples.yaml"),
    }
    output_dir = args.output / args.era
    plot_dir = (Path(args.plot_output) / args.era) if keep_plots_apart(args) else output_dir
    summaries = {}
    for region in regions:
        print(f"\n=== {args.era} {region}", flush=True)
        summaries[region] = analyse_region(region, args, cfgs, output_dir, plot_dir)

    strategies = [s.strip() for s in args.strategies.split(",") if s.strip()]
    report(summaries, strategies)
    print(f"\nJSON and ROOT in {output_dir}")
    print(f"Images in {plot_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
