#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Sweep transition biases and global threshold over the bundled (en) dataset.

Reports macro F1 per cell so the operator can pick a config that beats the
neutral baseline. One nullpii serve process is launched per cell — model
load (~10s) dominates, so keep the grid coarse.

Usage:
  python scripts/run_sweep.py            # default 7-cell sweep
  python scripts/run_sweep.py --grid     # 5×5 enter-bias × background grid
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval.adapters import nullpii_predictor
from nullpii_eval.datasets import load
from nullpii_eval.metrics import evaluate, macro_f1


def cell(samples, **kwargs) -> float:
    pred = nullpii_predictor(**kwargs)
    truths = [list(s.spans) for s in samples]
    preds = [list(pred(s.text).spans) for s in samples]
    return macro_f1(evaluate(preds, truths))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locale", default="en")
    parser.add_argument("--grid", action="store_true", help="run 5×5 enter×background grid")
    args = parser.parse_args()

    samples = list(load(args.locale).samples)
    print(f"sweep: locale={args.locale} n_samples={len(samples)}")
    results: list[dict] = []

    if args.grid:
        cells = [
            {"enter_bias": e, "background_bias": b}
            for e in (-1.0, -0.5, 0.0, 0.5, 1.0)
            for b in (-1.0, -0.5, 0.0, 0.5, 1.0)
        ]
    else:
        cells = [
            {},
            {"enter_bias": 0.5},
            {"enter_bias": 1.0},
            {"enter_bias": -0.5},
            {"background_bias": 0.5},
            {"background_bias": -0.5},
            {"continue_bias": 0.5},
            {"threshold": 0.5},
            {"threshold": 0.7},
            {"threshold": 0.9},
        ]

    for cfg in cells:
        f1 = cell(samples, **cfg)
        results.append({"cfg": cfg, "f1": f1})
        print(f"  cfg={cfg!s:60} f1={f1:.4f}")

    out = Path("/tmp/nullpii-eval/sweep.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"locale": args.locale, "n_samples": len(samples), "results": results}, indent=2),
        encoding="utf-8",
    )
    best = max(results, key=lambda r: r["f1"])
    print(f"\nbest cell: {best}")
    print(f"results → {out}")


if __name__ == "__main__":
    main()
