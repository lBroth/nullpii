#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fast ensemble smoke against nullpii-bench + 1k Isotonic.

Configurable via CLI:
  --tools     comma list from {nullpii, gliner, presidio, deberta, piiranha}
  --strategy  union | primary | intersection | majority | category-routing
  --gliner-threshold N

Prints per-dataset F1 + AVG. ~2-3 min wall-clock.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import (
    DEFAULT_REGEX_PATTERNS,
    boundary_refined_predictor,
    category_routing_predictor,
    deberta_pii_predictor,
    gliner_chunked_predictor,
    multi_ensemble_predictor,
    nullpii_pool_predictor,
    piiranha_predictor,
    presidio_predictor,
    regex_recognizer_predictor,
)
from nullpii_eval.datasets import Sample, Span, load
from nullpii_eval.metrics import evaluate, macro_f1


def load_nullpii_bench() -> dict[str, list[Sample]]:
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-bench.jsonl"
    by_subset: dict[str, list[Sample]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            by_subset.setdefault(row["subset"], []).append(Sample(row["text"], spans))
    return by_subset


# Per-category routing derived from miss-rate analysis (lower is better).
DEFAULT_ROUTING = {
    "private_url":     "gliner",
    "private_person":  "gliner",
    "private_phone":   "gliner",
    "private_email":   "nullpii",
    "private_address": "presidio",
    "private_date":    "presidio",
    "account_number":  "presidio",
    "secret":          "gliner",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tools", default="nullpii,gliner,presidio",
        help="comma list from {nullpii, gliner, presidio, deberta, piiranha}",
    )
    parser.add_argument(
        "--strategy", default="primary",
        choices=["union", "primary", "intersection", "majority", "category-routing", "category"],
    )
    parser.add_argument("--gliner-threshold", type=float, default=0.5)
    parser.add_argument("--isotonic", type=int, default=1000)
    parser.add_argument("--pool-size", type=int, default=4)
    parser.add_argument("--threads-each", type=int, default=4)
    parser.add_argument(
        "--refine-boundaries", action="store_true",
        help="trim trailing punct/whitespace from final spans",
    )
    args = parser.parse_args()

    tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    print(f"tools: {tools}, strategy: {args.strategy}, gliner_th: {args.gliner_threshold}")

    builders = {
        "nullpii": lambda: nullpii_pool_predictor(
            pool_size=args.pool_size, threads_each=args.threads_each,
            backend="cpu", variant="fp16",
        ),
        "gliner":  lambda: gliner_chunked_predictor(threshold=args.gliner_threshold),
        "presidio": lambda: presidio_predictor(),
        "deberta": lambda: _wrap_batch(deberta_pii_predictor(device="cpu", batch_size=16)),
        "piiranha": lambda: _wrap_batch(piiranha_predictor(device="cpu", batch_size=16)),
        "regex": lambda: regex_recognizer_predictor(patterns=DEFAULT_REGEX_PATTERNS),
    }
    preds_by_name: dict[str, object] = {}
    for t in tools:
        if t not in builders:
            raise SystemExit(f"unknown tool: {t}")
        print(f"  loading {t}…")
        preds_by_name[t] = builders[t]()

    if args.strategy in {"category-routing", "category"}:
        routing = {label: preds_by_name[tool] for label, tool in DEFAULT_ROUTING.items() if tool in preds_by_name}
        fallback = preds_by_name.get("nullpii") or next(iter(preds_by_name.values()))
        ens = category_routing_predictor(routing=routing, fallback=fallback)
        print(f"  routing: {DEFAULT_ROUTING}")
    else:
        ens = multi_ensemble_predictor(
            predictors=[preds_by_name[t] for t in tools],
            strategy=args.strategy,
        )
    if args.refine_boundaries:
        ens = boundary_refined_predictor(inner=ens)
        print("  boundary-refinement enabled")

    runs: list[tuple[str, list[Sample]]] = []
    for subset, samples in load_nullpii_bench().items():
        runs.append((f"bench-{subset}", samples))
    if args.isotonic > 0:
        for loc in ("en", "it", "de", "fr"):
            runs.append((f"isotonic-{loc}", list(public_datasets._load_isotonic(args.isotonic, lang=loc).samples)))

    print(
        f"\n{'dataset':<22} {'n':>5} {'wall':>7} {'ms/req':>7} {'F1':>7}",
    )
    print("-" * 53)
    f1_values: list[float] = []
    n_total = 0
    workers = args.pool_size
    total_wall = 0.0
    t_all = time.perf_counter()
    for name, samples in runs:
        truths = [list(s.spans) for s in samples]
        out: list[list] = [None] * len(samples)  # type: ignore[list-item]

        def _work(indices: list[int], _samples=samples, _out=out) -> None:
            for i in indices:
                _out[i] = list(ens(_samples[i].text).spans)

        shards: list[list[int]] = [[] for _ in range(workers)]
        for i in range(len(samples)):
            shards[i % workers].append(i)
        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_work, shards))
        el = time.perf_counter() - t0
        # Per-request latency under parallel dispatch — reflects throughput
        # the client sees, not wall_per_sample of an isolated call.
        ms_per_req = el * 1000 / max(1, len(samples))
        f1 = macro_f1(evaluate(out, truths))
        print(f"{name:<22} {len(samples):>5} {el:>7.1f} {ms_per_req:>7.1f} {f1:>7.4f}")
        if name != "bench-adversarial":
            f1_values.append(f1)
        n_total += len(samples)
        total_wall += el
    print("-" * 53)
    avg = sum(f1_values) / max(1, len(f1_values))
    wall = time.perf_counter() - t_all
    avg_ms = total_wall * 1000 / max(1, n_total)
    print(
        f"{'AVG PII (excl adv)':<22} {n_total:>5} {wall:>7.1f} {avg_ms:>7.1f} {avg:>7.4f}",
    )
    print(f"\nCONFIG tools={tools} strategy={args.strategy} gliner_th={args.gliner_threshold}")


def _wrap_batch(batch_pred):
    """Adapt list-in / list-out batch predictor to single-call interface."""
    def _single(text):
        return batch_pred([text])[0]
    return _single


if __name__ == "__main__":
    main()
