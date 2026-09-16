#!/usr/bin/env python3
"""Valida i file di una produzione di skim.

Il controllo di esistenza usato dal submitter non basta: un job ucciso dopo lo
``Snapshot`` lascia un ``.root`` pieno senza ``report_*.json``, e un file
troncato si apre ma contiene meno eventi di quelli dichiarati nel report.

Per ogni chunk del manifest ``skim_chunks.json`` verifica che

* il ``.root`` esista, non sia vuoto e si apra senza errori;
* contenga il tree ``Events`` e che l'ultimo evento sia leggibile;
* il ``report_*.json`` esista e sia JSON valido;
* le entries del tree coincidano con l'ultimo cut del report.

Scrive un JSON con l'esito di ogni chunk, riusabile come blacklist da
``tools/build_skim_overlay.py``.

    python3 tools/validate_skim.py --era Run3_2024 \\
        --input /eos/.../skim_v4 --state-dir htcondor/skim_v4 \\
        --output results/skim_v4/validation_Run3_2024.json
"""

import argparse
import json
import os
from multiprocessing import Pool
from pathlib import Path

import ROOT

ROOT.gROOT.SetBatch(True)
ROOT.gErrorIgnoreLevel = ROOT.kFatal


def check(task):
    """Restituisce (dataset, index, esito, entries, entries attese)."""
    directory, dataset, index = task
    root_path = os.path.join(directory, dataset, f"skim_{index}.root")
    report_path = os.path.join(directory, dataset, f"report_{index}.json")

    if not os.path.exists(root_path):
        return (dataset, index, "ROOT_ASSENTE", 0, -1)
    if os.path.getsize(root_path) == 0:
        return (dataset, index, "ROOT_VUOTO", 0, -1)

    try:
        tfile = ROOT.TFile.Open(root_path)
    except Exception as error:
        return (dataset, index, f"NON_APRIBILE ({type(error).__name__})", 0, -1)
    if not tfile or tfile.IsZombie():
        return (dataset, index, "ZOMBIE", 0, -1)

    tree = tfile.Get("Events")
    if not tree:
        tfile.Close()
        return (dataset, index, "NO_TREE_Events", 0, -1)

    entries = tree.GetEntries()
    try:
        tree.GetEntry(max(0, entries - 1))
    except Exception:
        tfile.Close()
        return (dataset, index, "ULTIMO_EVENTO_ILLEGGIBILE", entries, -1)
    tfile.Close()

    if not os.path.exists(report_path):
        return (dataset, index, "JSON_ASSENTE", entries, -1)
    try:
        report = json.loads(Path(report_path).read_text())
    except Exception:
        return (dataset, index, "JSON_CORROTTO", entries, -1)

    passes = [v["pass"] for v in report.values() if isinstance(v, dict) and "pass" in v]
    expected = passes[-1] if passes else -1
    if expected >= 0 and expected != entries:
        return (dataset, index, f"MISMATCH report={expected} tree={entries}", entries, expected)

    return (dataset, index, "OK", entries, expected)


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--era", required=True)
    parser.add_argument("--input", required=True, type=Path, help="Base della produzione.")
    parser.add_argument("--state-dir", required=True, type=Path,
                        help="State dir della campagna, per i manifest skim_chunks.json.")
    parser.add_argument("--output", type=Path, help="JSON con l'esito di ogni chunk.")
    parser.add_argument("--datasets", nargs="*", help="Limita a questi dataset.")
    parser.add_argument("--jobs", type=int, default=16, help="Processi paralleli.")
    parser.add_argument("--scan", action="store_true",
                        help="Ignora i manifest e valida tutti i file presenti. Serve per le "
                             "ere il cui state dir copre solo una parte dei dataset.")
    args = parser.parse_args()

    era_dir = args.input / args.era
    directory = str(era_dir)
    manifests = [] if args.scan else sorted(
        (args.state_dir / "log" / args.era).glob("*/skim_chunks.json"))
    tasks = []

    if manifests:
        for manifest in manifests:
            dataset = manifest.parent.name
            if args.datasets and dataset not in args.datasets:
                continue
            for chunk in json.loads(manifest.read_text())["chunks"]:
                tasks.append((directory, dataset, chunk["index"]))
    else:
        # Nessun manifest: l'era e' stata prodotta con un'altra state dir. Si
        # valida quello che c'e', senza poter accorgersi di chunk mai scritti.
        if not args.scan:
            print(f"[WARN] nessun manifest sotto {args.state_dir}/log/{args.era}: "
                  f"valido i file presenti, i chunk mai prodotti non sono rilevabili")
        if not era_dir.is_dir():
            raise SystemExit(f"[ERROR] {era_dir} non esiste")
        for dataset_dir in sorted(p for p in era_dir.iterdir() if p.is_dir()):
            if args.datasets and dataset_dir.name not in args.datasets:
                continue
            for root_file in sorted(dataset_dir.glob("skim_*.root")):
                index = int(root_file.stem.split("_")[-1])
                tasks.append((directory, dataset_dir.name, index))

    if not tasks:
        raise SystemExit(f"[ERROR] nessun chunk da validare in {directory}")

    print(f"valido {len(tasks)} chunk di {args.era} in {directory}", flush=True)
    with Pool(args.jobs) as pool:
        results = pool.map(check, tasks, chunksize=4)

    bad = [r for r in results if r[2] != "OK"]
    entries = sum(r[3] for r in results if r[2] == "OK")

    print(f"\nchunk validati   : {len(results)}")
    print(f"OK               : {len(results) - len(bad)}")
    print(f"PROBLEMI         : {len(bad)}")
    print(f"eventi totali    : {entries}")

    if bad:
        print("\ndataset                                        idx  problema")
        for dataset, index, what, _, _ in bad:
            print(f"{dataset:45s} {index:4d}  {what}")

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps([list(r) for r in results], indent=1))
        print(f"\nesito scritto in {args.output}")

    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
