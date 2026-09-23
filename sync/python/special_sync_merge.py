#!/usr/bin/env python3
"""Merge the special sync jobs into the final sync tuples and cutflows.

Refuses to merge unless every input file of both datasets has its report.
Writes, next to the other sync tuples:
  sync_tuple_<Muon0|Muon1>_Run2024H_<tag>.root and sync_tuple_Run2024H_<tag>.root
  <stem>_cutflow.csv, <stem>_cutflow_vbf_Z_CR_H_SB.csv, <stem>_categories_regions.csv
"""
import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

REPOSITORY = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPOSITORY))
from studies.prepare_tuple_forSync import write_cutflow  # noqa: E402

DATASETS = ("Muon0_Run2024H", "Muon1_Run2024H")


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="special_20260923")
    parser.add_argument("--output-root", type=Path, default=Path("/eos/user/v/vdamante/H_mumu/Sync"))
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def dataset_jobs(root, dataset):
    inputs = (root / f"{dataset}_inputs.txt").read_text().split("\n")
    jobs = [line.split("\t")[0] for line in inputs if line]
    missing = [job for job in jobs if not (root / dataset / f"{job}_report.json").is_file()
               or not (root / dataset / f"{job}.root").is_file()]
    if missing:
        raise SystemExit(f"[ERROR] {dataset}: {len(missing)}/{len(jobs)} jobs missing, e.g. {missing[:5]}")
    return [root / dataset / f"{job}.root" for job in jobs]


def summed(reports):
    report, cutflows, yields, total = {}, {}, {}, 0
    for path in reports:
        data = json.loads(path.read_text())
        for name, value in data["report"].items():
            report[name] = report.get(name, 0) + int(value if isinstance(value, int) else value["pass"])
        for key, steps in data["cutflows"].items():
            target = cutflows.setdefault(key, {})
            for step, count in steps:
                target[step] = target.get(step, 0) + count
        for kind, name, count in data["yields"]:
            yields[(kind, name)] = yields.get((kind, name), 0) + count
        total += data["events_after_skim"]
    return report, cutflows, yields, total


def write_outputs(stem, root_files, overwrite):
    output = stem.with_suffix(".root")
    if output.exists() and not overwrite:
        raise SystemExit(f"[ERROR] {output} exists; pass --overwrite")
    subprocess.run(["hadd", "-f", str(output), *map(str, root_files)], check=True,
                   stdout=subprocess.DEVNULL)
    reports = [path.with_name(f"{path.stem}_report.json") for path in root_files]
    report, cutflows, yields, total = summed(reports)
    report_counts = list(report.items())
    for key, steps in cutflows.items():
        suffix = "_cutflow" if key == "cutflow" else f"_{key}"
        write_cutflow(stem.with_name(stem.name + suffix + ".csv"), report_counts, list(steps.items()))
    with stem.with_name(stem.name + "_categories_regions.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["kind", "selection", "pass", "total_events", "efficiency"])
        for (kind, name), count in yields.items():
            writer.writerow([kind, name, count, total, count / total if total else 0.0])
    print(f"[special-sync] wrote {output}")


def main():
    args = arguments()
    root = args.output_root / args.tag
    per_dataset = {dataset: dataset_jobs(root, dataset) for dataset in DATASETS}
    for dataset, files in per_dataset.items():
        write_outputs(args.output_root / f"sync_tuple_{dataset}_{args.tag}", files, args.overwrite)
    write_outputs(args.output_root / f"sync_tuple_Run2024H_{args.tag}",
                  [f for files in per_dataset.values() for f in files], args.overwrite)


if __name__ == "__main__":
    main()
