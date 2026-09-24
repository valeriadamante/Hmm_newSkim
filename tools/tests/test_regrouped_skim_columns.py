import unittest
from unittest.mock import patch

from analysis.jets import ProcessAllJetVariables, SelectJetVars, SelectVBFJets
from common.jet_variation_suffixes import jet_variation_suffixes
from corrections.jetVetoMap import ApplyJetVetoMap


class RecordingFrame:
    def __init__(self, columns):
        self.columns = dict.fromkeys(columns, '')

    def GetColumnNames(self):
        return list(self.columns)

    def Define(self, name, expression):
        self.columns[name] = expression
        return self

    Redefine = Define


class RegroupedSkimColumnsTest(unittest.TestCase):
    def test_regrouped_columns_reach_snapshot_list(self):
        cfg = {'scales': ['up', 'down'], 'systematics': {
            'JER': {'jet_suffix': '_JER{scale}'},
            'JES_Total': {'jet_suffix': '_JESTotal{scale}'},
        }}
        for year in ('2022', '2022EE', '2023', '2023BPix', '2024', '2025', '2026'):
            suffixes = [f'_JESRegrouped_BBEC1_{year}{scale}' for scale in ('up', 'down')]
            df = RecordingFrame(['Jet_p4', 'Jet_p4_JERup', 'Jet_p4_JERdown',
                'Jet_p4_JESTotalup', 'Jet_p4_JESTotaldown', 'Jet_btagPNetB'] +
                ['Jet_p4' + suffix for suffix in suffixes])
            self.assertEqual(jet_variation_suffixes(df, False, cfg), [''])
            args = (['Jet_btagPNetB'], {}, 'PNet', {'L': 0.1, 'M': 0.3}, True, cfg)
            df, saved = ProcessAllJetVariables(df, *args)
            with patch('corrections.jetVetoMap.InitializeVetoMap'):
                df, veto = ApplyJetVetoMap(df, {}, '', False, False, False, True, cfg)
            df, selected = SelectJetVars(df, *args)
            df, vbf = SelectVBFJets(df, True, cfg)
            saved += veto + selected + vbf
            for suffix in suffixes:
                for prefix in ('Jet_pt', 'Jet_mass', 'Jet_vetoMap', 'SelectedJet_pt', 'VBFJetIdx_1'):
                    self.assertIn(prefix + suffix, saved)
            self.assertEqual(len(jet_variation_suffixes(df, True, cfg)), 7)


if __name__ == '__main__':
    unittest.main()
