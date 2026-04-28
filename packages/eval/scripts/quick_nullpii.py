#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fast nullpii-only smoke against the merged nullpii-bench dataset
+ a 1k Isotonic-en sample. Used inside the loop "commit / new branch
/ test / keep-or-revert" iteration cycle.

Outputs a single avg PII F1 number to stdout (and per-dataset breakdown).
Takes ~30-60s wall-clock, depending on hardware.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import nullpii_pool_predictor
from nullpii_eval.datasets import Sample, Span, load
from nullpii_eval.metrics import evaluate, macro_f1


def load_nullpii_bench() -> dict[str, list[Sample]]:
    """Group merged dataset rows by subset for per-subset reporting."""
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-bench.jsonl"
    by_subset: dict[str, list[Sample]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            sample = Sample(row["text"], spans)
            by_subset.setdefault(row["subset"], []).append(sample)
    return by_subset


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isotonic", type=int, default=1000)
    parser.add_argument(
        "--enter-bias", type=float, default=None,
        help="transitionBiases.enterSpan (default: 0)",
    )
    parser.add_argument(
        "--background-bias", type=float, default=None,
        help="transitionBiases.background (default: 0)",
    )
    parser.add_argument(
        "--continue-bias", type=float, default=None,
        help="transitionBiases.continueSpan (default: 0)",
    )
    parser.add_argument(
        "--threshold", type=float, default=None,
        help="global confidence threshold (default: 0)",
    )
    parser.add_argument("--pool-size", type=int, default=4)
    args = parser.parse_args()

    np_pred = nullpii_pool_predictor(
        pool_size=args.pool_size,
        threads_each=2,
        backend="cpu",
        variant="fp16",
        enter_bias=args.enter_bias,
        background_bias=args.background_bias,
        continue_bias=args.continue_bias,
        threshold=args.threshold,
    )

    runs: list[tuple[str, list[Sample]]] = []
    for subset, samples in load_nullpii_bench().items():
        runs.append((f"bench-{subset}", samples))
    if args.isotonic > 0:
        for loc in ("en", "it", "de", "fr"):
            runs.append((
                f"isotonic-{loc}",
                list(public_datasets._load_isotonic(args.isotonic, lang=loc).samples),
            ))

    print(
        f"{'dataset':<22} {'n':>5} {'wall':>7} {'F1':>7}",
    )
    print("-" * 45)
    f1_values: list[float] = []
    n_total = 0
    t_all = time.perf_counter()
    for name, samples in runs:
        truths = [list(s.spans) for s in samples]
        t0 = time.perf_counter()
        preds = [list(np_pred(s.text).spans) for s in samples]
        el = time.perf_counter() - t0
        f1 = macro_f1(evaluate(preds, truths))
        print(f"{name:<22} {len(samples):>5} {el:>7.1f} {f1:>7.4f}")
        # Adversarial subset has no positive PII — F1 collapses to 0 with
        # any false positive. Track it separately, exclude from avg.
        if name != "bench-adversarial":
            f1_values.append(f1)
        n_total += len(samples)
    print("-" * 45)
    avg = sum(f1_values) / max(1, len(f1_values))
    wall = time.perf_counter() - t_all
    print(f"{'AVG PII (excl adv)':<22} {n_total:>5} {wall:>7.1f} {avg:>7.4f}")
    print(
        f"\nCONFIG enter={args.enter_bias} bg={args.background_bias} "
        f"continue={args.continue_bias} threshold={args.threshold}",
    )


if __name__ == "__main__":
    main()
