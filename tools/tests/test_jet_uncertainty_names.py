import re
import unittest
from pathlib import Path
from unittest.mock import patch

from corrections import jets


class RecordingFrame:
    def __init__(self):
        self.columns = {}

    def Define(self, name, expression):
        if name in self.columns:
            raise AssertionError(f'Duplicate column: {name}')
        self.columns[name] = expression
        return self


class JetUncertaintyNamesTest(unittest.TestCase):
    def test_variations_match_provider_for_all_eras_and_modes(self):
        header = Path(jets.__file__).with_suffix('.h').read_text()
        eras = {
            '2022_Summer22': '2022', '2022_Summer22EE': '2022EE',
            '2023_Summer23': '2023', '2023_Summer23BPix': '2023BPix',
            '2024_Summer24': '2024', '2025_Summer24': '2025',
            '2026_Summer24': '2026',
        }
        for period, year in eras.items():
            for regrouped in (False, True):
                with self.subTest(period=period, regrouped=regrouped):
                    state = dict(jets._jet_correction_state, initialized=False)
                    with patch.object(jets, '_jet_correction_state', state), \
                         patch.object(jets.ROOT.gInterpreter, 'Declare'), \
                         patch.object(jets.ROOT.gInterpreter, 'ProcessLine'):
                        jets.initialize_jet_corrections(period, False, 'DY', regrouped)
                        df = jets.define_jet_p4_variations(RecordingFrame(), True, True, True)
                        map_name = 'unc_map_regrouped' if regrouped else 'unc_map_total'
                        body = header.split(map_name + ' = {', 1)[1].split('};', 1)[0]
                        available = set(re.findall(r'UncSource::(\w+)', body)) | {'Central', 'JER'}
                        for name, expression in df.columns.items():
                            self.assertNotIn('{year}', name)
                            match = re.search(r'UncSource::(\w+)', expression)
                            if match:
                                self.assertIn(match.group(1), available)
                        self.assertIn('Jet_p4_JESTotalup', df.columns)
                        self.assertIn('Jet_p4_JERup', df.columns)
                        self.assertNotIn('Jet_p4_JESJERup', df.columns)
                        self.assertIn('UncSource::Total', df.columns['Jet_p4_JESTotalup'])
                        if regrouped:
                            column = df.columns[f'Jet_p4_JESRegrouped_BBEC1_{year}up']
                            self.assertIn('UncSource::BBEC1_year', column)
                            self.assertIn('UncSource::RelativeBal', df.columns['Jet_p4_JESRegrouped_RelativeBalup'])
                        else:
                            self.assertEqual({name for name in df.columns if name.startswith('Jet_p4')},
                                             {'Jet_p4', 'Jet_p4_shifted_map', 'Jet_p4_JERup', 'Jet_p4_JERdown',
                                              'Jet_p4_JESTotalup', 'Jet_p4_JESTotaldown'})
                            self.assertIn('seed_jersmearing', df.columns)

    def test_horn_mitigation_reaches_cpp_for_both_late_eras(self):
        for period in ('2025_Summer24', '2026_Summer24'):
            for enabled in (False, True):
                state = dict(jets._jet_correction_state, initialized=True,
                             is_data=False, period=period, use_regrouped=False)
                with patch.object(jets, '_jet_correction_state', state):
                    df = jets.define_jet_p4_variations(
                        RecordingFrame(), False, True, True,
                        apply_horn_mitigation=enabled)
                expression = df.columns['Jet_p4_shifted_map']
                self.assertRegex(expression, r'Jet_genJetIdx,\s*' + str(enabled).lower() + r'\s*\)')

    def test_aliases_and_unknown_source(self):
        for alias in ('Total', 'JESTotal'):
            self.assertEqual(jets._jet_uncertainty_enum(alias, '2022_Summer22'), 'Total')
        self.assertEqual(jets._jet_uncertainty_enum('Regrouped_HF_{year}', '2023_Summer23BPix'), 'HF_year')
        with self.assertRaises(KeyError):
            jets._jet_uncertainty_enum('Unknown', '2024_Summer24')


if __name__ == '__main__':
    unittest.main()
