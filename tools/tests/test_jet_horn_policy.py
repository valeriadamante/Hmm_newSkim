from pathlib import Path
import unittest
import yaml

from common.jet_horn_policy import horn_mitigation_enabled


class JetHornPolicyTest(unittest.TestCase):
    def test_configured_and_disabled_veto(self):
        repo = Path(__file__).resolve().parents[2]
        for era in ('2022', '2022EE', '2023', '2023BPix', '2024', '2025', '2026'):
            with self.subTest(era=era):
                config = yaml.safe_load((repo / 'config' / ('Run3_' + era) / 'selections.yaml').read_text())
                self.assertTrue(horn_mitigation_enabled('Run3_' + era, config))
                for disabled in ('false', '(abs(v_ops::eta(Jet_p4)) < 0)', '( abs(v_ops::eta(Jet_p4) ) <0 )'):
                    self.assertEqual(horn_mitigation_enabled('Run3_' + era, {'jet_horn_veto_expr': disabled}),
                                     era not in ('2025', '2026'))
        veto = {'jet_horn_veto_expr': '(abs(v_ops::eta(Jet_p4)) >= 2.5 && v_ops::pt(Jet_p4) < 50)'}
        self.assertTrue(horn_mitigation_enabled('Run3_2026', veto))


def test_configured_jet_thresholds_and_overrides():
    from common.jet_horn_policy import configure_horn_veto
    repo = Path(__file__).resolve().parents[2]
    for era in ('2022', '2022EE', '2023', '2023BPix', '2024', '2025', '2026'):
        selections = yaml.safe_load((repo / 'config' / ('Run3_' + era) / 'selections.yaml').read_text())
        for mode in ('configured', 'with', 'without'):
            effective = dict(selections)
            configure_horn_veto(effective, 'Run3_' + era, mode)
            expression = effective['jet_horn_veto_expr'].replace('v_ops::eta(Jet_p4)', 'eta').replace('v_ops::pt(Jet_p4)', 'pt').replace('&&', ' and ')
            for eta in (2.1, 2.49, 2.6, 2.99, 3.1, 4.7):
                for pt in (29., 49.9, 50., 50.1, 60.):
                    expected = mode != 'without' and eta >= 2.5 and pt <= 50 and (era.startswith(('2022', '2023')) or eta < 3)
                    for signed_eta in (eta, -eta):
                        assert bool(eval(expression, {'__builtins__': {}, 'abs': abs}, {'eta': signed_eta, 'pt': pt})) == expected, (era, mode, signed_eta, pt)
