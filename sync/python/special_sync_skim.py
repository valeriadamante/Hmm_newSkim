#!/usr/bin/env python3
"""Special sync skim of 2026-09-23: NanoAOD -> compact sync tuple, data only.

Reuses the framework's golden JSON, MET filters, muon ScaRe/FSR and jet
corrections, jet ID and veto map, and redefines only what the special sync
asks for (definitions in config/Run3_2024/selections_sync_special_20260923.yaml):

  * muon pT is always the plain NanoAOD pT (Muon_pt), including sorting,
    trigger matching and the 26/20 GeV thresholds; only the dimuon system
    uses the NanoAOD pT with ScaRe and FSR recovery (Muon_p4_nano_corr_FSR,
    no bsc);
  * good muons: pT>10, |eta|<2.4, mediumId, |dz|<0.1, |dxy|<0.05 and
    newIso = (pfRelIso04_all*pT - pT_gamma)/pT < 0.25, where pT_gamma is the
    FSR photon (Muon_fsrPhotonIdx) accepted by the FSR recovery and inside the
    isolation cone (dR<0.4); exactly 2 good muons;
  * exactly 2 loose muons: as good muons but looseId, |dz|<1, |dxy|<0.5;
    a superset of the good muons, which are counted among them;
  * electron veto on good electrons: pT>10, |eta|<2.5, mvaIso_WP90;
  * good jets cleaned (dR>0.4) against good muons and good electrons;
  * HasVBF: among pT-ordered good jets, the first (pT-leading) pair with
    pT>35/25, m_jj>400 and |deta|>2.5.

One job writes a tuple (mass_inclusive events) and a JSON with the skim
report and the cutflow counts; special_sync_merge.py combines the jobs.
"""
import argparse
import json
import os
import sys
from pathlib import Path

import ROOT

ROOT.gROOT.SetBatch(True)
REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))
os.environ.setdefault("ANALYSIS_PATH", str(REPOSITORY))
ROOT.gInterpreter.Declare(f'#include "{REPOSITORY / "analysis" / "AnalysisTools.h"}"')

import yaml  # noqa: E402
import common.utilities as utilities  # noqa: E402

SPECIAL_CONFIG = REPOSITORY / "config" / "Run3_2024" / "selections_sync_special_20260923.yaml"
ERA = "Run3_2024"

HELPERS = r"""
#ifndef SPECIAL_SYNC_20260923
#define SPECIAL_SYNC_20260923
namespace special_sync {
using RVecF = ROOT::VecOps::RVec<float>;
using RVecI = ROOT::VecOps::RVec<int>;
using RVecB = ROOT::VecOps::RVec<bool>;
using P4 = ROOT::Math::LorentzVector<ROOT::Math::PtEtaPhiM4D<double>>;
using RVecP4 = ROOT::VecOps::RVec<P4>;

// pT of the FSR photon associated with each muon, with the same acceptance
// as fsr_corrected_p4 (corrections/muon_fsr.py) evaluated on the NanoAOD pT.
// maxDR restricts it to photons inside the isolation cone (0.4); a negative
// value keeps the full FSR-recovery acceptance (dR<0.5).
RVecF FsrPhotonPt(const RVecF& mu_pt, const RVecF& mu_eta, const RVecF& mu_phi,
                  const RVecI& fsr_idx, const RVecF& fsr_pt, const RVecF& fsr_eta,
                  const RVecF& fsr_phi, const RVecF& fsr_dROverEt2,
                  const RVecF& fsr_relIso03, const RVecI& fsr_electronIdx,
                  float maxDR) {
  RVecF out(mu_pt.size(), 0.f);
  for (size_t i = 0; i < mu_pt.size(); ++i) {
    const int k = fsr_idx[i];
    if (k < 0 || k >= int(fsr_pt.size())) continue;
    const float dr = ROOT::VecOps::DeltaR(mu_eta[i], fsr_eta[k], mu_phi[i], fsr_phi[k]);
    if (!(dr > 0.0001 && dr < 0.5)) continue;
    if (maxDR > 0 && !(dr < maxDR)) continue;
    if (fsr_electronIdx[k] != -1) continue;
    if (fsr_pt[k] / mu_pt[i] > 0.4) continue;
    if (fsr_dROverEt2[k] > 0.012) continue;
    if (fsr_relIso03[k] / mu_pt[i] > 1.8) continue;
    out[i] = fsr_pt[k];
  }
  return out;
}

RVecF FsrPhotonDR(const RVecF& mu_eta, const RVecF& mu_phi, const RVecI& fsr_idx,
                  const RVecF& fsr_eta, const RVecF& fsr_phi) {
  RVecF out(mu_eta.size(), -1.f);
  for (size_t i = 0; i < mu_eta.size(); ++i) {
    const int k = fsr_idx[i];
    if (k < 0 || k >= int(fsr_eta.size())) continue;
    out[i] = ROOT::VecOps::DeltaR(mu_eta[i], fsr_eta[k], mu_phi[i], fsr_phi[k]);
  }
  return out;
}

// Jets passing preselection, veto map and horn veto, and farther than 0.4
// from every good muon and every good electron.
RVecB CleanJets(const RVecP4& jets, const RVecB& presel, const RVecB& vetoMap,
                const RVecB& outsideHorn, const RVecP4& muons, const RVecP4& electrons) {
  RVecB out(jets.size(), false);
  for (size_t i = 0; i < jets.size(); ++i) {
    bool ok = presel[i] && !vetoMap[i] && outsideHorn[i];
    for (const auto& m : muons)
      if (ok && ROOT::Math::VectorUtil::DeltaR(jets[i], m) <= 0.4) ok = false;
    for (const auto& e : electrons)
      if (ok && ROOT::Math::VectorUtil::DeltaR(jets[i], e) <= 0.4) ok = false;
    out[i] = ok;
  }
  return out;
}

// Jets are pT ordered, so the first pair found in (i, j>i) order is the one
// with the highest leading pT and, for that leading jet, the highest
// subleading pT.
RVecI LeadingVBFPair(const RVecF& pt, const RVecF& eta, const RVecF& phi, const RVecF& mass) {
  RVecI result{-1000, -1000};
  for (size_t i = 0; i < pt.size(); ++i) {
    if (!(pt[i] > 35.)) continue;
    for (size_t j = i + 1; j < pt.size(); ++j) {
      if (!(pt[j] > 25.)) continue;
      if (!(std::abs(eta[i] - eta[j]) > 2.5)) continue;
      const P4 a(pt[i], eta[i], phi[i], mass[i]);
      const P4 b(pt[j], eta[j], phi[j], mass[j]);
      if (!((a + b).M() > 400.)) continue;
      result[0] = int(i);
      result[1] = int(j);
      return result;
    }
  }
  return result;
}
}  // namespace special_sync
#endif
"""


def arguments():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dataset-name", required=True, choices=("Muon0_Run2024H", "Muon1_Run2024H"))
    parser.add_argument("--input-file", required=True, action="append")
    parser.add_argument("--output-file", required=True, type=Path)
    parser.add_argument("--report-file", type=Path)
    parser.add_argument("--n-events", type=int, default=-1)
    parser.add_argument("--threads", type=int, default=1)
    return parser.parse_args()


def load(path):
    with open(path) as stream:
        return yaml.safe_load(stream)


def define_muons(df, muon_columns, trigger_config):
    """Good/loose muons with NanoAOD pT, trigger matching and dimuon system."""
    new_cols = []

    def track(node, name, expression):
        if name in new_cols:
            return node
        new_cols.append(name)
        return node.Define(name, expression)

    df = df.Define("Muon_p4_nano", "GetP4(Muon_pt, Muon_eta, Muon_phi, Muon_mass)")
    df = df.Define("Muon_p4_nano_corr", "GetP4(Muon_pt_nano_corr, Muon_eta, Muon_phi, Muon_mass)")
    fsr_args = ("Muon_pt, Muon_eta, Muon_phi, Muon_fsrPhotonIdx, FsrPhoton_pt, FsrPhoton_eta, "
                "FsrPhoton_phi, FsrPhoton_dROverEt2, FsrPhoton_relIso03, FsrPhoton_electronIdx")
    df = df.Define("Muon_fsrPhotonPtIso", f"special_sync::FsrPhotonPt({fsr_args}, 0.4f)")
    df = df.Define("Muon_fsrPhotonPtRecovered", f"special_sync::FsrPhotonPt({fsr_args}, -1.f)")
    df = df.Define("Muon_fsrPhotonDR", "special_sync::FsrPhotonDR(Muon_eta, Muon_phi, "
                   "Muon_fsrPhotonIdx, FsrPhoton_eta, FsrPhoton_phi)")
    df = df.Define("Muon_newIso", "(Muon_pfRelIso04_all * Muon_pt - Muon_fsrPhotonPtIso) / Muon_pt")

    kinematic = "Muon_pt > 10 && abs(Muon_eta) < 2.4 && Muon_newIso < 0.25"
    df = df.Define("good_muons", f"{kinematic} && Muon_mediumId && abs(Muon_dz) < 0.1 && abs(Muon_dxy) < 0.05")
    df = df.Define("loose_muons", f"{kinematic} && Muon_looseId && abs(Muon_dz) < 1 && abs(Muon_dxy) < 0.5")
    df = track(df, "n_goodMuons", "int(ROOT::VecOps::Sum(good_muons))")
    df = track(df, "n_looseMuons", "int(ROOT::VecOps::Sum(loose_muons))")

    # Trigger matching with the NanoAOD pT and direction.
    df = df.Define("TrigObj_idx", "CreateIndexes(TrigObj_pt.size())")
    df = df.Define("TrigObj_mass", "RVecF(TrigObj_pt.size(), 0.f)")
    df = df.Define("TrigObj_p4", "GetP4(TrigObj_pt, TrigObj_eta, TrigObj_phi, TrigObj_mass, TrigObj_idx)")
    trigger_filters = []
    for path, config in trigger_config.items():
        path_name = config["path"][0]
        leg = config["legs"][0]
        df = df.Define(f"TrigObj_passOnlineCut_{path}", leg["online_obj"]["cut"])
        df = df.Define(f"Muon_passOfflineCut_{path}", leg["offline_obj"]["cut"].format(obj="Muon", pt="pt"))
        df = df.Define(f"Muon_TriggerMatchingIdx_{path}",
                       f"FindMatching(Muon_passOfflineCut_{path}, TrigObj_passOnlineCut_{path}, "
                       f"Muon_p4_nano, TrigObj_p4, 0.4)")
        df = track(df, f"Event_HasTriggerMatching_{path}",
                   f"{path_name} && Any(Muon_TriggerMatchingIdx_{path} > -1)")
        new_cols.append(path_name)
        trigger_filters.append(f"Event_HasTriggerMatching_{path}")
    df = df.Filter(" || ".join(trigger_filters), "Trigger matching for " + "__".join(trigger_config))

    df = df.Define("good_idx", "ROOT::VecOps::Nonzero(good_muons)")
    df = df.Define("sorted_idx", "Reverse(Take(good_idx, Argsort(Take(Muon_pt, good_idx))))")
    df = track(df, "mu1_idx", "sorted_idx.size() > 0 ? int(sorted_idx[0]) : -1")
    df = track(df, "mu2_idx", "sorted_idx.size() > 1 ? int(sorted_idx[1]) : -1")
    df = df.Filter("sorted_idx.size() == 2", "Exactly 2 muons")
    df = df.Filter("n_looseMuons == 2", "Exactly 2 loose muons")

    stage_columns = {
        "pt_raw_noCorr": "Muon_pt_raw_noCorr", "pt_raw_corr": "Muon_pt_raw_corr",
        "pt_raw_scale": "Muon_pt_raw_scale", "pt_FSR_noCorr": "Muon_pt_FSR_noCorr",
        "pt_FSR_corr": "Muon_pt_FSR_corr", "pt_FSR_scale": "Muon_pt_FSR_scale",
        "pt_err": "Muon_pt_err", "pt_nano": "Muon_pt", "pt_nano_corr": "Muon_pt_nano_corr",
        "pt_nano_corr_FSR": "Muon_pt_nano_corr_FSR", "newIso": "Muon_newIso",
        "fsrPhoton_ptIso": "Muon_fsrPhotonPtIso", "fsrPhoton_ptRecovered": "Muon_fsrPhotonPtRecovered",
        "fsrPhoton_dR": "Muon_fsrPhotonDR",
    }
    for i in (1, 2):
        idx = f"mu{i}_idx"
        df = df.Define(f"mu{i}_p4", f"Muon_p4_nano.at({idx})")
        df = df.Define(f"mu{i}_p4_nano_corr", f"Muon_p4_nano_corr.at({idx})")
        df = df.Define(f"mu{i}_p4_nano_corr_FSR", f"Muon_p4_nano_corr_FSR.at({idx})")
        df = df.Define(f"mu{i}_p4_FSR_corr", f"Muon_p4_FSR_corr.at({idx})")
        df = track(df, f"mu{i}_pt", f"Muon_pt[{idx}]")
        df = track(df, f"mu{i}_eta", f"Muon_eta[{idx}]")
        df = track(df, f"mu{i}_phi", f"Muon_phi[{idx}]")
        df = track(df, f"mu{i}_mass", f"Muon_mass[{idx}]")
        for column in muon_columns:
            df = track(df, f"mu{i}_{column.split('_', 1)[1]}", f"{column}[{idx}]")
        for stage, column in stage_columns.items():
            df = track(df, f"mu{i}_{stage}", f"{column}[{idx}]")
        for stage in ("raw_noCorr", "raw_corr", "raw_scale", "FSR_noCorr", "FSR_corr", "FSR_scale"):
            df = track(df, f"mu{i}_eta_{stage}", f"Muon_p4_{stage}[{idx}].Eta()")
            df = track(df, f"mu{i}_phi_{stage}", f"Muon_p4_{stage}[{idx}].Phi()")
        df = track(df, f"mu{i}_GenMatched", "false")
        for path in trigger_config:
            df = track(df, f"mu{i}_HasTriggerMatching_{path}", f"Muon_TriggerMatchingIdx_{path}[{idx}] >= 0")

    pair_filters = [f"(Event_HasTriggerMatching_{path} && (mu1_HasTriggerMatching_{path} || "
                    f"mu2_HasTriggerMatching_{path}))" for path in trigger_config]
    df = df.Filter(" || ".join(pair_filters), "Selected dimuon trigger matching")

    # Dimuon system: NanoAOD pT with ScaRe and FSR recovery, only here.
    df = df.Define("dimuon_p4_nano_corr_FSR", "mu1_p4_nano_corr_FSR + mu2_p4_nano_corr_FSR")
    df = track(df, "m_mumu", "dimuon_p4_nano_corr_FSR.M()")
    df = track(df, "pt_mumu", "dimuon_p4_nano_corr_FSR.Pt()")
    df = track(df, "eta_mumu", "dimuon_p4_nano_corr_FSR.Eta()")
    df = track(df, "phi_mumu", "dimuon_p4_nano_corr_FSR.Phi()")
    df = track(df, "m_mumu_nano", "(mu1_p4 + mu2_p4).M()")
    df = track(df, "m_mumu_nano_corr", "(mu1_p4_nano_corr + mu2_p4_nano_corr).M()")
    df = track(df, "m_mumu_FSR_corr", "(mu1_p4_FSR_corr + mu2_p4_FSR_corr).M()")
    df = df.Filter("m_mumu > 50 && m_mumu < 200", "dimuon mass cut")
    return df, new_cols


def define_electrons(df):
    df = df.Define("Electron_p4", "GetP4(Electron_pt, Electron_eta, Electron_phi, Electron_mass)")
    df = df.Define("good_electrons", "Electron_pt > 10 && abs(Electron_eta) < 2.5 && Electron_mvaIso_WP90")
    df = df.Define("n_goodElectrons", "int(ROOT::VecOps::Sum(good_electrons))")
    df = df.Define("GoodElectron_p4", "Electron_p4[good_electrons]")
    df = df.Filter("n_goodElectrons == 0", "No extra electrons")
    return df, ["n_goodElectrons"]


def main():
    args = arguments()
    if args.threads > 1 and args.n_events < 0:
        ROOT.EnableImplicitMT(args.threads)
    ROOT.gInterpreter.Declare(HELPERS)
    config_dir = REPOSITORY / "config" / ERA
    config = utilities.get_config(str(config_dir / "maincfg.yaml"))
    config["want_variations"] = False
    dataset_cfg = utilities.get_config(str(config_dir / "samples.yaml"))[args.dataset_name]
    if not dataset_cfg.get("is_data", False):
        raise RuntimeError("the special sync skim is data only")
    sel_config = utilities.get_config(str(config_dir / "selections.yaml"))
    from common.jet_horn_policy import configure_horn_veto, horn_mitigation_enabled
    configure_horn_veto(sel_config, ERA, "configured")
    trigger_config = utilities.get_config(str(config_dir / "triggers.yaml"))
    syst_cfg = utilities.get_config(str(config_dir / "systematics.yaml"))
    nano_version = config.get("nano_version", "v15")
    input_files = [path for value in args.input_file for path in value.split(",") if path]

    chain = ROOT.TChain("Events")
    for path in input_files:
        if chain.Add(path) == 0:
            raise RuntimeError(f"could not add input file {path}")
    df = ROOT.RDataFrame(chain)
    if args.n_events > 0:
        df = df.Range(args.n_events)
    df = df.Define("period", f"static_cast<int>(Period::{config['era']})")
    df = df.Define("is_data", "true").Define("is_data_int", "1").Define("is_signal", "false")

    from corrections.general import apply_golden_json, apply_corrections
    df = apply_golden_json(df, config["lumiFile"])
    config["apply_jet_horn_mitigation"] = horn_mitigation_enabled(ERA, sel_config)
    df = apply_corrections(df, config, dataset_cfg, args.dataset_name, False)
    if "MET_flags" in config:
        from analysis.other import applyMETFlags
        df = applyMETFlags(df, config, True)

    from analysis.muons import DefineMuonPtAndP4
    df = DefineMuonPtAndP4(df, False)
    muon_columns = utilities.GetObservablesCols("Muon", True, nano_version)
    df, cols = define_muons(df, muon_columns, trigger_config)
    df, electron_cols = define_electrons(df)
    cols += electron_cols

    from analysis.jets import ProcessAllJetVariables, SelectJetVars
    from corrections.btag_wpValues import getBTagWPValues
    from corrections.jetVetoMap import ApplyJetVetoMap
    btag_wps = getBTagWPValues(config)
    btag_algo = config.get("bTagAlgo", "PNet")
    jet_columns = utilities.GetObservablesCols("Jet", True, nano_version)
    df, _ = ProcessAllJetVariables(df, jet_columns, sel_config, btag_algo, btag_wps, False, syst_cfg)
    df, _ = ApplyJetVetoMap(df, config, "nano", False, False, nano_version == "v12", False, syst_cfg)
    # Good-jet definition with the lepton cleaning of the special sync;
    # SelectJetVars keeps predefined columns and builds SelectedJet_* on them.
    pt_min = sel_config.get("jet_pt_min", 25.0)
    eta_max = sel_config.get("jet_eta_max", 4.7)
    df = df.Define("Jet_preSel", f"v_ops::pt(Jet_p4) > {pt_min} && abs(v_ops::eta(Jet_p4)) < {eta_max} && Jet_passJetIdTight")
    df = df.Define("GoodMuon_p4", "Muon_p4_nano[good_muons]")
    df = df.Define("Jet_NoOverlapWithMuons", "special_sync::CleanJets(Jet_p4, Jet_preSel, Jet_vetoMap, "
                   "Jet_IsOutsideHorn, GoodMuon_p4, GoodElectron_p4)")
    df = df.Define("goodJet", "Jet_NoOverlapWithMuons")
    df, _ = SelectJetVars(df, jet_columns, sel_config, btag_algo, btag_wps, False, syst_cfg)
    df = df.Define("VBFPairIdx", "special_sync::LeadingVBFPair(SelectedJet_pt, SelectedJet_eta, "
                   "SelectedJet_phi, SelectedJet_mass)")
    df = df.Define("HasVBF", "VBFPairIdx[0] >= 0")
    df = df.Define("VBFJetIdx_1", "VBFPairIdx[0]")
    df = df.Define("VBFJetIdx_2", "VBFPairIdx[1]")

    # Compact tuple with the column set of the previous sync tuples.
    import studies.prepare_tuple_forSync as sync_tuple
    special = load(SPECIAL_CONFIG)
    sync_tuple.SYNC_CONFIG = special
    sync_tuple.SYNC_CONFIG_PATH = SPECIAL_CONFIG
    df = sync_tuple.prepare(df, "standard")
    report = df.Report()
    keep = sync_tuple.selected_columns(df, False)
    extra = cols + ["exactly_2_loose_muons", "bothMuons_ML", "m_mumu_nano",
                    "m_mumu_nano_corr", "m_mumu_FSR_corr"]
    available = sync_tuple.columns(df)
    keep = sorted(c for c in set(keep) | {c for c in extra if c in available} if "_p4" not in c)

    cutflows = {}
    count_actions = []
    for key in ("cutflow", "cutflow_vbf_Z_CR_H_SB"):
        node = df
        cutflows[key] = []
        for step in special[key]:
            node = node.Filter(step, f"{key}_{step}")
            action = node.Count()
            cutflows[key].append((step, action))
            count_actions.append(action)
    yields = [((kind, name), df.Filter(name).Count()) for kind, name in sync_tuple.stored_category_region_names()]
    total = df.Count()

    args.output_file.parent.mkdir(parents=True, exist_ok=True)
    options = ROOT.RDF.RSnapshotOptions()
    options.fLazy = True
    options.fMode = "RECREATE"
    snapshot = df.Filter("mass_inclusive", "sync output selection").Snapshot(
        "Events", str(args.output_file), utilities.ListToVector(keep), options)
    ROOT.RDF.RunGraphs([snapshot, total, *count_actions, *(a for _, a in yields)])

    _, report_json = utilities.SaveReport(df, report.GetValue())
    summary = {
        "dataset": args.dataset_name, "input_files": input_files,
        "selection_config": str(SPECIAL_CONFIG),
        "report": report_json,
        "cutflows": {key: [[step, int(a.GetValue())] for step, a in steps] for key, steps in cutflows.items()},
        "yields": [[kind, name, int(a.GetValue())] for (kind, name), a in yields],
        "events_after_skim": int(total.GetValue()),
    }
    report_path = args.report_file or args.output_file.with_name(args.output_file.stem + "_report.json")
    report_path.write_text(json.dumps(summary, indent=2))
    print(f"[special-sync] wrote {args.output_file} and {report_path}")


if __name__ == "__main__":
    main()
