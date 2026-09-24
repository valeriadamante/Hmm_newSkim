#!/usr/bin/env python3
"""Aggrega in parallelo su campagna x era x famiglia.

Il driver seriale impiegava ore perche' faceva una famiglia alla volta: l'hadd
e' legato all'I/O di EOS, non alla CPU, quindi tenerne uno solo in volo spreca
quasi tutto il tempo in attesa.  Qui ogni (campagna, era, famiglia) e' un
lavoro indipendente e ne girano N insieme.

Una famiglia per invocazione, con --mode syst --families <una>: con --mode both
workflow.py rifarebbe anche Central a ogni chiamata, e N processi si
pesterebbero i piedi sullo stesso output.  Central e' un lavoro a se',
--mode central.

    python3 campaigns/hadd_parallel.py --jobs 12
    python3 campaigns/hadd_parallel.py --dry-run --campaign all_variables
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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
LOGS = Path('logs_plots_Sep16')

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


def ready(c, era, family):
    try:
        products = W.raw_products(c, era, family)
    except Exception:
        return False
    return bool(products) and all(p.is_file() and p.stat().st_size > 0 for p in products)


def build_jobs(selected_campaigns, eras):
    jobs, skipped = [], []
    for name, script, config, root, extra, has_syst in CAMPAIGNS:
        if selected_campaigns and name not in selected_campaigns:
            continue
        c = campaign_object(config, root, extra)
        families = ['Central'] + (list(c.families) if has_syst else [])
        for era in eras:
            missing = [f for f in families if not ready(c, era, f)]
            for fam in families:
                if fam in missing:
                    continue
                mode = ['--mode', 'central'] if fam == 'Central' else ['--mode', 'syst', '--families', fam]
                jobs.append((name, era, fam, ['bash', script, 'hadd', *mode, '--eras', era,
                                              '--check-level', 'files', '--missing-only',
                                              '--input-dir', V4_IN, '--manifest-root', V4_MAN,
                                              '--output-dir', str(root)] + extra))
            if missing:
                skipped.append((name, era, missing))
    return jobs, skipped


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--eras', default=','.join(ERAS))
    p.add_argument('--campaign', action='append')
    p.add_argument('--jobs', type=int, default=12,
                   help="Aggregazioni in parallelo. L'hadd e' I/O su EOS: alzarlo "
                        "rende finche' EOS regge, non serve una CPU per lavoro.")
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    eras = [e.strip() for e in args.eras.split(',') if e.strip()]
    jobs, skipped = build_jobs(args.campaign, eras)
    LOGS.mkdir(exist_ok=True)

    print(f'{len(jobs)} aggregazioni pronte, {args.jobs} in parallelo', flush=True)
    for name, era, missing in skipped:
        print(f'  {name} Run3_{era}: {len(missing)} famiglie non pronte, saltate '
              f'({", ".join(missing[:4])}{"..." if len(missing) > 4 else ""})', flush=True)
    if args.dry_run:
        for name, era, fam, cmd in jobs[:10]:
            print('  $ ' + ' '.join(cmd))
        print(f'  ... e altre {max(0, len(jobs) - 10)}')
        return

    started = time.monotonic()
    done = failed = 0

    def run_one(job):
        name, era, fam, cmd = job
        log = LOGS / f'hadd_{name}_{era}_{fam}.log'
        with log.open('w') as handle:
            rc = subprocess.run(cmd, stdout=handle, stderr=subprocess.STDOUT).returncode
        return name, era, fam, rc

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = [pool.submit(run_one, job) for job in jobs]
        for future in as_completed(futures):
            name, era, fam, rc = future.result()
            done += 1
            failed += rc != 0
            mark = 'ok ' if rc == 0 else f'rc={rc}'
            print(f'[{done}/{len(jobs)}] {mark:<6} {name} Run3_{era} {fam} '
                  f'({time.monotonic() - started:.0f} s)', flush=True)

    print(f'\nfinito: {done - failed} riuscite, {failed} fallite, '
          f'{time.monotonic() - started:.0f} s', flush=True)


if __name__ == '__main__':
    main()
