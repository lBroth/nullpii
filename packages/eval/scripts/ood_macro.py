#!/usr/bin/env python3
"""Compute the OOD-7 headline macro-F1 from a bench `matrix.json`.

The held-out OOD headline quoted in the top-level README used to be a
hand-maintained number. Nothing computed it, so the root README and
`packages/eval/datasets/README.md` drifted apart: the root enumerated
seven datasets (0.7784) while the datasets README claimed five (0.7656),
a 0.0128 gap that silently invalidated any regression gate measured
against the wrong baseline.

This script is the single source of truth. `OOD_7` below is the set;
change it here and nowhere else.

Membership criterion: externally authored AND no part of it entered
nullpii's training distribution. The `-heldout` suffix means rows sliced
above nullpii's own training offsets (`_AI4_HELDOUT_OFFSET` /
`_ISOTONIC_HELDOUT_ROW_OFFSET` in `bench_full.py`) — it carries no
held-out guarantee for any other tool in the matrix.

Usage:
  python ood_macro.py packages/eval/published-bench/matrix.json
  python ood_macro.py matrix.json --tool nullpii-bare
  python ood_macro.py a/matrix.json --baseline b/matrix.json   # A/B delta

Exits non-zero if any OOD-7 cell is missing or did not complete, so a
truncated bench run can never be reported as a headline.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# The held-out OOD headline set. Order is the reporting order.
OOD_7 = (
    "presidio-synthetic",
    "isotonic-en-heldout",
    "isotonic-de-heldout",
    "isotonic-fr-heldout",
    "isotonic-it-heldout",
    "ai4privacy-300k-heldout",
    "tab-echr",
)

_OK_STATUS = "OK"


def ood_cells(matrix: dict, tool: str) -> dict[str, float]:
    """Per-dataset F1 for `tool` across OOD-7. Raises if any cell is unusable."""
    cells: dict[str, float] = {}
    missing: list[str] = []
    for key in OOD_7:
        cell = matrix.get(key, {}).get(tool)
        if cell is None:
            missing.append(f"{key}: absent")
            continue
        status = cell.get("status", _OK_STATUS)
        if status != _OK_STATUS:
            missing.append(f"{key}: status={status}")
            continue
        f1 = cell.get("f1")
        if f1 is None:
            missing.append(f"{key}: no f1")
            continue
        cells[key] = float(f1)
    if missing:
        raise SystemExit(
            f"OOD-7 incomplete for tool '{tool}' — refusing to report a headline:\n  "
            + "\n  ".join(missing)
        )
    return cells


def ood_macro(matrix: dict, tool: str) -> float:
    """Unweighted mean of the seven OOD-7 per-dataset macro-F1 scores."""
    cells = ood_cells(matrix, tool)
    return sum(cells.values()) / len(cells)


def _load(path: Path) -> dict:
    if not path.exists():
        raise SystemExit(f"no such matrix: {path}")
    return json.loads(path.read_text())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("matrix", type=Path, help="path to matrix.json")
    ap.add_argument("--tool", default="nullpii", help="tool column (default: nullpii)")
    ap.add_argument("--baseline", type=Path, default=None,
                    help="second matrix.json to diff against (A/B mode)")
    args = ap.parse_args()

    cells = ood_cells(_load(args.matrix), args.tool)
    macro = sum(cells.values()) / len(cells)

    if args.baseline is None:
        for key, f1 in cells.items():
            print(f"  {key:26} {f1:.4f}")
        print(f"\nOOD-7 macro [{args.tool}] = {macro:.4f}  (n={len(cells)} datasets)")
        return

    base = ood_cells(_load(args.baseline), args.tool)
    base_macro = sum(base.values()) / len(base)
    print(f"  {'dataset':26} {'baseline':>9} {'candidate':>10} {'delta':>9}")
    for key in OOD_7:
        delta = cells[key] - base[key]
        flag = "  " if abs(delta) < 5e-4 else (" +" if delta > 0 else " -")
        print(f"  {key:26} {base[key]:9.4f} {cells[key]:10.4f} {delta:+9.4f}{flag}")
    delta = macro - base_macro
    print(f"\n  {'OOD-7 macro':26} {base_macro:9.4f} {macro:10.4f} {delta:+9.4f}")
    if delta < 0:
        print("\nREGRESSION — candidate is worse than baseline.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
