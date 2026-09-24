#!/usr/bin/env python3
"""Apply the temporary VBF-Z fit normalizations to DY component ROOT files."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
import sys

REPOSITORY = Path(__file__).resolve().parents[1]
if str(REPOSITORY) not in sys.path:
    sys.path.insert(0, str(REPOSITORY))

from common.jet_component_splitting import pu_hard_component_style


PATCH_MARKER = "__temporary_dy_component_reweight__"
FACTOR_FILE = Path(__file__).with_name("rew_patch_factors.json")
DY_COMPONENT_SCALES = json.loads(FACTOR_FILE.read_text())
COMPONENT_PARAMETER = {
    "2J Hard": "2J Hard",
    "VBF Hard": "2J Hard",
    "1J PU": "1J PU",
    "2J PU1": "1J PU",
    "VBF PU1": "1J PU",
    "2J PU2": "2J PU",
    "VBF PU2": "2J PU",
}


def dy_component_scale(sample_name: str, era: str) -> float:
    """Return the patch factor; non-DY, 0J and 1J-hard return one."""
    component = pu_hard_component_style(sample_name)
    if component is None or component[0] != "DY":
        return 1.0

    era_text = str(era).removeprefix("Run3_")
    if "_" in era_text:
        return 1.0
    year = next(
        (year for year in DY_COMPONENT_SCALES if era_text.startswith(year)),
        None,
    )
    parameter = COMPONENT_PARAMETER.get(component[1])
    if year is None or parameter is None:
        return 1.0
    return DY_COMPONENT_SCALES[year][parameter]


def root_file_has_patch(root_file) -> bool:
    """Check whether a ROOT file was already rewritten by this script."""
    return bool(root_file.Get(PATCH_MARKER))


def _scale_directory(directory, factor, root_module) -> int:
    scaled = 0
    for key in list(directory.GetListOfKeys()):
        obj = key.ReadObj()
        if obj.InheritsFrom("TDirectory"):
            scaled += _scale_directory(obj, factor, root_module)
        elif obj.InheritsFrom("TH1"):
            obj.Scale(factor)
            directory.cd()
            obj.Write(key.GetName(), root_module.TObject.kOverwrite)
            scaled += 1
    return scaled


def reweight_root_file(path: Path, sample_name: str, era: str) -> tuple[float, int]:
    """Scale every histogram in one component file and add a safety marker."""
    import ROOT

    factor = dy_component_scale(sample_name, era)
    if factor == 1.0:
        return factor, 0

    root_file = ROOT.TFile.Open(str(path), "UPDATE")
    if not root_file or root_file.IsZombie():
        raise OSError(f"cannot update ROOT file {path}")
    if root_file_has_patch(root_file):
        root_file.Close()
        raise RuntimeError(f"{path} already contains the {PATCH_MARKER} marker")

    scaled = _scale_directory(root_file, factor, ROOT)
    root_file.cd()
    marker = ROOT.TNamed(PATCH_MARKER, f"era={era};sample={sample_name};factor={factor}")
    marker.Write(PATCH_MARKER, ROOT.TObject.kOverwrite)
    root_file.Close()
    return factor, scaled


def _input_files(inputs: list[Path]) -> list[Path]:
    files = []
    for source in inputs:
        if source.is_dir():
            files.extend(sorted(source.glob("*.root")))
        elif source.suffix == ".root":
            files.append(source)
        else:
            raise ValueError(f"not a ROOT file or directory: {source}")
    return list(dict.fromkeys(files))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="ROOT files or directories")
    parser.add_argument("--era", required=True, help="e.g. 2024 or Run3_2024")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--output-dir", type=Path)
    destination.add_argument("--in-place", action="store_true")
    parser.add_argument(
        "--overwrite", action="store_true", help="overwrite existing output copies"
    )
    args = parser.parse_args()

    try:
        files = _input_files(args.inputs)
    except ValueError as error:
        parser.error(str(error))
    if not files:
        parser.error("no ROOT files found")
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)

    for source in files:
        sample_name = source.stem
        factor = dy_component_scale(sample_name, args.era)
        target = source
        if args.output_dir:
            target = args.output_dir / source.name
            if target.exists() and not args.overwrite:
                parser.error(f"output exists (use --overwrite): {target}")
            shutil.copy2(source, target)
        if factor == 1.0:
            action = "copied unchanged" if args.output_dir else "left unchanged"
            print(f"[SKIP] {target}: no patch factor, {action}")
            continue
        applied_factor, count = reweight_root_file(target, sample_name, args.era)
        print(f"[OK] {target}: scaled {count} histograms by {applied_factor}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
