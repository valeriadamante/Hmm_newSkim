"""Numerical skim selection regressions; run after sourcing env.sh."""
from pathlib import Path
import unittest

import ROOT
import yaml

from analysis.muons import GetPtConfigurations, ProcessMuonVariables, DefineMuonSelection
from common.jet_horn_policy import horn_mitigation_enabled

REPO = Path(__file__).resolve().parents[2]


class SkimMuonSelectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        ROOT.gInterpreter.Declare(f'#include "{REPO / "analysis/AnalysisTools.h"}"')

    def selected(self, raw='RVecF{21.f, 11.f}', corrected='RVecF{22.f, 28.f}',
                 charges='RVecI{1, -1}', matched='RVecI{-1, 0}', gen_inputs=None):
        df = ROOT.RDataFrame(1)
        inputs = {
            'Muon_eta': 'RVecF{0.2f, -0.2f}', 'Muon_phi': 'RVecF{0.f, 3.f}',
            'Muon_mass': 'RVecF{0.105f, 0.105f}', 'Muon_charge': charges,
            'Muon_mediumId': 'RVecI{1, 1}', 'Muon_looseId': 'RVecI{1, 1}',
            'Muon_tightId': 'RVecI{1, 1}', 'Muon_pfIsoId': 'RVecI{4, 4}',
            'Muon_pt_err': 'RVecF{0.1f, 0.1f}',
            'Muon_TriggerMatchingIdx_singleMu': matched,
            'Event_HasTriggerMatching_singleMu': 'true', 'HLT_IsoMu24': 'true',
        }
        inputs.update(gen_inputs or {})
        for name, expression in inputs.items():
            df = df.Define(name, expression)
        for pt in GetPtConfigurations(False)[0]:
            df = df.Define(pt, raw if pt == 'Muon_pt_raw_noCorr' else corrected)
            df = df.Define(pt.replace('pt', 'p4'), f'GetP4({pt}, Muon_eta, Muon_phi, Muon_mass)')
        df, saved = ProcessMuonVariables(df, ['Muon_charge', 'Muon_mediumId', 'Muon_looseId',
                                         'Muon_tightId', 'Muon_pfIsoId'],
                                    'FSR_corr', {'singleMu': {}}, False, 10., 0., 1000., {})
        self.assertTrue({'mu1_GenMatched', 'mu2_GenMatched'} <= set(saved))
        return df

    def test_raw_preselection_and_corrected_order_and_flags(self):
        df = self.selected()
        cfg = yaml.safe_load((REPO / 'config/Run3_2024/selections.yaml').read_text())
        df, saved = DefineMuonSelection(df, cfg, False, {})
        self.assertEqual(df.Count().GetValue(), 1)
        self.assertEqual(df.Max('mu1_idx').GetValue(), 1)
        self.assertEqual(df.Filter('mu_pt_sel && mu_pt_trg_sel && muon_pre_sel_check').Count().GetValue(), 1)
        self.assertTrue({'mu1_pt_g26', 'mu2_pt_g20', 'mu_pt_sel', 'mu_pt_trg_sel'} <= set(saved))

    def test_os_is_only_a_saved_flag(self):
        cfg = yaml.safe_load((REPO / 'config/Run3_2024/selections.yaml').read_text())
        for charges, expected in [('RVecI{1, 1}', 0), ('RVecI{1, -1}', 1)]:
            df, saved = DefineMuonSelection(self.selected(charges=charges), cfg, False, {})
            self.assertIn('muons_OS', saved)
            self.assertEqual(df.Count().GetValue(), 1)
            self.assertEqual(df.Filter('muons_OS').Count().GetValue(), expected)

    def test_gen_matching_follows_corrected_order(self):
        df = self.selected(gen_inputs={'Muon_genPartIdx': 'RVecI{-1, 0}',
                                       'GenPart_pdgId': 'RVecI{-13}'})
        self.assertEqual(df.Filter('mu1_GenMatched && !mu2_GenMatched').Count().GetValue(), 1)

    def test_gen_matching_rejects_nonmuon_and_invalid_index(self):
        df = self.selected(gen_inputs={'Muon_genPartIdx': 'RVecI{5, 0}',
                                       'GenPart_pdgId': 'RVecI{22}'})
        self.assertEqual(df.Filter('!mu1_GenMatched && !mu2_GenMatched').Count().GetValue(), 1)

    def test_gen_matching_without_gen_branches(self):
        self.assertEqual(self.selected().Filter('!mu1_GenMatched && !mu2_GenMatched').Count().GetValue(), 1)

    def test_gen_matching_flavour_fallback_includes_nonprompt(self):
        df = self.selected(gen_inputs={'Muon_genPartFlav': 'RVecI{0, 5}'})
        self.assertEqual(df.Filter('mu1_GenMatched && !mu2_GenMatched').Count().GetValue(), 1)

    def test_gen_matching_index_without_gen_collection(self):
        df = self.selected(gen_inputs={'Muon_genPartIdx': 'RVecI{-1, 0}'})
        self.assertEqual(df.Filter('mu1_GenMatched && !mu2_GenMatched').Count().GetValue(), 1)

    def test_raw_threshold_not_corrected_threshold(self):
        self.assertEqual(self.selected(raw='RVecF{21.f, 10.f}').Count().GetValue(), 0)

    def test_matching_must_belong_to_pair(self):
        self.assertEqual(self.selected(matched='RVecI{-1, -1}').Count().GetValue(), 0)

    def test_analysis_pt_cut_is_flag_not_skim_filter(self):
        df = self.selected(corrected='RVecF{19.f, 28.f}')
        cfg = yaml.safe_load((REPO / 'config/Run3_2024/selections.yaml').read_text())
        df, _ = DefineMuonSelection(df, cfg, False, {})
        self.assertEqual(df.Count().GetValue(), 1)
        self.assertEqual(df.Filter('mu_pt_sel').Count().GetValue(), 0)

    def test_2024_horn_toggle(self):
        self.assertFalse(horn_mitigation_enabled('Run3_2024', {'jet_horn_veto_expr': 'false'}))
        self.assertTrue(horn_mitigation_enabled('Run3_2024', {'jet_horn_veto_expr': 'abs(eta) > 2.5'}))


if __name__ == '__main__':
    unittest.main()
