# DNN performance tools

This directory is the public entry point for DNN validation and performance
studies.  Histogram production itself (including sideband dimuon-mass shifts)
lives in `histograms/dnn_histogram_production.py` and is called by
`histograms/hist_maker.py`.

Available commands:

```bash
python3 dnn_performance/check_model_inputs.py --help
python3 dnn_performance/compare_performance.py --help
python3 dnn_performance/optimize_binning.py --help
python3 dnn_performance/rebin_histograms.py --help
python3 dnn_performance/roc_from_skims.py --help
```

`compare_performance.py` works on produced histograms, so it always compares
weighted yields; use it to compare two campaigns, for example with and without
the DY reweights.  `roc_from_skims.py` reads the skims through
`common.prepare_rdf` and returns the weighted and the unweighted ROC from one
event loop, which is the comparison histograms cannot give.  It supersedes
`tools/vbf_dnn_roc.py`, which is unweighted only and rebuilds the VBF signal
region by hand instead of using the era selections.

Signal and background composition for all of these comes from
`config/dnn_studies.yaml`.  The whole chain from skim_v4 to `results/skim_v4/`
is driven by `campaigns/dnn_studies_skim_v4.sh` and documented in
`docs/REPRODUCE_RESULTS_SKIM_V4.md`.

The corresponding `tools/*.py` files remain compatibility entry points for
existing campaigns and tests.
