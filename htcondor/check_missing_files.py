#!/usr/bin/env python3

import os
import argparse
import json
import yaml
from collections import OrderedDict

parser = argparse.ArgumentParser(
    description="Dry-run checker: count missing skim outputs per dataset/sample."
)

parser.add_argument("-e", "--era", required=True, help="e.g. Run3_2022EE")
parser.add_argument("--max-files", type=int, default=None)
parser.add_argument("--write-missing", action="store_true")
parser.add_argument("--only-missing", action="store_true")

args = parser.parse_args()
era = args.era

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
ANALYSIS_PATH = os.environ.get(
    "ANALYSIS_PATH",
    os.path.abspath(os.path.join(BASE_PATH, "..")),
)

CONFIG_PATH = os.path.join(ANALYSIS_PATH, "config")
HTCONDOR_PATH = os.path.join(ANALYSIS_PATH, "htcondor")

skim_cfg_path = os.path.join(CONFIG_PATH, era, "skim_cfg.yaml")
main_cfg_path = os.path.join(CONFIG_PATH, era, "maincfg.yaml")
processes_yaml = os.path.join(CONFIG_PATH, era, "process_names.yaml")
samples_yaml = os.path.join(CONFIG_PATH, era, "samples_withfiles.yaml")

with open(skim_cfg_path) as f:
    skim_config = yaml.safe_load(f)

with open(main_cfg_path) as f:
    main_config = yaml.safe_load(f)

with open(processes_yaml) as f:
    processes_cfg = yaml.safe_load(f)

with open(samples_yaml) as f:
    samples_cfg = yaml.safe_load(f)

output_dir = skim_config["output_dir"]
output_directory = os.path.abspath(output_dir)
max_files_cfg = skim_config.get("max_files", -1)

datasets_whitelist = skim_config.get("datasets_whitelist", [])
process_to_select = skim_config.get("process_to_select", [])


def valid_file(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


def get_output_paths(infile, dataset):
    basename = os.path.basename(infile)

    outfile_root = os.path.join(
        output_directory,
        era,
        dataset,
        basename.replace(".root", "_skim.root"),
    )

    outfile_json = os.path.join(
        output_directory,
        era,
        dataset,
        basename.replace(".root", "_skim_report.json"),
    )

    return outfile_root, outfile_json


def get_dataset_log_dir(dataset):
    return os.path.join(HTCONDOR_PATH, "log", era, dataset)


def write_missing_report(dataset, missing_files):
    log_dir = get_dataset_log_dir(dataset)
    os.makedirs(log_dir, exist_ok=True)

    outpath = os.path.join(log_dir, "missing_files_dryrun.txt")

    with open(outpath, "w") as f:
        for x in missing_files:
            f.write(x + "\n")

    return outpath


# ============================================================
# Build dataset list
# ============================================================

all_datasets = []

all_datasets.extend(datasets_whitelist)

for process in process_to_select:
    # "or []": vedi condorsubmit.py, una lista di dataset tutta commentata
    # arriva come None e faceva esplodere extend().
    all_datasets.extend(processes_cfg[process].get("datasets") or [])
    all_datasets.extend(processes_cfg[process].get("sub_processes") or [])

all_datasets = list(OrderedDict.fromkeys(all_datasets))


# ============================================================
# Scan
# ============================================================

summary = OrderedDict()

for dataset in all_datasets:

    chunk_manifest_path = os.path.join(
        get_dataset_log_dir(dataset), "skim_chunks.json"
    )
    if not os.path.exists(chunk_manifest_path):
        print(
            f"[WARNING] Missing chunk manifest for dataset {dataset}: "
            f"{chunk_manifest_path}. Run condorsubmit.py --no-submit first."
        )
        continue

    with open(chunk_manifest_path) as manifest_handle:
        chunk_manifest = json.load(manifest_handle)
    chunks = chunk_manifest.get("chunks", [])

    missing_files = []
    completed = 0

    for chunk in chunks:
        outfile_root = chunk["root_file"]
        outfile_json = chunk["report_file"]
        if valid_file(outfile_root) and valid_file(outfile_json):
            completed += 1
        else:
            missing_files.extend(chunk.get("input_files", []))

    total = len(chunks)
    missing = total - completed

    report = None
    if args.write_missing:
        report = write_missing_report(dataset, missing_files)

    summary[dataset] = {
        "total": total,
        "completed": completed,
        "missing": missing,
        "report": report,
    }


# ============================================================
# Print compact summary
# ============================================================

print("\n========== MISSING FILES DRYRUN ==========\n")

global_total = 0
global_completed = 0
global_missing = 0

for dataset, s in summary.items():

    if args.only_missing and s["missing"] == 0:
        continue

    total = s["total"]
    completed = s["completed"]
    missing = s["missing"]

    frac = 100.0 * completed / total if total else 0.0

    global_total += total
    global_completed += completed
    global_missing += missing

    print(
        f"{dataset:45s} "
        f"missing = {missing:6d} / {total:6d} "
        f"completed = {completed:6d} "
        f"({frac:5.1f}%)"
    )

    if s["report"]:
        print(f"{'':45s} report  = {s['report']}")

print("\n========== GLOBAL ==========")
print(f"total chunks     : {global_total}")
print(f"completed chunks : {global_completed}")
print(f"missing chunks   : {global_missing}")
print("=========================================\n")
