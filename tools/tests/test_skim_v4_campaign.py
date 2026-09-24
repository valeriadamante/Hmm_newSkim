import ast
from pathlib import Path
import shlex
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[2]


class SkimV4CampaignTest(unittest.TestCase):
    def commands(self, *args):
        result = subprocess.run(['bash', 'campaigns/run3_skim_v4.sh', 'plan', *args],
                                cwd=ROOT, check=True, capture_output=True, text=True)
        return [shlex.split(line) for line in result.stdout.splitlines()]

    def test_all_eras_and_two_horn_versions(self):
        commands = self.commands()
        self.assertEqual(len(commands), 9)
        destinations = set()
        for cmd in commands:
            value = lambda key: cmd[cmd.index(key) + 1]
            era = value('--era')
            horn = value('--jet-horn-veto')
            self.assertEqual(horn == 'configured', era not in ('Run3_2025', 'Run3_2026'))
            self.assertIn('skim_v4', value('--output-dir'))
            self.assertIn('skim_v4', value('--state-dir'))
            destinations.add((value('--output-dir'), era))
        self.assertEqual(len(destinations), 9)

    def test_limited_run_and_dataset_are_isolated(self):
        commands = self.commands('--era', '2026', '--variant', 'without', '--n-events', '1000',
                                 '--dataset', 'DY', '--max-submit-jobs', '1')
        self.assertEqual(len(commands), 1)
        cmd = commands[0]
        self.assertIn('skim_v4_test1000_noHornVeto', cmd[cmd.index('--output-dir') + 1])
        self.assertEqual(cmd[cmd.index('--n-events') + 1], '1000')
        self.assertEqual(cmd[cmd.index('--dataset') + 1], 'DY')

    def test_worker_forwards_horn_and_event_limit(self):
        import os
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            (work / 'env.sh').write_text(':\n')
            python = work / 'python3'
            python.write_text('#!/bin/bash\nprintf "%s\\n" "$@"\n')
            python.chmod(0o755)
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'])
            result = subprocess.run(['bash', str(ROOT / 'htcondor/run_skim.sh'),
                '/tmp/proxy', tmp, 'Run3_2026', 'input.root', 'DY', 'output.root',
                'report.json', 'CMSSW_15_0_2', 'with', '1000'],
                env=env, check=True, capture_output=True, text=True)
            args = result.stdout.splitlines()
            self.assertEqual(args[args.index('--jet-horn-veto') + 1], 'with')
            self.assertEqual(args[args.index('--n-events') + 1], '1000')

    def test_output_override_is_honored(self):
        tree = ast.parse((ROOT / 'htcondor/condorsubmit.py').read_text())
        stmt = next(n for n in tree.body if isinstance(n, ast.Assign) and
                    any(isinstance(t, ast.Name) and t.id == 'output_dir' for t in n.targets))
        from types import SimpleNamespace
        for override, expected in [('/tmp/v4', '/tmp/v4'), (None, '/tmp/v3')]:
            ns = {'args': SimpleNamespace(output_dir=override), 'skim_config': {'output_dir': '/tmp/v3'}}
            exec(compile(ast.Module(body=[stmt], type_ignores=[]), '<output override>', 'exec'), ns)
            self.assertEqual(ns['output_dir'], expected)

    def test_explicit_dataset_excludes_configured_processes(self):
        tree = ast.parse((ROOT / 'htcondor/condorsubmit.py').read_text())
        start = next(i for i,n in enumerate(tree.body) if isinstance(n,ast.Assign) and
                     any(isinstance(t,ast.Name) and t.id=='all_datasets' for t in n.targets))
        from types import SimpleNamespace
        ns={'args':SimpleNamespace(datasets=['DY']), 'datasets_whitelist':[],
            'process_to_select':['TT'], 'processes_cfg':{'TT':{'datasets':['TT']}}}
        exec(compile(ast.Module(body=tree.body[start:start+3],type_ignores=[]),'<dataset selection>','exec'),ns)
        self.assertEqual(ns['all_datasets'],['DY'])


if __name__ == '__main__':
    unittest.main()
