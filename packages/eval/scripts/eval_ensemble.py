#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""nullpii + GLiNER ensemble — 3 merge strategies + per-category error
analysis.

Tests whether combining nullpii (full pipeline) with GLiNER (zero-shot)
gives material F1 lift, and where each tool individually misses.

Predictors compared:
- nullpii (full pipeline + privacy-filter)
- GLiNER chunked (zero-shot multilingual + nullpii-style chunking)
- ensemble:union — both, longest-wins dedupe
- ensemble:nullpii_primary — nullpii first, GLiNER fills non-overlapping gaps
- ensemble:intersection — only spans both tools agree on
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import (
    gliner_chunked_predictor,
    nullpii_pool_predictor,
)
from nullpii_eval.datasets import Span, load
from nullpii_eval.metrics import evaluate, macro_f1


def f1_for(pred, samples) -> tuple[float, float, list]:
    truths = [list(s.spans) for s in samples]
    t0 = time.perf_counter()
    out = [list(pred(s.text).spans) for s in samples]
    el = time.perf_counter() - t0
    return macro_f1(evaluate(out, truths)), el, out


def f1_parallel(pred, samples, *, workers: int = 4) -> tuple[float, float, list]:
    """Pool-aware f1: shards samples across N threads (preserves order)."""
    truths = [list(s.spans) for s in samples]
    out: list[list] = [None] * len(samples)  # type: ignore[list-item]

    def _work(indices: list[int]) -> None:
        for i in indices:
            out[i] = list(pred(samples[i].text).spans)

    shards: list[list[int]] = [[] for _ in range(workers)]
    for i in range(len(samples)):
        shards[i % workers].append(i)

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_work, shards))
    el = time.perf_counter() - t0
    return macro_f1(evaluate(out, truths)), el, out


def _overlaps(a: Span, b: Span) -> bool:
    return a.start < b.end and b.start < a.end


def _merge_union(np_spans: list[Span], gl_spans: list[Span]) -> list[Span]:
    sorted_spans = sorted(np_spans + gl_spans, key=lambda s: (s.start, -s.end))
    out: list[Span] = []
    for s in sorted_spans:
        replaced = False
        for i in range(len(out) - 1, -1, -1):
            prev = out[i]
            if prev.end <= s.start:
                break
            if not _overlaps(prev, s):
                continue
            if prev.label != s.label:
                continue
            if (s.end - s.start) > (prev.end - prev.start):
                out[i] = s
            replaced = True
            break
        if not replaced:
            out.append(s)
    return sorted(out, key=lambda s: s.start)


def _merge_primary(np_spans: list[Span], gl_spans: list[Span]) -> list[Span]:
    added = list(np_spans)
    for g in gl_spans:
        if any(_overlaps(g, n) for n in np_spans):
            continue
        added.append(g)
    return sorted(added, key=lambda s: s.start)


def _merge_intersection(np_spans: list[Span], gl_spans: list[Span]) -> list[Span]:
    out: list[Span] = []
    for n in np_spans:
        for g in gl_spans:
            if n.label == g.label and _overlaps(n, g):
                out.append(n)
                break
    return out


def merge_f1(np_preds: list, gl_preds: list, samples, *, strategy: str) -> float:
    """In-memory merger — no model calls, just pure span arithmetic."""
    truths = [list(s.spans) for s in samples]
    merger = {
        "union": _merge_union,
        "nullpii_primary": _merge_primary,
        "intersection": _merge_intersection,
    }[strategy]
    merged = [merger(np_preds[i], gl_preds[i]) for i in range(len(samples))]
    return macro_f1(evaluate(merged, truths))


def _category_errors(preds: list[list[Span]], truths: list[list[Span]]) -> dict:
    """Compute per-category miss counts (true span had no predicted match)."""
    misses: dict[str, int] = defaultdict(int)
    totals: dict[str, int] = defaultdict(int)
    for ts, ps in zip(truths, preds):
        for t in ts:
            totals[t.label] += 1
            hit = any(
                p.label == t.label
                and p.start < t.end
                and t.start < p.end
                for p in ps
            )
            if not hit:
                misses[t.label] += 1
    return {
        label: {
            "total": totals[label],
            "missed": misses[label],
            "miss_rate": misses[label] / max(1, totals[label]),
        }
        for label in totals
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isotonic", type=int, default=1000)
    parser.add_argument("--presidio-syn", type=int, default=1000)
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parent.parent / "results" / "ensemble.json"
        ),
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = (
        out_path.parent / f"ensemble-{datetime.now():%Y%m%d-%H%M%S}.log"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("ensemble")
    log.info("starting ensemble eval; out=%s", out_path)

    runs: list[tuple[str, list]] = []
    for loc in ("en", "it", "de", "fr", "es"):
        runs.append((f"bundled-{loc}", list(load(loc).samples)))
    runs.append(("long-prompts-en", list(load("long-prompts-en").samples)))
    iso_n = None if args.isotonic == 0 else args.isotonic
    for loc in ("en", "it", "de", "fr"):
        runs.append((f"isotonic-{loc}", list(public_datasets._load_isotonic(iso_n, lang=loc).samples)))
    if args.presidio_syn > 0:
        runs.append((
            "presidio-synthetic",
            list(public_datasets._load_presidio_synthetic(args.presidio_syn).samples),
        ))
    log.info("datasets: %d, samples: %d", len(runs), sum(len(s) for _, s in runs))

    log.info("loading predictors…")
    np_pred = nullpii_pool_predictor(pool_size=4, threads_each=2)
    gl_pred = gliner_chunked_predictor(threshold=0.5)
    log.info("  ready")

    out: dict = {"_meta": {"started": datetime.now().isoformat()}}
    for idx, (name, samples) in enumerate(runs, start=1):
        truths = [list(s.spans) for s in samples]
        log.info("[%d/%d] %s n=%d — running base predictors in parallel", idx, len(runs), name, len(samples))
        # Run nullpii (pool-sharded) and GLiNER concurrently; precompute
        # outputs once, then apply merger logic in-memory for each strategy.
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            fut_np = ex.submit(f1_parallel, np_pred, samples, workers=4)
            fut_gl = ex.submit(f1_for, gl_pred, samples)
            np_f1, np_el, np_preds = fut_np.result()
            gl_f1, gl_el, gl_preds = fut_gl.result()
        # Mergers are pure span math, microseconds.
        t0 = time.perf_counter()
        u_f1 = merge_f1(np_preds, gl_preds, samples, strategy="union")
        p_f1 = merge_f1(np_preds, gl_preds, samples, strategy="nullpii_primary")
        i_f1 = merge_f1(np_preds, gl_preds, samples, strategy="intersection")
        merge_el = time.perf_counter() - t0
        out[name] = {
            "n": len(samples),
            "nullpii_f1": np_f1,
            "gliner_f1": gl_f1,
            "ensemble_union_f1": u_f1,
            "ensemble_primary_f1": p_f1,
            "ensemble_intersect_f1": i_f1,
            "nullpii_s": np_el,
            "gliner_s": gl_el,
            "merge_s": merge_el,
            "category_errors_nullpii": _category_errors(np_preds, truths),
            "category_errors_gliner": _category_errors(gl_preds, truths),
        }
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        log.info(
            "  np=%.4f gl=%.4f union=%.4f primary=%.4f intersect=%.4f (np_s=%.1f gl_s=%.1f)",
            np_f1, gl_f1, u_f1, p_f1, i_f1, np_el, gl_el,
        )

    out["_meta"]["finished"] = datetime.now().isoformat()
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    log.info("complete — results → %s", out_path)


if __name__ == "__main__":
    main()
