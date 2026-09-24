import importlib.util
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("optimize_vbf_cuts.py")
SPEC = importlib.util.spec_from_file_location("optimize_vbf_cuts", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_reverse_cumulative_2d():
    values = np.array([[1.0, 2.0], [3.0, 4.0]])
    expected = np.array([[10.0, 6.0], [7.0, 4.0]])
    np.testing.assert_allclose(MODULE.reverse_cumulative(values), expected)


def test_threshold_histogram_matches_direct_scan():
    thresholds = {
        "mjj": np.array([200.0, 400.0]),
        "detajj": np.array([1.0, 2.5]),
        "jet1_pt": np.array([30.0, 40.0]),
        "jet2_pt": np.array([20.0, 30.0]),
        "ptjj": np.array([0.0, 50.0]),
    }
    arrays = {
        "mjj": np.array([250.0, 450.0, 700.0]),
        "detajj": np.array([1.5, 3.0, 4.0]),
        "jet1_pt": np.array([35.0, 45.0, 80.0]),
        "jet2_pt": np.array([25.0, 35.0, 50.0]),
        "ptjj": np.array([40.0, 70.0, 120.0]),
    }
    weights = np.array([1.0, 2.0, -0.5])
    sumw, sumw2 = MODULE.threshold_histogram(arrays, weights, thresholds)

    for index in np.ndindex(sumw.shape):
        mask = np.ones(len(weights), dtype=bool)
        for axis, variable in enumerate(MODULE.VARIABLES):
            mask &= arrays[variable] >= thresholds[variable][index[axis]]
        np.testing.assert_allclose(sumw[index], weights[mask].sum())
        np.testing.assert_allclose(sumw2[index], np.square(weights[mask]).sum())


def test_significance_rejects_nonpositive_background():
    signal = np.array([2.0, 2.0, -1.0])
    background = np.array([4.0, 0.0, 4.0])
    np.testing.assert_allclose(
        MODULE.significance(signal, background),
        np.array([1.0, 0.0, 0.0]),
    )


def test_jet_category_masks():
    njets = np.array([1, 2, 3, 4])
    np.testing.assert_array_equal(
        MODULE.category_mask(njets, {"min_njets": 2}),
        np.array([False, True, True, True]),
    )
    np.testing.assert_array_equal(
        MODULE.category_mask(njets, {"min_njets": 2, "max_njets": 2}),
        np.array([False, True, False, False]),
    )


def test_best_2d_point():
    score = np.array([[0.1, 0.2], [0.5, 0.3]])
    signal = np.array([[1.0, 2.0], [3.0, 4.0]])
    background = np.array([[4.0, 4.0], [9.0, 16.0]])
    thresholds = {
        "mjj": np.array([400.0, 500.0]),
        "detajj": np.array([2.5, 3.0]),
    }
    best = MODULE.best_2d_point(
        score,
        signal,
        background,
        thresholds,
        {"jet1_pt": 35, "jet2_pt": 25, "ptjj": 0},
    )
    assert best["mjj"] == 500.0
    assert best["detajj"] == 2.5
    assert best["significance"] == 0.5


def test_optimize_variable_subset_holds_other_cuts_fixed():
    thresholds = {
        "mjj": np.array([0.0, 500.0]),
        "detajj": np.array([0.0, 3.0]),
        "jet1_pt": np.array([25.0, 40.0]),
        "jet2_pt": np.array([20.0, 30.0]),
        "ptjj": np.array([0.0, 50.0]),
    }
    shape = (2, 2, 2, 2, 2)
    signal = np.ones(shape)
    background = np.ones(shape)
    signal[1, 0, 0, 0, 0] = 4.0
    signal[1, 1, 1, 1, 1] = 100.0
    totals = {
        "signal": {"sumw": signal, "sumw2": signal},
        "background": {"sumw": background, "sumw2": background},
    }
    result = MODULE.optimize_variable_subset(
        totals,
        thresholds,
        ("mjj",),
        {"mjj": 0, "detajj": 0, "jet1_pt": 25, "jet2_pt": 20, "ptjj": 0},
        0.0,
    )
    assert result["mjj"] == 500.0
    assert result["detajj"] == 0.0
    assert result["jet1_pt"] == 25.0
    assert result["jet2_pt"] == 20.0
    assert result["ptjj"] == 0.0
    assert result["significance"] == 4.0


def test_sampling_stride():
    assert MODULE.sampling_stride(500_000, 1_000_000) == 1
    assert MODULE.sampling_stride(1_000_000, 1_000_000) == 1
    assert MODULE.sampling_stride(1_000_001, 1_000_000) == 2
    assert MODULE.sampling_stride(3_200_000, 1_000_000) == 4


def test_display_edges_respect_requested_plot_range():
    edges = MODULE.display_edges(np.array([0.0, 50.0, 100.0]), lower=0.0, upper=100.0)
    np.testing.assert_allclose(edges, np.array([0.0, 25.0, 75.0, 100.0]))
