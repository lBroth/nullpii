#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Fast ensemble smoke against nullpii-bench + 1k Isotonic.

Configurable via CLI:
  --tools     comma list from {nullpii, gliner, presidio, deberta, piiranha, regex}
  --strategy  primary | union  (other strategies tested + dropped, see CLEANUP_TODO)
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
    deberta_pii_predictor,
    gliner_chunked_predictor,
    multi_ensemble_predictor,
    nullpii_pool_predictor,
    piiranha_predictor,
    presidio_predictor,
    regex_recognizer_predictor,
)
from nullpii_eval.datasets import Sample, Span
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--tools", default="nullpii,gliner,regex",
        help="comma list from {nullpii, gliner, presidio, deberta, piiranha, regex}",
    )
    parser.add_argument(
        "--strategy", default="primary", choices=["primary", "union"],
        help="primary = winner-take-overlap (production default); union = recall-tilted",
    )
    parser.add_argument("--gliner-threshold", type=float, default=0.8)
    parser.add_argument("--isotonic", type=int, default=1000)
    parser.add_argument("--pool-size", type=int, default=4)
    parser.add_argument("--threads-each", type=int, default=4)
    parser.add_argument(
        "--no-refine-boundaries", dest="refine_boundaries",
        action="store_false", default=True,
        help="disable boundary trim (default: enabled)",
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
        f"\n{'dataset':<22} {'n':>5} {'wall':>6} {'tput':>5} {'p50':>5} {'p95':>5} {'F1':>7}",
    )
    print("-" * 60)
    f1_values: list[float] = []
    n_total = 0
    workers = args.pool_size
    total_wall = 0.0
    all_latencies: list[float] = []
    t_all = time.perf_counter()
    for name, samples in runs:
        truths = [list(s.spans) for s in samples]
        out: list[list] = [None] * len(samples)  # type: ignore[list-item]
        latencies: list[float] = []
        latencies_lock = __import__("threading").Lock()

        def _work(indices: list[int], _samples=samples, _out=out, _lat=latencies) -> None:
            local: list[float] = []
            for i in indices:
                t0 = time.perf_counter()
                _out[i] = list(ens(_samples[i].text).spans)
                local.append((time.perf_counter() - t0) * 1000)
            with latencies_lock:
                _lat.extend(local)

        shards: list[list[int]] = [[] for _ in range(workers)]
        for i in range(len(samples)):
            shards[i % workers].append(i)
        t0 = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
            list(ex.map(_work, shards))
        el = time.perf_counter() - t0
        tput_ms = el * 1000 / max(1, len(samples))
        latencies.sort()
        p50 = latencies[len(latencies) // 2] if latencies else 0.0
        p95_idx = int(len(latencies) * 0.95)
        p95 = latencies[min(p95_idx, len(latencies) - 1)] if latencies else 0.0
        f1 = macro_f1(evaluate(out, truths))
        print(
            f"{name:<22} {len(samples):>5} {el:>6.1f} {tput_ms:>5.1f} {p50:>5.0f} {p95:>5.0f} {f1:>7.4f}",
        )
        if name != "bench-adversarial":
            f1_values.append(f1)
        n_total += len(samples)
        total_wall += el
        all_latencies.extend(latencies)
    print("-" * 60)
    avg = sum(f1_values) / max(1, len(f1_values))
    wall = time.perf_counter() - t_all
    tput_avg = total_wall * 1000 / max(1, n_total)
    all_latencies.sort()
    p50_all = all_latencies[len(all_latencies) // 2] if all_latencies else 0.0
    p95_all = all_latencies[int(len(all_latencies) * 0.95)] if all_latencies else 0.0
    print(
        f"{'AVG PII (excl adv)':<22} {n_total:>5} {wall:>6.1f} {tput_avg:>5.1f} "
        f"{p50_all:>5.0f} {p95_all:>5.0f} {avg:>7.4f}",
    )
    print()
    print("legend: wall=dataset wall(s), tput=ms/req parallel, p50/p95=single-call latency ms")
    print(f"\nCONFIG tools={tools} strategy={args.strategy} gliner_th={args.gliner_threshold}")


def _wrap_batch(batch_pred):
    """Adapt list-in / list-out batch predictor to single-call interface."""
    def _single(text):
        return batch_pred([text])[0]
    return _single


if __name__ == "__main__":
    main()
