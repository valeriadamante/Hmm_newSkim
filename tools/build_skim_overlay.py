#!/usr/bin/env python3
"""Costruisce una view di skim combinando una produzione base e una patch.

Serve quando i file della produzione base appartengono a un altro utente e
l'ACL di EOS (``egroup:...:rw!d``) impedisce di sovrascriverli: i chunk rotti
vengono riprodotti in una directory di patch e questa view li sostituisce senza
toccare la base.

Per ogni chunk del manifest ``skim_chunks.json``:

* se esiste valido nella patch, il link punta alla patch;
* altrimenti punta alla base.

I link sono simbolici, quindi la view non occupa spazio.  ROOT li segue
normalmente anche su EOS.

    python3 tools/build_skim_overlay.py --era Run3_2024 \\
        --base /eos/.../skim_v4 --patch /eos/.../skim_v4_patch \\
        --output /eos/.../skim_v4_fixed --state-dir htcondor/skim_v4

Senza ``--run`` stampa soltanto il piano.
"""

import argparse
import json
import os
from pathlib import Path


def valid(path):
    return path.exists() and path.stat().st_size > 0


def chunk_ok(root_dir, dataset, index):
    base = root_dir / dataset
    return valid(base / f"skim_{index}.root") and valid(base / f"report_{index}.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--era", required=True)
    parser.add_argument("--base", required=True, type=Path,
                        help="Produzione originale (sola lettura).")
    parser.add_argument("--patch", required=True, type=Path,
                        help="Directory con i chunk riprodotti.")
    parser.add_argument("--output", required=True, type=Path,
                        help="View da creare.")
    parser.add_argument("--state-dir", required=True, type=Path,
                        help="State dir della campagna base, per i manifest skim_chunks.json.")
    parser.add_argument("--blacklist", type=Path, action="append", default=[],
                        help="JSON di tools/validate_skim.py: i chunk non OK non "
                             "vengono presi dalla base. Ripetibile.")
    parser.add_argument("--run", action="store_true",
                        help="Crea davvero i link. Senza questo stampa solo il piano.")
    args = parser.parse_args()

    rejected = set()
    for path in args.blacklist:
        for dataset, index, verdict, _, _ in json.loads(path.read_text()):
            if verdict != "OK":
                rejected.add((dataset, index))
    if rejected:
        print(f"[blacklist] {len(rejected)} chunk della base scartati dalla validazione")

    base_era = args.base / args.era
    patch_era = args.patch / args.era
    out_era = args.output / args.era

    manifests = sorted((args.state_dir / "log" / args.era).glob("*/skim_chunks.json"))
    if manifests:
        plan = [(m.parent.name, [c["index"] for c in json.loads(m.read_text())["chunks"]])
                for m in manifests]
    else:
        # Era prodotta con un'altra state dir: si linka quello che esiste.
        print(f"[WARN] nessun manifest sotto {args.state_dir}/log/{args.era}: "
              f"linko i chunk presenti, i chunk mai prodotti non sono rilevabili")
        if not base_era.is_dir():
            raise SystemExit(f"[ERROR] {base_era} non esiste")
        plan = []
        for dataset_dir in sorted(p for p in base_era.iterdir() if p.is_dir()):
            indices = sorted(int(f.stem.split("_")[-1])
                             for f in dataset_dir.glob("skim_*.root"))
            if indices:
                plan.append((dataset_dir.name, indices))

    n_base = n_patch = n_missing = 0
    missing = []

    for dataset, indices in plan:
        if args.run:
            (out_era / dataset).mkdir(parents=True, exist_ok=True)

        for index in indices:

            if chunk_ok(patch_era, dataset, index):
                source, kind = patch_era, "patch"
                n_patch += 1
            elif (dataset, index) not in rejected and chunk_ok(base_era, dataset, index):
                source, kind = base_era, "base"
                n_base += 1
            else:
                n_missing += 1
                missing.append(f"{dataset}/{index}")
                continue

            if not args.run:
                continue

            for name in (f"skim_{index}.root", f"report_{index}.json"):
                link = out_era / dataset / name
                target = source / dataset / name
                if link.is_symlink() or link.exists():
                    link.unlink()
                link.symlink_to(target)

    total = n_base + n_patch + n_missing
    print(f"era              : {args.era}")
    print(f"dataset          : {len(plan)}")
    print(f"chunk totali     : {total}")
    print(f"  dalla base     : {n_base}")
    print(f"  dalla patch    : {n_patch}")
    print(f"  ANCORA ROTTI   : {n_missing}")

    if missing:
        print("\nchunk senza sorgente valida:")
        for item in missing:
            print(f"  {item}")

    if args.run:
        print(f"\nview creata in {out_era}")
    else:
        print("\n[DRY RUN] rilanciare con --run per creare i link")

    return 1 if n_missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
