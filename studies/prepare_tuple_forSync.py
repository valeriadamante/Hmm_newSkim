#!/usr/bin/env python3
"""Fast standalone synchronization skimmer for one dataset at a time."""
import argparse
import copy
import csv
import glob
import json
import os
import re
import sys
from pathlib import Path

import ROOT
import yaml

ROOT.gROOT.SetBatch(True)
MISSING = -1000.0
REPOSITORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY))

from common.add_vars import DefineSelections  # noqa: E402

SYNC_CONFIG_PATH = REPOSITORY / "config" / "Run3_2024" / "selections_sync.yaml"
with SYNC_CONFIG_PATH.open() as stream:
    SYNC_CONFIG = yaml.safe_load(stream)
REGIONS = SYNC_CONFIG["masses_regions"]
CATEGORIES = SYNC_CONFIG["categories"]


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="ROOT file(s), glob(s), or dataset directory")
    parser.add_argument("-o", "--output", type=Path,
                        help="output ROOT file (required unless --cutflow-only)")
    parser.add_argument("--tree", default="Events")
    parser.add_argument("--mc", action="store_true", help="also save all available event weights")
    parser.add_argument("--selection", default="mass_inclusive", help="output filter; use 1 for none")
    parser.add_argument("--threads", type=int, default=max(1, min(8, os.cpu_count() or 1)))
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cutflow-output", type=Path,
                        help="cutflow CSV (default: <output stem>_cutflow.csv)")
    parser.add_argument("--no-cutflow", action="store_true",
                        help="skip report JSON aggregation and cutflow output")
    parser.add_argument("--cutflow-only", type=Path, metavar="TUPLE",
                        help="read an existing tuple and produce only its cutflow CSV")
    parser.add_argument("--tuple-preselection", default="mass_inclusive",
                        help="cut already applied to --cutflow-only tuple; use 1 for none")
    parser.add_argument("--cutflow-key", default="cutflow",
                        help="YAML key holding the cumulative cutflow step list")
    parser.add_argument("--vbf-pair-strategy", choices=("standard", "leading"),
                        default="standard", help=argparse.SUPPRESS)
    return parser.parse_args()


def find_files(items):
    found = []
    for item in items:
        path = Path(item).expanduser()
        matches = (sorted(path.rglob("*.root")) if path.is_dir() else
                   [path] if path.is_file() else [Path(x) for x in sorted(glob.glob(item))])
        found += [str(x.resolve()) for x in matches if x.suffix == ".root"]
    found = list(dict.fromkeys(found))
    if not found:
        raise ValueError("no ROOT input files found")
    return found


def report_for_root(root_file):
    path = Path(root_file)
    if path.stem.startswith("skim_"):
        report = path.with_name(f"report_{path.stem[len('skim_'):]}.json")
    else:
        report = path.with_name(f"{path.stem}_report.json")
    return report if report.is_file() else None


def aggregate_reports(files):
    totals = {}
    order = []
    for root_file in files:
        report_path = report_for_root(root_file)
        if report_path is None:
            raise FileNotFoundError(f"missing report JSON for {root_file}")
        with report_path.open() as stream:
            report = json.load(stream)
        if not order:
            order = list(report)
        elif list(report) != order:
            raise RuntimeError(f"inconsistent cutflow keys in {report_path}")
        for name, value in report.items():
            passed = value if isinstance(value, (int, float)) else value["pass"]
            totals[name] = totals.get(name, 0) + int(passed)
    return [(name, totals[name]) for name in order]


def reports_from_inputs(items):
    reports = []
    for item in items:
        path = Path(item).expanduser()
        if path.is_dir():
            reports.extend(sorted(path.rglob("report_*.json")))
        elif path.suffix == ".json" and path.is_file():
            reports.append(path)
    reports = list(dict.fromkeys(path.resolve() for path in reports))
    if not reports:
        raise ValueError("no report JSON files found")
    return reports


def aggregate_report_paths(report_paths):
    totals = {}
    order = []
    for report_path in report_paths:
        with report_path.open() as stream:
            report = json.load(stream)
        if not order:
            order = list(report)
        elif list(report) != order:
            raise RuntimeError(f"inconsistent cutflow keys in {report_path}")
        for name, value in report.items():
            passed = value if isinstance(value, (int, float)) else value["pass"]
            totals[name] = totals.get(name, 0) + int(passed)
    return [(name, totals[name]) for name in order]


def make_cutflow_only(args):
    report_counts = aggregate_report_paths(reports_from_inputs(args.inputs))
    if not args.cutflow_only.is_file():
        raise FileNotFoundError(f"tuple does not exist: {args.cutflow_only}")
    df = ROOT.RDataFrame(args.tree, str(args.cutflow_only))
    available = columns(df)
    configured = {
        name: definition
        for section in ("masses_regions", "muons_selection", "jets_selection", "categories")
        for name, definition in SYNC_CONFIG.get(section, {}).items()
    }
    defining = set()

    def ensure_column(node, name):
        if name in available:
            return node
        if name not in configured:
            raise RuntimeError(f"unknown cutflow selection: {name}")
        if name in defining:
            raise RuntimeError(f"cyclic selection dependency involving {name}")
        defining.add(name)
        expression = configured[name]["expression"].format(
            tot_suff="", mu_suff="", jet_suff=""
        )
        for dependency in configured:
            if dependency != name and re.search(rf"\b{re.escape(dependency)}\b", expression):
                node = ensure_column(node, dependency)
        node = node.Define(name, expression)
        available.add(name)
        defining.remove(name)
        return node

    category_config = SYNC_CONFIG.get("categories", {})
    configured_order = [
        name for name in cutflow_steps(args.cutflow_key)
        if name not in category_config or category_config[name].get("store", False)
    ]
    preselection = args.tuple_preselection
    order = ([preselection] if preselection != "1" else []) + [
        name for name in configured_order if name != preselection
    ]
    count_actions = []
    node = df
    for selection in order:
        node = ensure_column(node, selection)
        node = node.Filter(selection, f"cutflow_{selection}")
        count_actions.append((selection, node.Count()))
    total_action = df.Count()
    yield_actions = [
        ((kind, name), df.Filter(name, f"yield_{kind}_{name}").Count())
        for kind, name in stored_category_region_names()
    ]
    ROOT.RDF.RunGraphs([
        *(action for _, action in count_actions), total_action,
        *(action for _, action in yield_actions),
    ])
    selection_counts = [(name, int(action.GetValue())) for name, action in count_actions]
    path = args.cutflow_output or args.cutflow_only.with_name(
        f"{args.cutflow_only.stem}_cutflow.csv"
    )
    write_cutflow(path, report_counts, selection_counts)
    write_selection_yields(
        yields_path_from_cutflow(path), int(total_action.GetValue()),
        [(key, int(action.GetValue())) for key, action in yield_actions],
    )


def cutflow_steps(key):
    if key not in SYNC_CONFIG:
        raise KeyError(f"{SYNC_CONFIG_PATH} has no cutflow list named {key}")
    return SYNC_CONFIG[key]


def write_cutflow(path, report_counts, selection_counts):
    counts = report_counts + selection_counts
    if not counts:
        raise RuntimeError("empty cutflow")
    initial = counts[0][1]
    previous = initial
    rows = []
    for step, (name, passed) in enumerate(counts):
        rows.append({
            "step": step,
            "selection": name,
            "cumulative_pass": passed,
            "rejected_at_step": previous - passed,
            "relative_efficiency": passed / previous if previous else 0.0,
            "cumulative_efficiency": passed / initial if initial else 0.0,
        })
        previous = passed
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[sync] wrote cutflow {path}")


def stored_category_region_names():
    return [
        ("region" if section == "masses_regions" else "category", name)
        for section in ("masses_regions", "categories")
        for name, definition in SYNC_CONFIG.get(section, {}).items()
        if definition.get("store", False)
    ]


def write_selection_yields(path, total, counts):
    rows = [{
        "kind": kind,
        "selection": name,
        "pass": passed,
        "total_events": total,
        "efficiency": passed / total if total else 0.0,
    } for (kind, name), passed in counts]
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(f"[sync] wrote category/region yields {path}")


def yields_path_from_cutflow(path):
    stem = path.stem
    if stem.endswith("_cutflow"):
        stem = stem[:-len("_cutflow")]
    return path.with_name(f"{stem}_categories_regions.csv")


def columns(df):
    return {str(x) for x in df.GetColumnNames()}


def put(df, name, expression):
    return df.Redefine(name, expression) if name in columns(df) else df.Define(name, expression)


def require(df, needed, label):
    missing = sorted(set(needed) - columns(df))
    if missing:
        raise RuntimeError(f"cannot define {label}; missing: {', '.join(missing)}")


VBF_STAGES_HELPER = """
#include <Math/Vector4D.h>
#include <cmath>
namespace sync_vbf {
using P4 = ROOT::Math::LorentzVector<ROOT::Math::PtEtaPhiM4D<double>>;
// Stages of FindVBFJets in the order the C++ selection applies them, so a
// cutflow can attribute the VBF loss to the horn cleaning, the jet pT, the
// dijet mass or the pseudorapidity gap. Stage 3 reproduces HasVBF exactly.
template <typename V, typename B>
bool PairStage(const V &pt, const V &eta, const V &phi, const V &mass,
               const B &outside, int stage) {
  for (size_t i = 0; i < pt.size(); ++i) {
    if (!outside[i]) continue;
    for (size_t j = i + 1; j < pt.size(); ++j) {
      if (!outside[j]) continue;
      if (stage == 0) return true;
      if (pt[i] < 35. || pt[j] < 25.) continue;
      if (stage == 1) return true;
      P4 first(pt[i], eta[i], phi[i], mass[i]);
      P4 second(pt[j], eta[j], phi[j], mass[j]);
      if ((first + second).M() < 400.) continue;
      if (stage == 2) return true;
      if (std::abs(eta[i] - eta[j]) < 2.5) continue;
      return true;
    }
  }
  return false;
}
}
"""


def define_vbf_stages(df):
    """Intermediate VBF requirements, only used as cutflow steps."""
    require(df, ["SelectedJet_pt", "SelectedJet_eta", "SelectedJet_phi",
                 "SelectedJet_mass", "SelectedJet_IsOutsideHorn"], "VBF stages")
    ROOT.gInterpreter.Declare(VBF_STAGES_HELPER)
    arguments = ("SelectedJet_pt, SelectedJet_eta, SelectedJet_phi, "
                 "SelectedJet_mass, SelectedJet_IsOutsideHorn")
    stages = {"vbf_jets_ge2": 0, "vbf_pair_pt": 1, "vbf_pair_mjj": 2,
              "vbf_pair_deta": 3}
    df = put(df, "jets_ge2", "N_SelectedJets >= 2")
    for name, stage in stages.items():
        df = put(df, name, f"sync_vbf::PairStage({arguments}, {stage})")
    return df


def define_leading_vbf_pair(df):
    """Choose the pT-leading pair among those passing mjj/deta thresholds."""
    expression = r"""
    ROOT::VecOps::RVec<int> result{-1, -1};
    for (size_t i = 0; i < SelectedJet_pt.size(); ++i) {
        for (size_t j = i + 1; j < SelectedJet_pt.size(); ++j) {
            SyncP4 ji(SelectedJet_pt[i], SelectedJet_eta[i],
                      SelectedJet_phi[i], SelectedJet_mass[i]);
            SyncP4 jj(SelectedJet_pt[j], SelectedJet_eta[j],
                      SelectedJet_phi[j], SelectedJet_mass[j]);
            if ((ji + jj).M() > 400. &&
                std::abs(SelectedJet_eta[i] - SelectedJet_eta[j]) > 2.5) {
                result[0] = static_cast<int>(i);
                result[1] = static_cast<int>(j);
                return result;
            }
        }
    }
    return result;
    """
    df = put(df, "VBFLeadingPairIdx", expression)
    df = put(df, "HasVBF", "VBFLeadingPairIdx[0] >= 0")
    df = put(df, "VBFJetIdx_1", "VBFLeadingPairIdx[0]")
    df = put(df, "VBFJetIdx_2", "VBFLeadingPairIdx[1]")
    return df


def prepare(df, vbf_pair_strategy="standard"):
    aliases = {"dimuon_mass": "m_mumu", "dimuon_pt": "pt_mumu",
               "dimuon_eta": "eta_mumu", "dimuon_phi": "phi_mumu"}
    available = columns(df)
    require(df, ["m_mumu"], "dimuon mass")
    missing_kinematics = {"pt_mumu", "eta_mumu", "phi_mumu"} - available
    if missing_kinematics:
        require(
            df,
            ["mu1_pt", "mu1_eta", "mu1_phi", "mu1_mass",
             "mu2_pt", "mu2_eta", "mu2_phi", "mu2_mass"],
            "dimuon kinematics",
        )
        ROOT.gInterpreter.Declare(
            "#include <Math/Vector4D.h>\n"
            "using SyncP4 = ROOT::Math::LorentzVector<"
            "ROOT::Math::PtEtaPhiM4D<double>>;"
        )
        df = put(
            df,
            "sync_dimuon_p4",
            "SyncP4(mu1_pt,mu1_eta,mu1_phi,mu1_mass) + "
            "SyncP4(mu2_pt,mu2_eta,mu2_phi,mu2_mass)",
        )
        fallback = {
            "pt_mumu": "static_cast<float>(sync_dimuon_p4.Pt())",
            "eta_mumu": "static_cast<float>(sync_dimuon_p4.Eta())",
            "phi_mumu": "static_cast<float>(sync_dimuon_p4.Phi())",
        }
        for name in sorted(missing_kinematics):
            df = df.Define(name, fallback[name])
    for target, source in aliases.items():
        df = put(df, target, source)

    df = define_vbf_stages(df)

    selection_config = copy.deepcopy(SYNC_CONFIG)
    if vbf_pair_strategy == "leading":
        ROOT.gInterpreter.Declare(
            "#include <Math/Vector4D.h>\n"
            "using SyncP4 = ROOT::Math::LorentzVector<"
            "ROOT::Math::PtEtaPhiM4D<double>>;"
        )
        df = define_leading_vbf_pair(df)
        selection_config["categories"]["VBF_def"]["expression"] = (
            "HasVBF{jet_suff}"
        )

    # Use the same selection builder as prepare_rdf, but skip its expensive
    # weight, correction and DNN setup: a sync tuple only needs the nominal
    # selection columns already supported by the input skim schema.
    df = DefineSelections(df, selection_config)

    # Expose every stored SelectedJet quantity also for the first three jets.
    available = columns(df)
    vectors = sorted(x for x in available if x.startswith("SelectedJet_") and x != "SelectedJet_p4")
    for index, prefix in enumerate(("leadingjet", "subleadingjet", "thirdleadingjet")):
        for source in vectors:
            target = f"{prefix}_{source[len('SelectedJet_') :]}"
            if target not in available:
                df = df.Define(target, f"{source}.size() > {index} ? static_cast<float>({source}.at({index})) : {MISSING}f")
                available.add(target)

    require(df, ["HasVBF", "VBFJetIdx_1", "VBFJetIdx_2", "SelectedJet_pt",
                 "SelectedJet_eta", "SelectedJet_phi", "SelectedJet_mass"], "dijet variables")
    available = columns(df)
    for leg, index_name in ((1, "VBFJetIdx_1"), (2, "VBFJetIdx_2")):
        for source in vectors:
            target = f"vbfjet{leg}_{source[len('SelectedJet_') :]}"
            if target in available:
                continue
            expression = (
                f"HasVBF && {index_name} >= 0 && "
                f"static_cast<size_t>({index_name}) < {source}.size() ? "
                f"static_cast<float>({source}.at({index_name})) : {MISSING}f"
            )
            df = df.Define(target, expression)
            available.add(target)

    ROOT.gInterpreter.Declare("#include <Math/Vector4D.h>\nusing SyncP4 = ROOT::Math::LorentzVector<ROOT::Math::PtEtaPhiM4D<double>>;")
    valid_vbf = "HasVBF && VBFJetIdx_1 >= 0 && VBFJetIdx_2 >= 0 && static_cast<size_t>(VBFJetIdx_1) < SelectedJet_pt.size() && static_cast<size_t>(VBFJetIdx_2) < SelectedJet_pt.size()"
    valid_ls = "SelectedJet_pt.size() >= 2 && SelectedJet_eta.size() >= 2 && SelectedJet_phi.size() >= 2 && SelectedJet_mass.size() >= 2"
    p4 = lambda i: f"SyncP4(SelectedJet_pt.at({i}),SelectedJet_eta.at({i}),SelectedJet_phi.at({i}),SelectedJet_mass.at({i}))"
    df = put(
        df, "sync_dijet_vbf_p4",
        f"{valid_vbf} ? {p4('VBFJetIdx_1')}+{p4('VBFJetIdx_2')} : SyncP4(0.,0.,0.,0.)",
    )
    df = put(
        df, "sync_dijet_ls_p4",
        f"{valid_ls} ? {p4('0')}+{p4('1')} : SyncP4(0.,0.,0.,0.)",
    )
    for name, method in (("mass", "M"), ("pt", "Pt"), ("eta", "Eta"), ("phi", "Phi")):
        df = put(df, f"dijet_vbf_{name}", f"{valid_vbf} ? static_cast<float>(sync_dijet_vbf_p4.{method}()) : {MISSING}f")
        df = put(df, f"dijet_ls_{name}", f"{valid_ls} ? static_cast<float>(sync_dijet_ls_p4.{method}()) : {MISSING}f")
    return df


def selected_columns(df, is_mc):
    available = columns(df)
    selection_sections = (
        "masses_regions", "muons_selection", "jets_selection", "categories"
    )
    configured_selections = {
        name
        for section in selection_sections
        for name in SYNC_CONFIG.get(section, {})
    }
    stored_selections = {
        name
        for section in selection_sections
        for name, definition in SYNC_CONFIG.get(section, {}).items()
        if definition.get("store", False)
    }
    exact = {"run", "luminosityBlock", "event", "HasVBF", "N_SelectedJets",
             "VBFJetIdx_1", "VBFJetIdx_2", *stored_selections,
             "dimuon_mass", "dimuon_pt", "dimuon_eta", "dimuon_phi",
             "dijet_ls_mass", "dijet_ls_pt", "dijet_ls_eta", "dijet_ls_phi",
             "dijet_vbf_mass", "dijet_vbf_pt", "dijet_vbf_eta", "dijet_vbf_phi"}
    prefixes = ("mu1_", "mu2_", "leadingjet_", "subleadingjet_",
                "thirdjet_", "thirdleadingjet_", "vbfjet1_", "vbfjet2_")
    result = {
        x for x in available
        if x in exact or (x.startswith(prefixes) and x not in configured_selections)
    }
    if is_mc:
        result |= {x for x in available if x.startswith("weight_") or x.startswith("weight__")}
        result |= {x for x in ("genWeight", "puWeight", "Generator_weight", "LHEWeight_originalXWGTUP") if x in available}
    return sorted(result)


def main():
    args = arguments()
    if args.threads < 1:
        raise ValueError("--threads must be >= 1")
    ROOT.EnableImplicitMT(args.threads)
    if args.cutflow_only:
        make_cutflow_only(args)
        return
    if args.output is None:
        raise ValueError("--output is required unless --cutflow-only is used")
    if args.output.exists() and not (args.overwrite or args.dry_run):
        raise FileExistsError(f"{args.output} exists; pass --overwrite")
    files = find_files(args.inputs)
    report_counts = [] if args.no_cutflow else aggregate_reports(files)
    print(f"[sync] reading one dataset from {len(files)} file(s)")
    df = prepare(ROOT.RDataFrame(args.tree, files), args.vbf_pair_strategy)
    keep = selected_columns(df, args.mc)
    print(f"[sync] selected {len(keep)} columns" + (" including MC weights" if args.mc else ""))
    if args.dry_run:
        print("\n".join(keep))
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    opts = ROOT.RDF.RSnapshotOptions()
    opts.fMode = "RECREATE"
    opts.fLazy = True
    snapshot = df.Filter(args.selection, "sync selection").Snapshot(
        args.tree, str(args.output), keep, opts
    )
    cut_node = df
    count_actions = []
    for selection in cutflow_steps(args.cutflow_key):
        if selection not in columns(cut_node):
            raise RuntimeError(f"unknown cutflow selection: {selection}")
        cut_node = cut_node.Filter(selection, f"cutflow_{selection}")
        count_actions.append((selection, cut_node.Count()))
    total_action = df.Count()
    yield_actions = [
        ((kind, name), df.Filter(name, f"yield_{kind}_{name}").Count())
        for kind, name in stored_category_region_names()
    ]
    ROOT.RDF.RunGraphs([
        snapshot, *(action for _, action in count_actions), total_action,
        *(action for _, action in yield_actions),
    ])
    print(f"[sync] wrote {args.output}")
    if not args.no_cutflow:
        selection_counts = [(name, int(action.GetValue())) for name, action in count_actions]
        cutflow_path = args.cutflow_output or args.output.with_name(
            f"{args.output.stem}_cutflow.csv"
        )
        write_cutflow(cutflow_path, report_counts, selection_counts)
        write_selection_yields(
            yields_path_from_cutflow(cutflow_path), int(total_action.GetValue()),
            [(key, int(action.GetValue())) for key, action in yield_actions],
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"[ERROR] {error}", file=sys.stderr)
        sys.exit(1)
