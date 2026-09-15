#!/usr/bin/env python3
"""Link the non-DY raw histograms of one campaign into another.

The custom DY reweights are applied only to datasets that
``common.apply_custom_weights.is_dy_dataset`` recognises, so every other
dataset gives byte-identical histograms with and without them. Producing those
twice would double the grid cost for no information: produce them once in the
weighted campaign and link them here, so the unweighted campaign still has the
same total background.

Jet-component files inherit their dataset name, so ``DYto2Mu_..._2J_Hard.root``
is filtered out by the same predicate as its parent.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(os.environ.get("ANALYSIS_PATH", Path(__file__).resolve().parents[1]))
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from common.apply_custom_weights import is_dy_dataset  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, required=True, help="Central/<era> of the weighted campaign"
    )
    parser.add_argument(
        "--destination", type=Path, required=True, help="Central/<era> of the other campaign"
    )
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy instead of symlinking, for filesystems without symlinks.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.source.is_dir():
        raise NotADirectoryError(f"Source directory does not exist: {args.source}")

    candidates = sorted(args.source.glob("*.root"))
    if not candidates:
        raise FileNotFoundError(f"No ROOT files in {args.source}")
    selected = [path for path in candidates if not is_dy_dataset(path.stem)]
    skipped = len(candidates) - len(selected)
    print(f"{args.source}: {len(selected)} non-DY files, {skipped} DY files skipped")

    if not args.dry_run:
        args.destination.mkdir(parents=True, exist_ok=True)

    linked = replaced = kept = 0
    for source in selected:
        target = args.destination / source.name
        if target.is_symlink() and os.readlink(target) == str(source):
            kept += 1
            continue
        if target.exists() or target.is_symlink():
            # A real file produced by the other campaign wins: it may have been
            # made with different weights and must not be silently replaced.
            if not target.is_symlink():
                print(f"    keeping existing file, not a link: {target.name}")
                kept += 1
                continue
            if not args.dry_run:
                target.unlink()
            replaced += 1
        if args.dry_run:
            linked += 1
            continue
        if args.copy:
            import shutil

            shutil.copy2(source, target)
        else:
            target.symlink_to(source)
        linked += 1

    verb = "would link" if args.dry_run else "linked"
    print(
        f"{args.destination}: {verb} {linked} file(s), "
        f"{replaced} stale link(s) refreshed, {kept} left untouched"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
