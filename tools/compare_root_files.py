#!/usr/bin/env python3
"""Compare the Events trees of two ROOT files."""

from __future__ import annotations

import argparse
import math
from pathlib import Path


def value_equal(left, right, tolerance: float) -> bool:
    left_is_sequence = isinstance(left, (list, tuple))
    right_is_sequence = isinstance(right, (list, tuple))
    if left_is_sequence or right_is_sequence:
        if left_is_sequence != right_is_sequence:
            return False
        if len(left) != len(right):
            return False
        return all(value_equal(a, b, tolerance) for a, b in zip(left, right))
    if isinstance(left, float) and isinstance(right, float):
        if math.isnan(left) and math.isnan(right):
            return True
        return math.isclose(left, right, rel_tol=tolerance, abs_tol=tolerance)
    return left == right


def branch_value(branch, entry: int):
    branch.GetEntry(entry)
    leaf = branch.GetLeaf(branch.GetName())
    if leaf and leaf.GetLen() == 1:
        return leaf.GetValue()
    if leaf:
        return [leaf.GetValue(index) for index in range(leaf.GetLen())]
    return None


def compare(path_a: Path, path_b: Path, tree_name: str, max_events: int, tolerance: float) -> int:
    import ROOT

    file_a = ROOT.TFile.Open(str(path_a), "READ")
    file_b = ROOT.TFile.Open(str(path_b), "READ")
    if not file_a or file_a.IsZombie():
        raise OSError(f"cannot open {path_a}")
    if not file_b or file_b.IsZombie():
        raise OSError(f"cannot open {path_b}")

    tree_a = file_a.Get(tree_name)
    tree_b = file_b.Get(tree_name)
    if not tree_a or not tree_b:
        raise KeyError(f"tree {tree_name!r} is missing from one of the files")

    branches_a = {branch.GetName(): branch for branch in tree_a.GetListOfBranches()}
    branches_b = {branch.GetName(): branch for branch in tree_b.GetListOfBranches()}
    names_a = set(branches_a)
    names_b = set(branches_b)
    common = sorted(names_a & names_b)
    entries_a = int(tree_a.GetEntries())
    entries_b = int(tree_b.GetEntries())
    entries_to_check = min(entries_a, entries_b)
    if max_events > 0:
        entries_to_check = min(entries_to_check, max_events)

    print(f"A: {path_a}")
    print(f"B: {path_b}")
    print(f"Tree: {tree_name}")
    print(f"Entries: A={entries_a}, B={entries_b}")
    print(f"Branches: A={len(names_a)}, B={len(names_b)}, common={len(common)}")
    only_a = sorted(names_a - names_b)
    only_b = sorted(names_b - names_a)
    if only_a:
        print(f"Only in A ({len(only_a)}; first 30): " + ", ".join(only_a[:30]))
    if only_b:
        print(f"Only in B ({len(only_b)}; first 30): " + ", ".join(only_b[:30]))

    mismatches = []
    for entry in range(entries_to_check):
        for name in common:
            value_a = branch_value(branches_a[name], entry)
            value_b = branch_value(branches_b[name], entry)
            if not value_equal(value_a, value_b, tolerance):
                mismatches.append((entry, name, value_a, value_b))
                if len(mismatches) >= 20:
                    break
        if len(mismatches) >= 20:
            break

    print(f"Compared entries: {entries_to_check}")
    if mismatches:
        print(f"Value mismatches: at least {len(mismatches)} (first 20 shown)")
        for entry, name, value_a, value_b in mismatches:
            print(f"  entry {entry}, {name}: A={value_a!r}, B={value_b!r}")
    else:
        print("Value mismatches: none found")

    structurally_equal = entries_a == entries_b and names_a == names_b
    contents_equal = not mismatches and entries_a == entries_b
    file_a.Close()
    file_b.Close()
    return 0 if structurally_equal and contents_equal else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file_a", type=Path)
    parser.add_argument("file_b", type=Path)
    parser.add_argument("--tree", default="Events")
    parser.add_argument(
        "--max-events",
        type=int,
        default=-1,
        help="compare at most this many entries; default: all entries",
    )
    parser.add_argument(
        "--tolerance",
        type=float,
        default=1e-6,
        help="absolute and relative tolerance for floating-point values",
    )
    args = parser.parse_args()
    if args.max_events == 0 or args.max_events < -1:
        parser.error("--max-events must be -1 or a positive integer")
    if args.tolerance < 0:
        parser.error("--tolerance must be non-negative")
    return compare(args.file_a, args.file_b, args.tree, args.max_events, args.tolerance)


if __name__ == "__main__":
    raise SystemExit(main())