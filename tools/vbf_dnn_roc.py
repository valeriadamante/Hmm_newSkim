#!/usr/bin/env python3
"""Run the H->mumu DNN in the VBF signal region and draw its ROC curve."""

import argparse
import os
import sys
import time

import matplotlib.pyplot as plt
import numpy as np
import ROOT
import yaml


ANALYSIS_PATH = os.environ.get(
    "ANALYSIS_PATH", os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
sys.path.insert(0, ANALYSIS_PATH)

from common.add_vars import (  # noqa: E402
    DefineSelections,
    GetAllMuonsObservablesNew,
    SelectedJetObservablesDef,
    SoftJetCollectionCleaningInVBF,
    VBFJetMuonsObservablesDef,
    VBFJetObservablesDef,
)
from common.dnn_application import ApplyDNN  # noqa: E402
from common.utilities import (
    list_root_files,
    initialize_root_runtime,
)


# Declare AnalysisTools.h, which provides ComputeCosThetaPhiCS and the other
# C++ helpers used while constructing the DNN input variables.
initialize_root_runtime()


# VBF signal region: analysis baseline, Higgs mass window and VBF jet cuts.
VBF_SIGNAL_REGION = (
    "baseline && m_mumu > 115 && m_mumu < 135 && HasVBF && "
    "SelectedJet_pt[VBFJetIdx_1] >= 35 && "
    "SelectedJet_pt[VBFJetIdx_2] >= 25"
)

ALL_ERAS = [
    "Run3_2022",
    "Run3_2022EE",
    "Run3_2023",
    "Run3_2023BPix",
    "Run3_2024",
    "Run3_2025",
]


def paths_for_era(paths, era, multiple_eras):
    """Resolve {era} templates or <parent>/<era> input directories."""
    resolved = []
    for path in paths:
        if "{era}" in path:
            resolved.append(path.format(era=era))
        elif multiple_eras and os.path.isdir(os.path.join(path, era)):
            resolved.append(os.path.join(path, era))
        elif multiple_eras:
            raise RuntimeError(
                f"For multiple eras, input {path!r} must contain an {era!r} "
                "subdirectory or use the {era} placeholder"
            )
        else:
            resolved.append(path)
    return resolved


def read_scores(paths, era):
    """Read ROOT skim files, select the VBF SR and return DNN scores."""
    files = []
    for path in paths:
        files.extend(list_root_files(path))
    files = sorted(set(files))
    if not files:
        raise RuntimeError(f"No ROOT files found in: {', '.join(paths)}")

    started = time.perf_counter()
    print(f"  reading {len(files)} ROOT files", flush=True)
    rdf = ROOT.RDataFrame("Events", files)
    rdf = SelectedJetObservablesDef(rdf)
    rdf = VBFJetObservablesDef(rdf)
    rdf = GetAllMuonsObservablesNew(rdf)
    rdf = VBFJetMuonsObservablesDef(rdf)
    rdf = SoftJetCollectionCleaningInVBF(rdf)

    # baseline and the analysis categories are expressions defined at runtime,
    # not persistent branches of the skim.
    selections_path = os.path.join(ANALYSIS_PATH, "config", era, "selections.yaml")
    if not os.path.exists(selections_path):
        raise RuntimeError(f"Selections file does not exist: {selections_path}")
    with open(selections_path) as stream:
        selections = yaml.safe_load(stream)
    rdf = DefineSelections(rdf, selections)

    rdf = rdf.Filter(VBF_SIGNAL_REGION, "VBF signal region")
    rdf = ApplyDNN(rdf, payload_names=["DNN"], era=era, model_set="updated")

    scores = np.asarray(rdf.AsNumpy(["DNN_NNOutput"])["DNN_NNOutput"])
    if scores.size == 0:
        raise RuntimeError(f"No events pass the VBF signal region in: {paths}")
    print(
        f"  selected {scores.size} events in {time.perf_counter() - started:.1f} s",
        flush=True,
    )
    return scores


def roc_curve(signal_scores, background_scores):
    """Compute an unweighted ROC curve without external ML packages."""
    scores = np.concatenate([signal_scores, background_scores])
    labels = np.concatenate(
        [np.ones(signal_scores.size, dtype=int), np.zeros(background_scores.size, dtype=int)]
    )
    order = np.argsort(scores, kind="mergesort")[::-1]
    scores, labels = scores[order], labels[order]

    # Keep only the last event for each distinct threshold.
    threshold_indices = np.r_[np.flatnonzero(np.diff(scores)), scores.size - 1]
    true_positive = np.cumsum(labels)[threshold_indices]
    false_positive = (threshold_indices + 1) - true_positive
    tpr = np.r_[0.0, true_positive / signal_scores.size, 1.0]
    fpr = np.r_[0.0, false_positive / background_scores.size, 1.0]
    auc = np.trapz(tpr, fpr)
    return fpr, tpr, auc


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--era", nargs="+", required=True,
        help="One or more eras, or 'all' for Run3_2022 through Run3_2025",
    )
    parser.add_argument(
        "--signal", nargs="+", required=True,
        help="VBFHmm and ggHmm ROOT files or directories",
    )
    parser.add_argument(
        "--background", nargs="+", required=True,
        help="DY105_160 and EWK_105_160 ROOT files or directories",
    )
    parser.add_argument("--output", default="vbf_dnn_roc.png")
    parser.add_argument(
        "--threads", type=int, default=4,
        help="ROOT input/selection threads (default: 4)",
    )
    args = parser.parse_args()

    if args.threads < 1:
        parser.error("--threads must be at least 1")
    if args.threads > 1:
        ROOT.EnableImplicitMT(args.threads)

    eras = ALL_ERAS if args.era == ["all"] else args.era
    unknown_eras = sorted(set(eras) - set(ALL_ERAS))
    if unknown_eras:
        parser.error(f"unknown era(s): {', '.join(unknown_eras)}")

    print(f"VBF signal region: {VBF_SIGNAL_REGION}")
    signal_by_era = []
    background_by_era = []
    for era in eras:
        print(f"\nProcessing {era}")
        signal = read_scores(
            paths_for_era(args.signal, era, len(eras) > 1), era
        )
        background = read_scores(
            paths_for_era(args.background, era, len(eras) > 1), era
        )
        signal_by_era.append(signal)
        background_by_era.append(background)
        print(f"  signal events: {signal.size}")
        print(f"  background events: {background.size}")

    signal_scores = np.concatenate(signal_by_era)
    background_scores = np.concatenate(background_by_era)
    fpr, tpr, auc = roc_curve(signal_scores, background_scores)

    fig, ax = plt.subplots(figsize=(7, 7))
    ax.plot(fpr, tpr, lw=2, label=f"DNN (AUC = {auc:.4f})")
    ax.plot([0, 1], [0, 1], "--", color="grey", label="Random classifier")
    ax.set(xlabel="Background efficiency", ylabel="Signal efficiency", xlim=(0, 1), ylim=(0, 1))
    ax.grid(alpha=0.25)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(args.output, dpi=160)
    plt.close(fig)

    print(f"Signal events:     {signal_scores.size}")
    print(f"Background events: {background_scores.size}")
    print(f"AUC:               {auc:.6f}")
    print(f"ROC saved to:      {args.output}")


if __name__ == "__main__":
    main()
