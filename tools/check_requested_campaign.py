#!/usr/bin/env python3
"""Check configured dataset outputs, including failed-chunk markers (read only)."""
import argparse
from pathlib import Path
import sys
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
from tools.histogram_completeness import datasets_for_histogram_groups

p = argparse.ArgumentParser()
p.add_argument('folder', type=Path)
p.add_argument('--era', required=True)
p.add_argument('--groups', required=True)
p.add_argument('--root-check', action='store_true', help='Also open every ROOT file with PyROOT')
a = p.parse_args()
era = a.era if a.era.startswith('Run3_') else 'Run3_' + a.era
samples = yaml.safe_load((REPO / 'config' / era / 'samples.yaml').read_text())
processes = yaml.safe_load((REPO / 'config' / era / 'process_names.yaml').read_text())
expected = []
for group in a.groups.split(','):
    if group == 'data':
        entry = processes['Data_Muon']
        expected.extend(entry.get('datasets', []) + entry.get('sub_processes', []))
    elif group == 'EWK_105_160':
        expected.extend(x for x in ('EWK_2Mu2J_MLL_105to160_herwig', 'EWK_2Mu2J_MLL_105to160_pythia') if x in samples)
    else:
        # The shared helper still includes FlashSim in signals; the current
        # submission wrapper reserves it for the separate FlashSim group.
        selected = datasets_for_histogram_groups(REPO, era, [group])
        if group == 'signals':
            selected = [x for x in selected if x != 'VBFHto2Mu_m125_Flashsim']
        expected.extend(selected)
expected = sorted(set(expected))
if not expected:
    p.error('Empty dataset selection')
if a.root_check:
    import ROOT
    from common.utilities import histogram_complete
bad = []
era_dir_exists = (a.folder / era).is_dir()
for dataset in expected:
    path = a.folder / era / (dataset + '.root')
    reason = None
    if not era_dir_exists or not path.is_file() or path.stat().st_size == 0:
        reason = 'MISSING/EMPTY'
    elif Path(str(path) + '.failed_chunks.txt').exists():
        reason = 'FAILED_CHUNKS'
    elif a.root_check and not histogram_complete(path):
        reason = 'INVALID_ROOT'
    if reason:
        bad.append((dataset, reason))
print(f'{a.folder}/{era}: expected={len(expected)} present={len(expected)-len(bad)} incomplete={len(bad)}', flush=True)
for dataset, reason in bad:
    print(f'  {reason} {dataset}')
print('Validation: ' + ('ROOT readability + file presence' if a.root_check else 'file presence/size only; histogram contents not validated'))
sys.exit(bool(bad))
