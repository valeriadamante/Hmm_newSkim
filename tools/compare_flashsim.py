#!/usr/bin/env python3
"""Confronta FullSim e FlashSim sulle stesse variabili, regione per regione.

Gli hadd delle campagne scrivono un file ROOT per processo, con una directory
per ``<mass_region>_<categoria>`` e dentro un istogramma per variabile.  I
processi FlashSim sono dichiarati in ``config/<era>/process_names.yaml`` accanto
ai corrispondenti FullSim, quindi il confronto e' fra due file dello stesso hadd.

Le coppie si deducono dal nome togliendo il suffisso ``_FlashSim``/``_Flashsim``;
quelle che non si deducono sono in ``EXTRA_PAIRS`` e si possono estendere con
``--pair FLASHSIM=FULLSIM``.

Il disegno e' delegato a ``studies/compare_hists.py``, che gia' fa rapporto,
rebinning ed etichette CMS.

    python3 tools/compare_flashsim.py --era Run3_2024 \\
        --input-base /eos/.../post_dy/all_variables/Hists_hadded \\
        --output results/skim_v4/flashsim_comparison
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

import yaml

import ROOT

ROOT.gROOT.SetBatch(True)
ROOT.gErrorIgnoreLevel = ROOT.kFatal

REPO = Path(__file__).resolve().parent.parent

# Coppie che il nome non permette di dedurre.
EXTRA_PAIRS = {
    "TTto2L2Nu_Flashsim": "TT",
    "VBFHto2Mu_m125_Flashsim": "VBFHto2Mu_M125_powheg",
}


def flashsim_pairs(era, extra):
    """Restituisce [(processo FlashSim, processo FullSim)] per l'era."""
    config = yaml.safe_load((REPO / "config" / era / "process_names.yaml").read_text())
    processes = {k for k, v in config.items() if isinstance(v, dict)}

    pairs = []
    for name in sorted(processes):
        if "flashsim" not in name.lower():
            continue
        override = extra.get(name)
        if override:
            counterpart = override
        else:
            stem = name.replace("_FlashSim", "").replace("_Flashsim", "")
            counterpart = stem if stem in processes else None
        if counterpart is None:
            print(f"[WARN] {name}: nessuna controparte FullSim, salto "
                  f"(aggiungila con --pair {name}=<processo>)")
            continue
        if counterpart not in processes:
            print(f"[WARN] {name}: controparte '{counterpart}' assente in process_names.yaml, salto")
            continue
        pairs.append((name, counterpart))
    return pairs


def contents(path):
    """{regione: [variabili]} di un file di hadd."""
    tfile = ROOT.TFile.Open(str(path))
    if not tfile or tfile.IsZombie():
        return {}
    found = {}
    for key in tfile.GetListOfKeys():
        directory = tfile.Get(key.GetName())
        if not directory or not directory.InheritsFrom("TDirectory"):
            continue
        found[key.GetName()] = sorted({k.GetName() for k in directory.GetListOfKeys()})
    tfile.Close()
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--era", required=True)
    parser.add_argument("--input-base", required=True, type=Path,
                        help="Directory di hadd che contiene <era>/<processo>.root")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--regions", help="CSV di regioni; default: tutte quelle presenti.")
    parser.add_argument("--variables", help="CSV di variabili; default: tutte quelle presenti.")
    parser.add_argument("--pair", action="append", default=[],
                        metavar="FLASHSIM=FULLSIM", help="Coppia esplicita, ripetibile.")
    parser.add_argument("--run", action="store_true",
                        help="Produce i plot. Senza, stampa solo il piano.")
    args = parser.parse_args()

    extra = dict(EXTRA_PAIRS)
    for item in args.pair:
        if "=" not in item:
            parser.error(f"--pair vuole FLASHSIM=FULLSIM, ricevuto {item!r}")
        flash, full = item.split("=", 1)
        extra[flash] = full

    pairs = flashsim_pairs(args.era, extra)
    if not pairs:
        raise SystemExit(f"[ERROR] nessuna coppia FlashSim/FullSim per {args.era}")

    era_dir = args.input_base / args.era
    wanted_regions = set(args.regions.split(",")) if args.regions else None
    wanted_variables = set(args.variables.split(",")) if args.variables else None

    planned = 0
    produced = 0
    summary = []

    for flash, full in pairs:
        file_flash = era_dir / f"{flash}.root"
        file_full = era_dir / f"{full}.root"
        if not file_flash.exists() or not file_full.exists():
            missing = [str(p) for p in (file_flash, file_full) if not p.exists()]
            print(f"[WARN] {flash} vs {full}: manca {missing}, salto")
            continue

        in_flash = contents(file_flash)
        in_full = contents(file_full)
        regions = sorted(set(in_flash) & set(in_full))
        if wanted_regions:
            regions = [r for r in regions if r in wanted_regions]

        for region in regions:
            variables = sorted(set(in_flash[region]) & set(in_full[region]))
            if wanted_variables:
                variables = [v for v in variables if v in wanted_variables]

            for variable in variables:
                out_dir = args.output / args.era / f"{flash}_vs_{full}" / region
                out_file = out_dir / f"{variable}.png"
                planned += 1
                if not args.run:
                    continue

                out_dir.mkdir(parents=True, exist_ok=True)
                command = [
                    sys.executable, str(REPO / "studies" / "compare_hists.py"),
                    str(file_full), str(file_flash),
                    "-r", region, "-v", variable,
                    "--label-a", full, "--label-b", flash,
                    # I nomi di processo sull'asse del rapporto sono illeggibili:
                    # la legenda sopra li riporta per intero, qui basta il verso.
                    "--ratio-label", "FullSim / FlashSim",
                    "-o", str(out_file),
                ]
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode == 0:
                    produced += 1
                    summary.append({"flashsim": flash, "fullsim": full,
                                    "region": region, "variable": variable,
                                    "plot": str(out_file)})
                else:
                    print(f"[WARN] {flash}/{region}/{variable}: "
                          f"{result.stderr.strip().splitlines()[-1] if result.stderr.strip() else 'fallito'}")

    print(f"\nera        : {args.era}")
    print(f"coppie     : {len(pairs)}")
    for flash, full in pairs:
        print(f"  {flash:42s} vs {full}")
    print(f"confronti  : {planned}")
    if args.run:
        print(f"plot scritti: {produced}")
        index = args.output / args.era / "index.json"
        index.parent.mkdir(parents=True, exist_ok=True)
        index.write_text(json.dumps(summary, indent=1))
        print(f"indice     : {index}")
    else:
        print("\n[DRY RUN] rilanciare con --run")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
