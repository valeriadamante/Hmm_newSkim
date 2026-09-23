#!/usr/bin/env python3
"""Produce the histograms of one dataset as several parallel Condor jobs.

A campaign job covers a whole dataset, so the wall clock of an era is set by
its largest sample: DYto2L_M_50 is 337 files and takes ~2.3 h while every
other job is long finished.

`hist_maker --file-shard I/N` reads the normalization denominator from the
dataset-wide report JSONs, not from the processed files, so a shard carries the
same weights as the full job and the sum of the shards reproduces the
unsharded output bin by bin.  This driver submits the N shards into a private
`shards/` subdirectory and then merges them into the file the campaign expects,
`<family>/<era>/<dataset>.root`, leaving the rest of the chain untouched.

    python3 tools/shard_hists.py submit --config all_variables \
        --era Run3_2022EE --dataset DYto2L_M_50_amcatnloFXFX --shards 10
    python3 tools/shard_hists.py merge  --config all_variables \
        --era Run3_2022EE --dataset DYto2L_M_50_amcatnloFXFX --shards 10
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from campaigns.workflow import (REPO, csv, era_name, for_era, input_overrides, load_campaign,
                                physical_family)


def shard_directory(campaign, family, dataset, index, total):
    return campaign.directory(family) / 'shards' / dataset / f'{index:02d}_of_{total:02d}'


def shard_files(campaign, family, era, dataset, index, total):
    directory = shard_directory(campaign, family, dataset, index, total) / era
    return sorted(directory.glob('*.root')) if directory.is_dir() else []


def submit(args, campaign, era):
    era_campaign = for_era(campaign, era)
    for index in range(1, args.shards + 1):
        output = shard_directory(campaign, args.family, args.dataset, index, args.shards)
        command = [
            'bash',
            'histograms/scripts/' + ('hists.sh' if args.family == 'Central' else 'systematics.sh'),
            '--era', era,
            '--dataset-name', args.dataset,
            '--output-dir', str(output),
            '--manifest-input-folder', campaign.manifests,
            '--root-input-folder', campaign.input_root,
            '--json-input-folder', campaign.json_root or campaign.input_root,
            '--systematics', physical_family(args.family, era),
            '--request-cpus', campaign.cpus,
            '--request-memory', campaign.memory,
            '--condor',
            '--condor-label', f'{campaign.name}_{args.family}_{args.dataset[:24]}_shard{index:02d}',
            '--force' if args.force else '--missing-only',
            '--',
            *era_campaign.hist_args,
            '--rdf-threads', campaign.cpus,
            '--variable-batch-size', campaign.batch,
            '--file-shard', f'{index}/{args.shards}',
        ]
        print(f'[SHARD {index}/{args.shards}] ' + ' '.join(command), flush=True)
        if args.dry_run:
            continue
        subprocess.run(command, cwd=REPO, check=True)


def merge(args, campaign, era):
    """Sum the shard outputs into the per-dataset file the campaign expects."""
    per_shard = {
        index: shard_files(campaign, args.family, era, args.dataset, index, args.shards)
        for index in range(1, args.shards + 1)
    }
    missing = [index for index, files in per_shard.items() if not files]
    if missing:
        raise SystemExit(
            f'[ERROR] No output for shard(s) {missing} of {args.dataset}: '
            'the jobs are still running or have failed.'
        )
    # hist_maker writes one file per jet/PU component next to the nominal one;
    # every shard must carry the same set, otherwise a component is incomplete.
    names = {path.name for files in per_shard.values() for path in files}
    for index, files in per_shard.items():
        incomplete = names - {path.name for path in files}
        if incomplete:
            raise SystemExit(
                f'[ERROR] Shard {index} of {args.dataset} is missing {sorted(incomplete)}'
            )
    destination = campaign.directory(args.family) / era
    destination.mkdir(parents=True, exist_ok=True)
    for name in sorted(names):
        inputs = [
            str(shard_directory(campaign, args.family, args.dataset, index, args.shards) / era / name)
            for index in range(1, args.shards + 1)
        ]
        target = destination / name
        print(f'[MERGE] {target} from {len(inputs)} shards', flush=True)
        if args.dry_run:
            continue
        subprocess.run(['hadd', '-f', str(target), *inputs], check=True)
    if args.cleanup and not args.dry_run:
        shutil.rmtree(campaign.directory(args.family) / 'shards' / args.dataset)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('action', choices=['submit', 'merge'])
    parser.add_argument('--config', required=True, help='Campaign configuration, e.g. all_variables')
    parser.add_argument('--era', required=True, help='Physical era, e.g. Run3_2022EE')
    parser.add_argument('--dataset', required=True, help='Dataset to split across jobs')
    parser.add_argument('--shards', type=int, required=True, help='Number of parallel jobs')
    parser.add_argument('--family', default='Central', help='Systematic family, e.g. Central or PU')
    parser.add_argument('--threads', type=int, help='Overrides REQUEST_CPUS/--rdf-threads')
    parser.add_argument('--memory', help='Overrides REQUEST_MEMORY, e.g. 20GB')
    parser.add_argument('--variable-batch-size', type=int, help='Overrides VARIABLE_BATCH_SIZE')
    # Same input/output overrides as campaigns/workflow.py, so a sharded dataset
    # lands in the campaign directory the rest of the chain is reading.
    parser.add_argument('--input-root', help='Skim ROOT base, e.g. .../skim_v4')
    parser.add_argument('--manifest-root', help='Validation-manifest base')
    parser.add_argument('--json-root', help='Skim-report JSON base; defaults to --input-root')
    parser.add_argument('--output-root', help='Campaign root; defaults to CAMPAIGN_ROOT')
    # Le regioni e le categorie effettive possono venire dalla riga di comando
    # della campagna, non dal file di configurazione: la catena passa cinque
    # mass region al DNN mentre dnn_vbf_signal_sep03.sh ne ha una sola. Senza
    # questi due override uno shard produrrebbe un sottoinsieme delle regioni e
    # il merge sostituirebbe il file buono con uno monco.
    parser.add_argument('--regions', help='Override delle mass region, come in workflow.py')
    parser.add_argument('--categories', help='Override delle categorie, come in workflow.py')
    parser.add_argument('--force', action='store_true', help='Resubmit shards that already exist')
    parser.add_argument('--cleanup', action='store_true', help='Remove the shard directory after merging')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    if args.shards < 2:
        raise SystemExit('--shards must be >= 2')
    campaign = input_overrides(load_campaign(args.config), args)
    if args.output_root:
        campaign.root = Path(args.output_root).resolve()
    if args.regions:
        campaign.regions = csv(args.regions)
    if args.categories:
        campaign.categories = csv(args.categories)
    era = era_name(args.era)
    if args.action == 'submit':
        submit(args, campaign, era)
    else:
        merge(args, campaign, era)


if __name__ == '__main__':
    main()
