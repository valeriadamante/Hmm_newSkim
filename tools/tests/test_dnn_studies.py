import importlib.util
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from common.dnn_studies import (  # noqa: E402
    background_processes,
    binning_constraints,
    exclude_patterns,
    object_path,
    signal_processes,
)

SCRIPT = REPO / "tools" / "dnn_roc_from_skims.py"
SPEC = importlib.util.spec_from_file_location("dnn_roc_from_skims", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_configuration_has_no_double_counted_background():
    background = background_processes()
    assert len(background) == len(set(background))
    # The inclusive samples and the alternative generators overlap with the
    # 105-160 samples in the signal region and must stay out of the sum.
    for forbidden in ("DY", "EWK", "EWK_2Mu2J_MLL_105to160_pythia", "DYto2Mu_minnlo"):
        assert forbidden not in background
    # Jet components are subsets of their parent process.
    assert not [name for name in background if "_0J_" in name or "_2J_" in name]
    assert object_path() == "Signal_Fit_VBF/DNN_NNOutput"
    assert signal_processes("powheg") == ["GluGluHto2Mu", "VBFHto2Mu_M125_powheg"]
    assert "*Hto2Mu*" in exclude_patterns()
    assert binning_constraints()["min_background"] > 0


def test_weighted_and_unweighted_roc_differ_only_through_the_weights():
    signal = np.array([0.9, 0.8, 0.7, 0.2])
    background = np.array([0.6, 0.4, 0.3, 0.1])

    unweighted = MODULE.roc_from_scores(
        signal, np.ones(4), background, np.ones(4)
    )
    uniform = MODULE.roc_from_scores(
        signal, np.full(4, 3.0), background, np.full(4, 3.0)
    )
    # A common weight rescales the yields but not the shape of the curve.
    assert uniform["auc"] == unweighted["auc"]
    assert uniform["signal_yield"] == 12.0

    # Down-weighting the well-classified signal events degrades the weighted AUC.
    reweighted = MODULE.roc_from_scores(
        signal, np.array([0.1, 0.1, 0.1, 10.0]), background, np.ones(4)
    )
    assert reweighted["auc"] < unweighted["auc"]


def test_perfect_and_random_separation():
    perfect = MODULE.roc_from_scores(
        np.array([0.9, 0.8]), np.ones(2), np.array([0.2, 0.1]), np.ones(2)
    )
    assert perfect["auc"] == 1.0
    assert perfect["signal_efficiency_at_best"] == 1.0
    assert perfect["background_efficiency_at_best"] == 0.0


def test_thinning_preserves_endpoints_and_the_working_point():
    rng = np.random.default_rng(1234)
    signal = rng.normal(0.7, 0.15, 20000)
    background = rng.normal(0.3, 0.15, 40000)
    full = MODULE.roc_from_scores(
        signal, np.full(signal.size, 0.01), background, np.full(background.size, 0.05)
    )
    thin = MODULE.thinned(full, max_points=500)

    assert thin["curve_points"] <= 502
    assert len(thin["thresholds"]) == thin["curve_points"]
    # tpr/fpr carry the extra leading zero point.
    assert len(thin["tpr"]) == thin["curve_points"] + 1
    assert thin["thresholds"][0] == full["thresholds"][0]
    assert thin["thresholds"][-1] == full["thresholds"][-1]
    assert max(thin["significance"]) == max(full["significance"])
    for key in ("auc", "best_threshold", "best_significance"):
        assert thin[key] == full[key]


def test_compact_drops_only_the_curve_arrays():
    result = MODULE.roc_from_scores(
        np.array([0.9, 0.1]), np.ones(2), np.array([0.5, 0.2]), np.ones(2)
    )
    summary = MODULE.compact(result)
    assert set(MODULE.CURVE_KEYS).isdisjoint(summary)
    assert summary["auc"] == result["auc"]
