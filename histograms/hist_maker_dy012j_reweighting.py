#!/usr/bin/env python3
"""Produce the Z-sideband inputs for the dy012j reweight derivation.

Uses hist_maker's input/output CLI. Stage variables, categories and weight
switches are fixed here so later corrections cannot contaminate the fit.
"""
import os
import sys

sys.path.append(os.environ["ANALYSIS_PATH"])
from histograms.hist_maker import main

STAGE_SETTINGS = {'variables': ['m_mumu',
               'eta_signed_vs_pt_leadingjet',
               'eta_signed_vs_pt_subleadingjet',
               'eta_signed_vs_pt_vbfjet1'],
 'categories': ['ggF', 'VBF', 'ggF_0J', 'ggF_1J', 'ggF_ge2J'],
 'custom_weights': False,
 'dy_jet_component_reweight': False,
 'dy_ptll_reweight': False,
 'dy_njets_reweight': False,
 'dy_jet_components': True,
 'all_mc_jet_components': True,
 'mass_regions': ['Z_sideband'],
 'systematics': ['Central'],
 'derive_jet_component_weights': False,
 'vbf_eta_regions': False}

if __name__ == "__main__":
    main(stage_settings=STAGE_SETTINGS)
