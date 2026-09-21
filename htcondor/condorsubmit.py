#!/usr/bin/env python3

import argparse
import getpass
import json
import os
import shlex
import subprocess
import sys
import time
import yaml
from collections import defaultdict, OrderedDict


# One public entry point for both producers.  The historical skim invocation
# remains unchanged; ``condorsubmit.py histograms ...`` delegates to the
# histogram implementation while sharing the same user-facing command.
if len(sys.argv) > 1 and sys.argv[1] in {"histograms", "hists"}:
    histogram_submitter = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "hist_condorsubmit.py"
    )
    raise SystemExit(
        subprocess.run([sys.executable, histogram_submitter, *sys.argv[2:]]).returncode
    )
if len(sys.argv) > 1 and sys.argv[1] == "skim":
    del sys.argv[1]

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from common.utilities import chunk_files_by_size


parser = argparse.ArgumentParser(
    description="Submit skim jobs to HTCondor with one Condor cluster per dataset."
)
parser.add_argument(
    "-e",
    "--era",
    required=True,
    help="Era to process, e.g. Run3_2022EE",
)
parser.add_argument(
    "-d",
    "--dataset",
    dest="datasets",
    action="append",
    help="Process one exact dataset; repeat for multiple datasets.",
)
parser.add_argument(
    "--max-parallel-jobs",
    type=int,
    default=None,
    help="Override MAX_PARALLEL_JOBS from the script/default configuration.",
)
parser.add_argument(
    "--poll-interval",
    type=int,
    default=None,
    help="Override polling interval in seconds.",
)
parser.add_argument(
    "--max-submit-jobs",
    type=int,
    default=None,
    help=(
        "Submit at most this many jobs in total. Useful for quick tests, "
        "e.g. --max-submit-jobs 1."
    ),
)
parser.add_argument(
    "--submit",
    action=argparse.BooleanOptionalAction,
    default=True,
    help=(
        "Submit jobs after checking missing outputs. Use --no-submit to only "
        "print/write the missing-file report. Default: true."
    ),
)
parser.add_argument(
    "--use-ext",
    action=argparse.BooleanOptionalAction,
    default=None,
    help=(
        "Use all nanoAOD paths listed for each sample, including ext samples, "
        "when resolving DAS file lists on the fly. Default comes from "
        "skim_cfg.yaml use_ext, or false if unset."
    ),
)
parser.add_argument(
    "--proxy",
    default=None,
    help=(
        "VOMS proxy to forward to workers. Default: X509_USER_PROXY, then "
        "proxy_location from skim_cfg.yaml."
    ),
)
parser.add_argument(
    "--output-dir",
    default=None,
    help="Override the skim output base directory from skim_cfg.yaml.",
)
parser.add_argument("--state-dir", default=None,
                    help="Directory for campaign-specific logs, chunk maps and completion records.")
parser.add_argument("--jet-horn-veto", choices=("configured", "with", "without"), default="configured")
parser.add_argument("--n-events", type=int, default=-1, help="Input-event limit per skim job (-1: all).")
args = parser.parse_args()
if args.n_events != -1 and args.n_events <= 0:
    parser.error("--n-events must be positive or -1")

era = args.era

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
ANALYSIS_PATH = os.environ.get(
    "ANALYSIS_PATH",
    os.path.abspath(os.path.join(BASE_PATH, "..")),
)

if "ANALYSIS_PATH" not in os.environ:
    print(
        f"Environment variable ANALYSIS_PATH is not set, "
        f"using {ANALYSIS_PATH} as default"
    )
else:
    print(f"Using ANALYSIS_PATH={ANALYSIS_PATH}")

HTCONDOR_PATH = os.path.abspath(args.state_dir or os.path.join(ANALYSIS_PATH, "htcondor"))
CONFIG_PATH = os.path.join(ANALYSIS_PATH, "config")

skim_cfg_path = os.path.join(CONFIG_PATH, era, "skim_cfg.yaml")
main_cfg_path = os.path.join(CONFIG_PATH, era, "maincfg.yaml")
processes_yaml = os.path.join(CONFIG_PATH, era, "process_names.yaml")
samples_yaml = os.path.join(CONFIG_PATH, era, "samples_withfiles.yaml")

with open(skim_cfg_path, "r") as skimconfig:
    skim_config = yaml.safe_load(skimconfig)

with open(main_cfg_path, "r") as mainconfig:
    main_config = yaml.safe_load(mainconfig)

with open(processes_yaml, "r") as processes_config:
    processes_cfg = yaml.safe_load(processes_config)

with open(samples_yaml, "r") as samples_config:
    data = yaml.safe_load(samples_config)


# =========================================================
# HTCondor setup
# =========================================================

if args.submit:
    import htcondor

    schedd = htcondor.Schedd()
    credd = htcondor.Credd()
    credd.add_user_cred(htcondor.CredTypes.Kerberos, None)
else:
    schedd = None


# =========================================================
# Configuration
# =========================================================

flavour = skim_config["job_flavour"]
cpus = skim_config["request_cpus"]
memory = skim_config["request_memory"]
disk = skim_config["request_disk"]

max_files = skim_config["max_files"]
chunk_size = skim_config["chunk_size"]
target_chunk_size_gb = float(skim_config.get("target_chunk_size_gb", 5.0))
max_files_per_chunk = int(
    skim_config.get("max_files_per_chunk", max(chunk_size, 5))
)
target_chunk_size_bytes = int(target_chunk_size_gb * 1024**3)
if target_chunk_size_bytes <= 0:
    raise SystemExit("[ERROR] target_chunk_size_gb must be greater than zero")
if max_files_per_chunk <= 0:
    raise SystemExit("[ERROR] max_files_per_chunk must be greater than zero")

datasets_whitelist = skim_config.get("datasets_whitelist", [])
process_to_select = skim_config.get("process_to_select", [])

proxy_location = (
    args.proxy
    or os.environ.get("X509_USER_PROXY")
    or skim_config["proxy_location"]
)
proxy_location = os.path.abspath(os.path.expanduser(proxy_location))
if os.path.exists(proxy_location):
    os.environ["X509_USER_PROXY"] = proxy_location
    print(f"Using X509_USER_PROXY={proxy_location}")
elif args.submit:
    raise SystemExit(
        f"[ERROR] VOMS proxy does not exist: {proxy_location}. "
        "Run voms-proxy-init and export X509_USER_PROXY, or pass --proxy."
    )
else:
    print(f"[WARNING] VOMS proxy does not exist: {proxy_location}")
cmssw_version = skim_config.get("cmssw_version", "CMSSW_15_0_2")

submit_jobs = args.submit
use_ext = args.use_ext
if use_ext is None:
    use_ext = skim_config.get("use_ext", False)


output_dir = args.output_dir or skim_config["output_dir"]
output_directory = os.path.abspath(output_dir)
if args.jet_horn_veto == "without":
    print("[INFO] Overriding jet horn veto to 'without' for this skim.")
    if not args.output_dir:
        output_directory = os.path.abspath(skim_config.get(
            "output_dir_noJetHornVeto",
            skim_config.get("output_dir_noHorn", output_dir.rstrip("/") + "_noHornVeto"),
        ))

MAX_PARALLEL_JOBS = args.max_parallel_jobs or skim_config.get("max_parallel_jobs", 6000)
POLL_INTERVAL = args.poll_interval or skim_config.get("poll_interval", 120)
MAX_SUBMIT_JOBS = (
    args.max_submit_jobs
    if args.max_submit_jobs is not None
    else skim_config.get("max_submit_jobs")
)

if MAX_SUBMIT_JOBS is not None and MAX_SUBMIT_JOBS < 1:
    raise SystemExit("[ERROR] max_submit_jobs / --max-submit-jobs must be >= 1")

WRITE_MISSING_FILES_DRYRUN = skim_config.get("write_missing_files_dryrun", True)


# =========================================================
# Helpers
# =========================================================

def valid_file(path):
    return os.path.exists(path) and os.path.getsize(path) > 0


def as_list(value):
    if isinstance(value, list):
        return value
    return [value]


def select_nanoaod_paths(nanoaod_paths, use_ext=False):
    paths = as_list(nanoaod_paths)
    if use_ext:
        return paths
    return paths[:1]


def resolve_nanoaod_files(nanoaod_paths, instance=None):
    resolved_files = []
    seen_files = set()

    for nanoaod_path in as_list(nanoaod_paths):
        query = f"file dataset={nanoaod_path}"
        if instance:
            query += f" instance={instance}"

        command = ["dasgoclient", f"--query={query}", "--json"]
        print(f"[DAS] {shlex.join(command)}")

        result = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            print("\n[ERROR] DAS query failed")
            print(f"[ERROR] nanoAOD path : {nanoaod_path}")
            print(f"[ERROR] query        : {query}")
            print(f"[ERROR] command      : {shlex.join(command)}")
            print(f"[ERROR] return code  : {result.returncode}")
            if result.stdout.strip():
                print("[ERROR] stdout:")
                print(result.stdout.strip())
            if result.stderr.strip():
                print("[ERROR] stderr:")
                print(result.stderr.strip())
            raise SystemExit(result.returncode)

        try:
            das_payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            raise SystemExit(f"[ERROR] Invalid DAS JSON for {nanoaod_path}: {error}")

        file_entries = []
        for record in das_payload:
            for file_info in record.get("file", []):
                filepath = file_info.get("name")
                if filepath:
                    file_entries.append(
                        (filepath, int(file_info.get("size") or 0))
                    )

        for filepath, file_size in sorted(file_entries):
            eos_path = f"/eos/cms/{filepath}"

            if os.path.exists(eos_path):
                resolved_path = eos_path
            else:
                resolved_path = f"root://cms-xrd-global.cern.ch/{filepath}"

            if resolved_path in seen_files:
                continue

            resolved_files.append(
                {"path": resolved_path, "size": file_size}
            )
            seen_files.add(resolved_path)

    return resolved_files


def get_dataset_log_dir(dataset):
    return os.path.join(HTCONDOR_PATH, "log", era, dataset)


def get_dataset_skim_log_path(dataset):
    return os.path.join(get_dataset_log_dir(dataset), "skim.log")


def log_dataset_message(dataset, message, also_print=True):
    """
    Write a dataset-level status line to:
        htcondor/log/<era>/<dataset>/skim.log

    This is independent of the HTCondor event logs, which remain job-by-job:
        htcondor/log/<era>/<dataset>/<filename>.<ClusterId>.<ProcId>.log
    """
    log_dir = get_dataset_log_dir(dataset)
    os.makedirs(log_dir, exist_ok=True)

    timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {message}"

    with open(get_dataset_skim_log_path(dataset), "a") as log_file:
        log_file.write(line + "\n")

    if also_print:
        print(line, flush=True)


def get_output_paths(chunk_index, dataset):
    outfile_root = os.path.join(
        output_directory, era, dataset, f"skim_{chunk_index}.root"
    )
    outfile_json = os.path.join(
        output_directory, era, dataset, f"report_{chunk_index}.json"
    )

    return outfile_root, outfile_json


def is_completed(chunk_index, dataset, completed_files_set):
    outfile_root, outfile_json = get_output_paths(chunk_index, dataset)

    in_completed_list = (
        outfile_root in completed_files_set
        and outfile_json in completed_files_set
    )

    exists_on_disk = valid_file(outfile_root) and valid_file(outfile_json)

    return in_completed_list or exists_on_disk


def make_filename_key(chunk_index):
    return f"skim_{chunk_index}"


def make_job_key(dataset, filename_key):
    return f"{dataset}::{filename_key}"


def ensure_dataset_dirs(dataset):
    for folder in ["log", "error", "output"]:
        os.makedirs(os.path.join(HTCONDOR_PATH, folder, era, dataset), exist_ok=True)

    os.makedirs(os.path.join(output_directory, era, dataset), exist_ok=True)


def get_condor_status_counts(cluster_id):
    ads = schedd.query(
        constraint=f"ClusterId == {cluster_id}",
        projection=["JobStatus"],
    )

    counts = {
        "idle": 0,
        "running": 0,
        "removed": 0,
        "completed": 0,
        "held": 0,
        "transferring": 0,
        "suspended": 0,
        "unknown": 0,
    }

    for ad in ads:
        status = int(ad.get("JobStatus", -1))

        if status == 1:
            counts["idle"] += 1
        elif status == 2:
            counts["running"] += 1
        elif status == 3:
            counts["removed"] += 1
        elif status == 4:
            counts["completed"] += 1
        elif status == 5:
            counts["held"] += 1
        elif status == 6:
            counts["transferring"] += 1
        elif status == 7:
            counts["suspended"] += 1
        else:
            counts["unknown"] += 1

    counts["in_queue"] = len(ads)

    return counts


def get_active_jobs_count():
    """
    Count jobs that occupy active queue capacity for the current user.

    Here we count idle, running and transferring jobs.
    Held jobs are reported separately and do not consume the refill threshold.
    """
    owner = getpass.getuser()

    ads = schedd.query(
        constraint=(
            f'Owner == "{owner}" '
            "&& (JobStatus == 1 || JobStatus == 2 || JobStatus == 6)"
        ),
        projection=["ClusterId"],
    )

    return len(ads)


def write_missing_files_report(dataset, missing_files):
    log_dir = get_dataset_log_dir(dataset)
    os.makedirs(log_dir, exist_ok=True)

    missing_path = os.path.join(log_dir, "missing_files_dryrun.txt")

    with open(missing_path, "w") as mf:
        for infile in missing_files:
            mf.write(f"{infile}\n")

    return missing_path


def print_dryrun_summary(dataset_stats):
    print("\n========== DRY RUN SUMMARY ==========")

    total_files = 0
    total_completed = 0
    total_missing = 0
    total_jobs = 0

    for dataset, stats in dataset_stats.items():
        n_total = stats["total_chunks"]
        n_completed = stats["completed_files"]
        n_missing = stats["missing_files"]
        n_jobs = stats["jobs_to_run"]

        total_files += n_total
        total_completed += n_completed
        total_missing += n_missing
        total_jobs += n_jobs

        percent = 100.0 * n_completed / n_total if n_total > 0 else 0.0

        print(f"\n{dataset}")
        print(f"  chunks total     : {n_total}")
        print(f"  chunks completed : {n_completed}")
        print(f"  chunks missing   : {n_missing}")
        print(f"  NanoAOD inputs   : {stats['total_files']}")
        print(f"  completion       : {percent:.1f}%")
        print(f"  jobs to submit   : {n_jobs}")

        if stats.get("missing_report"):
            print(f"  missing report   : {stats['missing_report']}")

    global_percent = 100.0 * total_completed / total_files if total_files > 0 else 0.0

    print("\n========== GLOBAL SUMMARY ==========")
    print(f"chunks total     : {total_files}")
    print(f"chunks completed : {total_completed}")
    print(f"chunks missing   : {total_missing}")
    print(f"completion       : {global_percent:.1f}%")
    print(f"jobs to submit   : {total_jobs}")
    print("====================================\n")


def verify_job_outputs(job_key, global_job_output_map):
    expected = global_job_output_map[job_key]

    missing_or_corrupt = []

    for fpath in expected["root_files"] + expected["json_files"]:
        if not valid_file(fpath):
            missing_or_corrupt.append(fpath)

    return len(missing_or_corrupt) == 0, missing_or_corrupt


def mark_job_completed(job_key, global_job_output_map):
    expected = global_job_output_map[job_key]
    dataset = expected["dataset"]

    completed_files_path = os.path.join(
        get_dataset_log_dir(dataset),
        "completed_files.txt",
    )

    os.makedirs(os.path.dirname(completed_files_path), exist_ok=True)

    with open(completed_files_path, "a") as cf:
        for rf in expected["root_files"]:
            cf.write(f"{rf}\n")
        for jf in expected["json_files"]:
            cf.write(f"{jf}\n")


def write_failed_job_report(
    cluster_id,
    proc_id,
    job_key,
    missing_or_corrupt,
    global_job_output_map,
):
    expected = global_job_output_map[job_key]
    dataset = expected["dataset"]
    filename = expected["filename"]

    failed_report = os.path.join(
        get_dataset_log_dir(dataset),
        "failed_jobs_report.txt",
    )

    os.makedirs(os.path.dirname(failed_report), exist_ok=True)

    with open(failed_report, "a") as f:
        f.write(
            f"Cluster: {cluster_id}.{proc_id} | "
            f"Dataset: {dataset} | "
            f"Filename: {filename} | "
            f"Missing: {missing_or_corrupt}\n"
        )


def print_cluster_status(active_clusters):
    if not active_clusters:
        return

    for cluster_id, info in active_clusters.items():
        dataset = info["dataset"]
        counts = get_condor_status_counts(cluster_id)
        finished = info["num_proc"] - counts["in_queue"]
        percent = 100.0 * finished / info["num_proc"] if info["num_proc"] > 0 else 0.0

        message = (
            f"[CLUSTER] Cluster {cluster_id} -> {dataset}: "
            f"finished={finished}/{info['num_proc']} ({percent:.1f}%) | "
            f"idle={counts['idle']} running={counts['running']} "
            f"held={counts['held']} transferring={counts['transferring']} "
            f"in_queue={counts['in_queue']}"
        )

        log_dataset_message(dataset, message)


def verify_finished_cluster(cluster_id, cluster_info, global_job_output_map):
    dataset = cluster_info["dataset"]
    num_proc = cluster_info["num_proc"]
    proc_to_job_key = cluster_info["proc_to_job_key"]

    log_dataset_message(
        dataset,
        f"[VERIFY] Cluster {cluster_id} left the queue. Verifying outputs...",
    )

    cluster_success = 0
    cluster_failed = 0

    for proc_id in range(num_proc):
        job_key = proc_to_job_key[proc_id]

        ok, missing_or_corrupt = verify_job_outputs(
            job_key,
            global_job_output_map,
        )

        if ok:
            mark_job_completed(job_key, global_job_output_map)
            cluster_success += 1
        else:
            write_failed_job_report(
                cluster_id,
                proc_id,
                job_key,
                missing_or_corrupt,
                global_job_output_map,
            )
            cluster_failed += 1

    log_dataset_message(dataset, f"[CLUSTER SUMMARY] Cluster {cluster_id}")
    log_dataset_message(dataset, f"  successful jobs : {cluster_success}")
    log_dataset_message(dataset, f"  failed jobs     : {cluster_failed}")

    return cluster_success, cluster_failed


def check_and_verify_finished_clusters(active_clusters, global_job_output_map):
    finished_cluster_ids = []
    success = 0
    failed = 0
    finished = 0

    for cluster_id, cluster_info in list(active_clusters.items()):
        dataset = cluster_info["dataset"]
        counts = get_condor_status_counts(cluster_id)

        if counts["in_queue"] != 0:
            if counts["held"] > 0:
                log_dataset_message(
                    dataset,
                    (
                        f"[WARNING] Cluster {cluster_id} has {counts['held']} held jobs. "
                        "Check condor_q -hold for details."
                    ),
                )
            continue

        cluster_success, cluster_failed = verify_finished_cluster(
            cluster_id,
            cluster_info,
            global_job_output_map,
        )

        success += cluster_success
        failed += cluster_failed
        finished += cluster_info["num_proc"]
        finished_cluster_ids.append(cluster_id)

    for cluster_id in finished_cluster_ids:
        del active_clusters[cluster_id]

    return finished, success, failed


def wait_until_dataset_can_be_submitted(dataset, n_jobs, active_clusters, global_job_output_map):
    """
    Keep the one-cluster-per-dataset policy.

    If n_jobs <= MAX_PARALLEL_JOBS, this waits until the queue has enough free
    capacity to submit the whole dataset as a single Condor cluster.

    If n_jobs > MAX_PARALLEL_JOBS, strict one-cluster-per-dataset and strict
    max-parallel-jobs cannot both be satisfied. In that case we submit the full
    dataset cluster anyway, with a clear warning in the dataset skim.log.
    """
    if n_jobs > MAX_PARALLEL_JOBS:
        log_dataset_message(
            dataset,
            (
                f"[WARNING] Dataset has {n_jobs} jobs, larger than "
                f"MAX_PARALLEL_JOBS={MAX_PARALLEL_JOBS}. "
                "Submitting as one dataset cluster anyway."
            ),
        )
        return

    while True:
        finished, success, failed = check_and_verify_finished_clusters(
            active_clusters,
            global_job_output_map,
        )

        current_active = get_active_jobs_count()
        available_slots = MAX_PARALLEL_JOBS - current_active

        if available_slots >= n_jobs:
            return finished, success, failed

        log_dataset_message(
            dataset,
            (
                f"[QUEUE] Waiting to submit dataset cluster: "
                f"active={current_active}, available_slots={available_slots}, "
                f"needed={n_jobs}. Waiting {POLL_INTERVAL}s..."
            ),
        )
        print_cluster_status(active_clusters)
        time.sleep(POLL_INTERVAL)


# =========================================================
# Dataset selection
# =========================================================

all_datasets = []

if args.datasets:
    all_datasets.extend(args.datasets)
else:
    all_datasets.extend(datasets_whitelist)

if process_to_select and not args.datasets:
    for process in process_to_select:
        # "or []": un processo con tutti i dataset commentati lascia la chiave
        # a None, non a lista vuota, e la somma esplodeva con TypeError.
        datasets = processes_cfg[process].get("datasets") or []
        subprocesses = processes_cfg[process].get("sub_processes") or []
        all_datasets.extend(list(datasets) + list(subprocesses))

all_datasets = list(dict.fromkeys(all_datasets))

print(f"Datasets to process: {all_datasets}")


# =========================================================
# FASE 1: scan files + dry run information
# =========================================================

dataset_condorinputs = OrderedDict()
global_job_output_map = {}

dataset_stats = {}
missing_files_by_dataset = defaultdict(list)
selected_submit_jobs = 0
hit_max_submit_jobs = False

print("\n[INFO] Scanning datasets and checking existing outputs...")
print(f"[INFO] use_ext={use_ext}")

for dataset in all_datasets:
    if hit_max_submit_jobs:
        break

    if dataset not in data:
        print(f"[WARNING] You don't have the sample entry for: {dataset}")
        continue

    if "filelist" not in data[dataset]:
        if "nanoAOD" not in data[dataset]:
            print(f"[WARNING] You don't have the filelist or nanoAOD for: {dataset}")
            continue

        selected_nanoaod_paths = select_nanoaod_paths(
            data[dataset]["nanoAOD"],
            use_ext=use_ext,
        )
        if len(as_list(data[dataset]["nanoAOD"])) > len(selected_nanoaod_paths):
            print(
                f"[INFO] {dataset}: use_ext=False, using only first nanoAOD "
                f"path out of {len(as_list(data[dataset]['nanoAOD']))}."
            )

        data[dataset]["filelist"] = resolve_nanoaod_files(
            selected_nanoaod_paths,
            instance=data[dataset].get("instance", None),
        )

    ensure_dataset_dirs(dataset)

    # Start a fresh dataset-level skim log for this campaign.
    with open(get_dataset_skim_log_path(dataset), "w") as skim_log:
        skim_log.write(
            f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
            f"[START] Dataset {dataset}, era {era}\n"
        )

    completed_files_path = os.path.join(
        get_dataset_log_dir(dataset),
        "completed_files.txt",
    )

    completed_files_set = set()

    if os.path.exists(completed_files_path):
        with open(completed_files_path, "r") as cf:
            completed_files_set = {line.strip() for line in cf if line.strip()}

    filelist = data[dataset]["filelist"]
    if filelist and isinstance(filelist[0], str) and "nanoAOD" in data[dataset]:
        # Legacy samples_withfiles.yaml stores only paths. Re-resolve DAS
        # metadata so size-based chunking has the real byte count.
        selected_nanoaod_paths = select_nanoaod_paths(
            data[dataset]["nanoAOD"],
            use_ext=use_ext,
        )
        filelist = resolve_nanoaod_files(
            selected_nanoaod_paths,
            instance=data[dataset].get("instance", None),
        )

    if max_files > 0:
        filelist = filelist[:max_files]

    chunks = chunk_files_by_size(
        filelist,
        target_chunk_size_bytes,
        max_files_per_chunk,
    )
    chunk_manifest = {
        "era": era,
        "dataset": dataset,
        "target_chunk_size_gb": target_chunk_size_gb,
        "max_files_per_chunk": max_files_per_chunk,
        "chunks": [],
    }
    for chunk_index, chunk_entries in enumerate(chunks):
        outfile_root, outfile_json = get_output_paths(chunk_index, dataset)
        chunk_manifest["chunks"].append(
            {
                "index": chunk_index,
                "input_size_bytes": sum(
                    max(0, int(entry.get("size", 0)))
                    for entry in chunk_entries
                ),
                "input_files": [entry["path"] for entry in chunk_entries],
                "root_file": outfile_root,
                "report_file": outfile_json,
            }
        )
    chunk_manifest_path = os.path.join(
        get_dataset_log_dir(dataset), "skim_chunks.json"
    )
    with open(chunk_manifest_path, "w") as manifest_handle:
        json.dump(chunk_manifest, manifest_handle, indent=2)

    total_files = len(filelist)
    total_chunks = len(chunks)
    completed_files_count = 0
    missing_files_count = 0
    jobs_to_run = 0

    dataset_condorinputs[dataset] = []

    for chunk_index, chunk_entries in enumerate(chunks):
        input_files = [entry["path"] for entry in chunk_entries]
        outfile_root, outfile_json = get_output_paths(chunk_index, dataset)

        if is_completed(chunk_index, dataset, completed_files_set):
            completed_files_count += 1
            continue

        missing_files_count += 1
        missing_files_by_dataset[dataset].extend(input_files)

        if MAX_SUBMIT_JOBS is not None and selected_submit_jobs >= MAX_SUBMIT_JOBS:
            hit_max_submit_jobs = True
            break

        input_list = ",".join(input_files)

        filename_key = make_filename_key(chunk_index)
        job_key = make_job_key(dataset, filename_key)

        arguments = (
            f"{proxy_location} "
            f"{ANALYSIS_PATH} "
            f"{era} "
            f"{input_list} "
            f"{dataset} "
            f"{outfile_root} "
            f"{outfile_json} "
            f"{cmssw_version} "
            f"{args.jet_horn_veto} "
            f"{args.n_events} "
        )

        dataset_condorinputs[dataset].append({
            "arguments": arguments,
            "filename": filename_key,
            "dataset": dataset,
            "job_key": job_key,
        })

        global_job_output_map[job_key] = {
            "dataset": dataset,
            "filename": filename_key,
            "input_files": input_files,
            "root_files": [outfile_root],
            "json_files": [outfile_json],
        }

        jobs_to_run += 1
        selected_submit_jobs += 1

        if MAX_SUBMIT_JOBS is not None and selected_submit_jobs >= MAX_SUBMIT_JOBS:
            hit_max_submit_jobs = True
            break

    missing_report = None

    if WRITE_MISSING_FILES_DRYRUN:
        missing_report = write_missing_files_report(
            dataset,
            missing_files_by_dataset[dataset],
        )

    dataset_stats[dataset] = {
        "total_files": total_files,
        "total_chunks": total_chunks,
        "completed_files": completed_files_count,
        "missing_files": missing_files_count,
        "jobs_to_run": jobs_to_run,
        "missing_report": missing_report,
    }

    percent = (
        100.0 * completed_files_count / total_chunks
        if total_chunks > 0
        else 0.0
    )

    log_dataset_message(
        dataset,
        f"[SCAN] inputs={total_files} chunks={total_chunks} "
        f"completed={completed_files_count} missing={missing_files_count} "
        f"({percent:.1f}%) submit={jobs_to_run}",
    )
    if missing_report:
        log_dataset_message(dataset, f"  missing report   : {missing_report}")

    if hit_max_submit_jobs:
        log_dataset_message(
            dataset,
            f"[INFO] Reached max_submit_jobs={MAX_SUBMIT_JOBS}. "
            "Stopping job selection here.",
        )

total_jobs_to_run = sum(
    len(condorinputs) for condorinputs in dataset_condorinputs.values()
)

print_dryrun_summary(dataset_stats)

if MAX_SUBMIT_JOBS is not None:
    print(
        f"[INFO] max_submit_jobs limit enabled: "
        f"selected {total_jobs_to_run}/{MAX_SUBMIT_JOBS} jobs."
    )


# =========================================================
# FASE 2: dry run exit
# =========================================================

if not submit_jobs:
    print("[DRY RUN] --no-submit")
    print("[DRY RUN] No jobs submitted.")
    raise SystemExit(0)

if total_jobs_to_run == 0:
    print("[INFO] All files are already completed. No jobs to submit.")
    raise SystemExit(0)


# =========================================================
# FASE 3: submit description
# =========================================================

job = htcondor.Submit({
    "executable": os.path.join(BASE_PATH, "run_skim.sh"),
    "arguments": "$(arguments)",

    # stdout from the executable, one file per job
    "output": os.path.join(
        HTCONDOR_PATH,
        "output",
        era,
        "$(dataset)",
        "$(filename).$(ClusterId).$(ProcId).out",
    ),

    # stderr from the executable, one file per job
    "error": os.path.join(
        HTCONDOR_PATH,
        "error",
        era,
        "$(dataset)",
        "$(filename).$(ClusterId).$(ProcId).err",
    ),

    # HTCondor event log, one file per job
    "log": os.path.join(
        HTCONDOR_PATH,
        "log",
        era,
        "$(dataset)",
        "$(filename).$(ClusterId).$(ProcId).log",
    ),

    "universe": "vanilla",
    "Requirements": '(OpSysAndVer =?= "AlmaLinux9")',
    "+JobFlavour": f'"{flavour}"',
    "+JobKey": '"$(job_key)"',
    "+Dataset": '"$(dataset)"',
    "RequestCpus": str(cpus),
    "request_memory": str(memory),
    "request_disk": str(disk),
    "max_retries": "1",

    # Since each submission contains one dataset only, this becomes:
    #   Skim_Run3_2022EE_DYJets
    #   Skim_Run3_2022EE_TTTo2L2Nu
    #   ...
    "batch_name": f"Skim_{era}_$(dataset)",
})

job["MY.SendCredential"] = "true"


# =========================================================
# FASE 4: one Condor cluster per dataset + monitoring
# =========================================================

print("\n[INFO] Starting dataset-wise submission...")
print(f"[INFO] MAX_PARALLEL_JOBS = {MAX_PARALLEL_JOBS}")
print(f"[INFO] POLL_INTERVAL     = {POLL_INTERVAL}s")
if MAX_SUBMIT_JOBS is not None:
    print(f"[INFO] MAX_SUBMIT_JOBS  = {MAX_SUBMIT_JOBS}")

active_clusters = {}

global_submitted_jobs = 0
global_finished_jobs = 0
global_success_jobs = 0
global_failed_jobs = 0

for dataset, condorinputs in dataset_condorinputs.items():
    if len(condorinputs) == 0:
        log_dataset_message(dataset, "[INFO] No jobs to submit for this dataset.")
        continue

    n_jobs = len(condorinputs)

    log_dataset_message(
        dataset,
        f"[SUBMIT PREP] Dataset {dataset} has {n_jobs} jobs to submit.",
    )

    result = wait_until_dataset_can_be_submitted(
        dataset,
        n_jobs,
        active_clusters,
        global_job_output_map,
    )

    if result is not None:
        finished, success, failed = result
        if finished > 0:
            global_finished_jobs += finished
            global_success_jobs += success
            global_failed_jobs += failed

    current_active = get_active_jobs_count()
    available_slots = MAX_PARALLEL_JOBS - current_active

    log_dataset_message(
        dataset,
        (
            f"[SUBMIT] Submitting one cluster for dataset {dataset}: "
            f"active={current_active}, available_slots={available_slots}, jobs={n_jobs}"
        ),
    )

    submit_result = schedd.submit(job, itemdata=iter(condorinputs))

    cluster_id = submit_result.cluster()
    num_proc = submit_result.num_procs()

    proc_to_job_key = {
        proc_id: condorinputs[proc_id]["job_key"]
        for proc_id in range(num_proc)
    }

    active_clusters[cluster_id] = {
        "dataset": dataset,
        "num_proc": num_proc,
        "proc_to_job_key": proc_to_job_key,
    }

    global_submitted_jobs += num_proc

    log_dataset_message(
        dataset, f"[SUBMIT] Cluster {cluster_id} -> {dataset} ({num_proc} jobs)"
    )

    print(
        f"[GLOBAL STATUS] "
        f"submitted={global_submitted_jobs}/{total_jobs_to_run}, "
        f"finished={global_finished_jobs}/{total_jobs_to_run}, "
        f"success={global_success_jobs}, "
        f"failed={global_failed_jobs}",
        flush=True,
    )


# =========================================================
# FASE 5: final monitoring
# =========================================================

while active_clusters:
    finished, success, failed = check_and_verify_finished_clusters(
        active_clusters,
        global_job_output_map,
    )

    if finished > 0:
        global_finished_jobs += finished
        global_success_jobs += success
        global_failed_jobs += failed

        print(
            f"[GLOBAL STATUS] "
            f"submitted={global_submitted_jobs}/{total_jobs_to_run}, "
            f"finished={global_finished_jobs}/{total_jobs_to_run}, "
            f"success={global_success_jobs}, "
            f"failed={global_failed_jobs}",
            flush=True,
        )
    else:
        print_cluster_status(active_clusters)

    if active_clusters:
        time.sleep(POLL_INTERVAL)


# =========================================================
# Final summary
# =========================================================

print("\n========== FINAL SUMMARY ==========")
print(f"submitted jobs : {global_submitted_jobs}")
print(f"finished jobs  : {global_finished_jobs}")
print(f"successful     : {global_success_jobs}")
print(f"failed         : {global_failed_jobs}")
print("===================================\n")

for dataset in dataset_condorinputs:
    log_dataset_message(dataset, "[FINAL SUMMARY]", also_print=False)
    log_dataset_message(dataset, f"  submitted jobs : {len(dataset_condorinputs[dataset])}", also_print=False)
