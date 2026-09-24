#!/usr/bin/env python3
"""Aggrega tutto quello che e' pronto, famiglia per famiglia.

`hadd --mode both` chiama prima un check su TUTTE le famiglie selezionate e si
ferma se una sola e' incompleta: con 21 famiglie su 22 non aggrega niente.
Qui si guarda famiglia per famiglia, si aggregano quelle complete e si lancia
merge-syst solo dove Central piu' tutte le famiglie sono aggregate -- che e' la
condizione che merge-syst pretende davvero.

    python3 campaigns/hadd_what_is_ready.py --dry-run
    python3 campaigns/hadd_what_is_ready.py --campaign all_variables
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / 'campaigns'))
os.chdir(REPO)
_ARGV = list(sys.argv)
sys.argv = [sys.argv[0]]
import workflow as W  # noqa: E402
sys.argv = _ARGV

V4_IN = '/eos/cms/store/group/phys_higgs/cmshmm/vdamante/skim_v4'
V4_MAN = '/eos/user/v/vdamante/H_mumu/manifests_skim_v4'
POST = Path('/eos/user/v/vdamante/H_mumu/skim_v4/post_dy')
DNN_REGIONS = 'Z_sideband,Signal_Fit,H_sideband,Signal_ext,mass_inclusive'
ERAS = ['2022', '2022EE', '2023', '2023BPix', '2024', '2025', '2026']

# (nome, script, config, output, opzioni extra per il runner, ha sistematiche)
CAMPAIGNS = [
    ('all_variables', 'campaigns/all_variables.sh', 'config/campaigns/all_variables.sh',
     POST / 'all_variables', [], True),
    ('dnn_vbf_weighted', 'campaigns/dnn_vbf_signal.sh', 'config/campaigns/dnn_vbf_signal_sep03.sh',
     POST / 'dnn_vbf_weighted',
     ['--regions', DNN_REGIONS, '--categories', 'VBF', '--threads', '1'], True),
    ('dnn_vbf_dy_unweighted', 'campaigns/dnn_vbf_signal.sh', 'config/campaigns/dnn_vbf_signal_sep03.sh',
     POST / 'dnn_vbf_dy_unweighted',
     ['--regions', DNN_REGIONS, '--categories', 'VBF', '--threads', '1'], False),
    ('vbf_eta_regions', 'campaigns/vbf_eta_regions.sh', 'config/campaigns/vbf_eta_regions.sh',
     POST / 'vbf_eta_regions', [], False),
    ('dnn_vbf_eta_regions', 'campaigns/dnn_vbf_eta_regions.sh', 'config/campaigns/dnn_vbf_eta_regions.sh',
     POST / 'dnn_vbf_eta_regions', [], False),
]


def campaign_object(config, root, extra):
    c = W.load_campaign(config)
    c.families = [p for f in c.families for p in (W.JES_REGROUPED if f == 'JES_Total' else [f])]
    c = dataclasses.replace(c, root=Path(root))
    if '--regions' in extra:
        c = dataclasses.replace(c, regions=extra[extra.index('--regions') + 1].split(','))
    if '--categories' in extra:
        c = dataclasses.replace(c, categories=extra[extra.index('--categories') + 1].split(','))
    return c


def complete(products):
    return bool(products) and all(p.is_file() and p.stat().st_size > 0 for p in products)


def run(cmd, dry):
    print('  $ ' + ' '.join(str(x) for x in cmd), flush=True)
    if dry:
        return 0
    return subprocess.run(cmd).returncode


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--eras', default=','.join(ERAS))
    p.add_argument('--campaign', action='append')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--no-merge-syst', action='store_true')
    args = p.parse_args()
    eras = [e.strip() for e in args.eras.split(',') if e.strip()]

    for name, script, config, root, extra, has_syst in CAMPAIGNS:
        if args.campaign and name not in args.campaign:
            continue
        c = campaign_object(config, root, extra)
        families = ['Central'] + (list(c.families) if has_syst else [])
        print(f'\n{"="*72}\n{name}\n{"="*72}')
        for era in eras:
            ready, missing = [], []
            for fam in families:
                try:
                    ok = complete(W.raw_products(c, era, fam))
                except Exception:
                    ok = False
                (ready if ok else missing).append(fam)
            if not ready:
                print(f'  Run3_{era:<10} niente di pronto')
                continue
            print(f'  Run3_{era:<10} {len(ready)}/{len(families)} famiglie pronte'
                  + (f' (mancano {", ".join(missing[:4])}{"..." if len(missing) > 4 else ""})' if missing else ''))
            cmd = ['bash', script, 'hadd', '--mode', 'both' if has_syst else 'central',
                   '--eras', era, '--check-level', 'files', '--missing-only']
            # --families vuoto farebbe morire argparse come e' successo con
            # --categories: si passa solo se c'e' davvero una famiglia syst.
            syst_ready = [f for f in ready if f != 'Central']
            if has_syst and syst_ready:
                cmd += ['--families', ','.join(syst_ready)]
            elif has_syst:
                cmd[cmd.index('both')] = 'central'
            cmd += ['--input-dir', V4_IN, '--manifest-root', V4_MAN, '--output-dir', str(root)]
            rc = run(cmd + extra, args.dry_run)
            if rc:
                print(f'    hadd uscito con {rc}')
            # merge-syst solo se c'e' davvero tutto: e' quello che pretende.
            if has_syst and not missing and not args.no_merge_syst:
                run(['bash', script, 'merge-syst', '--mode', 'both', '--eras', era,
                     '--check-level', 'files',
                     '--input-dir', V4_IN, '--manifest-root', V4_MAN,
                     '--output-dir', str(root)] + extra, args.dry_run)
            elif has_syst and missing:
                print('    merge-syst saltato: pretende Central e tutte le famiglie')


if __name__ == '__main__':
    main()
