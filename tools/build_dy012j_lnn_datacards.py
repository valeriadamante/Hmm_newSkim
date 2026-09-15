#!/usr/bin/env python3
"""Replace DY 2J rate parameters with era-specific log-normal uncertainties."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


COMPONENT_TO_PROCESS = {
    # The datacard processes retain the 2J names, but their correction in the
    # VBF category is fitted by the VBF-Z stage of derive_dy_012j_reweight.py.
    "VBFHard": ("2JHard", "DYto2Mu_MLL105To160_2J_Hard"),
    "VBFPU1": ("2JPU1", "DYto2Mu_MLL105To160_2J_PU1"),
    "VBFPU2": ("2JPU2", "DYto2Mu_MLL105To160_2J_PU2"),
}

ERA_GROUPS = {
    "2022": ("2022_2022EE", "Run3_2022_2022EE"),
    "2022EE": ("2022_2022EE", "Run3_2022_2022EE"),
    "2023": ("2023_2023BPix", "Run3_2023_2023BPix"),
    "2023BPix": ("2023_2023BPix", "Run3_2023_2023BPix"),
    "2024": ("2024", "Run3_2024"),
    "2025": ("2025", "Run3_2025"),
}

def fit_uncertainties(fit_root: Path, eras: list[str]) -> dict[tuple[str, str], float]:
    result: dict[tuple[str, str], float] = {}
    for era in eras:
        group, payload_dir = ERA_GROUPS[era]
        path = fit_root / payload_dir / "dy_012j_reweight_fit.json"
        payload = json.loads(path.read_text())
        parameters = dict(
            zip(payload["parameter_order"], zip(payload["values"], payload["errors"]))
        )
        for component in COMPONENT_TO_PROCESS:
            value, error = parameters[component]
            if value == 0.0:
                if error != 0.0:
                    raise ValueError(f"{path}: {component} has zero value but nonzero error")
                continue
            result[(group, component)] = 1.0 + error / value
    return result


def build(source: Path, output: Path, fit_root: Path) -> None:
    lines = source.read_text().splitlines()
    bin_lines = [line for line in lines if line.startswith("bin ")]
    process_lines = [line for line in lines if line.startswith("process ")]
    if len(bin_lines) < 2 or len(process_lines) < 1:
        raise ValueError(f"Could not find process table in {source}")

    bins = bin_lines[1].split()[1:]
    processes = process_lines[0].split()[1:]
    if len(bins) != len(processes):
        raise ValueError(f"Mismatched bin/process columns in {source}")

    eras = list(dict.fromkeys(name.removeprefix("y") for name in bins))
    factors = fit_uncertainties(fit_root, eras)
    nuisances: list[str] = []
    groups = list(dict.fromkeys(ERA_GROUPS[era][0] for era in eras))
    for group in groups:
        grouped_eras = {era for era in eras if ERA_GROUPS[era][0] == group}
        for component, (label, process) in COMPONENT_TO_PROCESS.items():
            factor = factors.get((group, component))
            if factor is None:
                continue
            columns = [
                f"{factor:.6f}"
                if b.removeprefix("y") in grouped_eras and p == process else "-"
                for b, p in zip(bins, processes)
            ]
            nuisances.append(f"DYVBFZ_fit_{label}_{group} lnN " + " ".join(columns))

    filtered = [
        line
        for line in lines
        if not (
            (line.startswith("DY_norm_") and " rateParam " in line)
            or line.startswith("DY012J_fit_")
            or line.startswith("DYVBFZ_fit_")
        )
    ]
    insertion = next(
        (i for i, line in enumerate(filtered) if " autoMCStats " in line), len(filtered)
    )
    filtered[insertion:insertion] = nuisances + ["------------"]
    output.write_text("\n".join(filtered) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--fit-root", type=Path, default=Path("reweights/dy_012j_reweight_skim_v4")
    )
    args = parser.parse_args()
    build(args.source, args.output, args.fit_root)


if __name__ == "__main__":
    main()
