#!/usr/bin/env python3
"""Submit special_sync_skim.py to HTCondor, one job per NanoAOD file.

Outputs go to <output-root>/<dataset>/job_<n>.root and job_<n>_report.json.
Jobs whose report already exists on EOS are skipped, so rerunning the command
resubmits only the missing or failed ones.
"""
import argparse
import subprocess
from pathlib import Path

import yaml

REPOSITORY = Path(__file__).resolve().parents[2]
DATASETS = ("Muon0_Run2024H", "Muon1_Run2024H")


def xrootd(path):
    """Standard schedds refuse /eos paths in the arguments: use xrootd URLs."""
    path = path.replace("/eos/cms//store", "/eos/cms/store")
    if path.startswith("/eos/cms/"):
        return "root://eoscms.cern.ch/" + path
    if path.startswith("/eos/user/"):
        return "root://eosuser.cern.ch/" + path
    return path


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default="special_20260923")
    parser.add_argument("--output-root", type=Path, default=Path("/eos/user/v/vdamante/H_mumu/Sync"))
    parser.add_argument("--proxy", default=str(REPOSITORY / "data" / "voms.proxy"))
    parser.add_argument("--flavour", default="workday")
    parser.add_argument("--max-jobs", type=int, default=None, help="submit at most N jobs (tests)")
    parser.add_argument("--no-submit", action="store_true")
    return parser.parse_args()


def main():
    args = arguments()
    samples = yaml.safe_load((REPOSITORY / "config" / "Run3_2024" / "samples_withfiles.yaml").read_text())
    log_dir = REPOSITORY / "htcondor" / "special_sync" / args.tag
    log_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    for dataset in DATASETS:
        output_dir = args.output_root / args.tag / dataset
        output_dir.mkdir(parents=True, exist_ok=True)
        files = samples[dataset]["filelist"]
        (output_dir.parent / f"{dataset}_inputs.txt").write_text(
            "".join(f"job_{i}\t{path}\n" for i, path in enumerate(files)))
        for index, path in enumerate(files):
            job = f"job_{index}"
            if (output_dir / f"{job}_report.json").is_file():
                continue
            lines.append(f"{args.proxy} {REPOSITORY} {dataset} {xrootd(path)} "
                         f"{xrootd(str(output_dir))} {job}")
    if args.max_jobs is not None:
        lines = lines[:args.max_jobs]
    queue = log_dir / "jobs.txt"
    queue.write_text("\n".join(lines) + "\n")
    submit = log_dir / "special_sync.sub"
    submit.write_text(f"""executable = {REPOSITORY}/sync/python/run_special_sync_skim.sh
arguments = $(proxy) $(repo) $(dataset) $(input) $(outdir) $(job)
output = {log_dir}/$(dataset)_$(job).$(ClusterId).$(ProcId).out
error = {log_dir}/$(dataset)_$(job).$(ClusterId).$(ProcId).err
log = {log_dir}/special_sync.$(ClusterId).log
universe = vanilla
Requirements = (OpSysAndVer =?= "AlmaLinux9")
+JobFlavour = "{args.flavour}"
RequestCpus = 1
request_memory = 4GB
request_disk = 4GB
max_retries = 2
MY.SendCredential = true
batch_name = SpecialSync_{args.tag}
queue proxy, repo, dataset, input, outdir, job from {queue}
""")
    print(f"[special-sync] {len(lines)} jobs, submit file {submit}")
    if lines and not args.no_submit:
        subprocess.run(["condor_submit", str(submit)], check=True)


if __name__ == "__main__":
    main()
