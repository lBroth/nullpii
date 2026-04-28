#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Per-category confusion matrix on the iter-22 best config.

For each of the 8 PII labels:
  TP = predicted span overlaps a same-label truth span (IoU >= 0.5)
  FP = predicted span has no matching truth span
  FN = truth span has no matching predicted span
  Reports precision, recall, F1, support per label across all datasets.

Insight-only — no F1 change, just reveals which categories cap the
overall score and where the ensemble bleeds.
"""
from __future__ import annotations

import concurrent.futures
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import (
    DEFAULT_REGEX_PATTERNS,
    boundary_refined_predictor,
    gliner_chunked_predictor,
    multi_ensemble_predictor,
    nullpii_pool_predictor,
    regex_recognizer_predictor,
)
from nullpii_eval.datasets import Sample, Span, load


def load_nullpii_bench() -> dict[str, list[Sample]]:
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-bench.jsonl"
    by: dict[str, list[Sample]] = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            by.setdefault(row["subset"], []).append(Sample(row["text"], spans))
    return by


def _iou(a: Span, b: Span) -> float:
    inter_lo = max(a.start, b.start)
    inter_hi = min(a.end, b.end)
    inter = max(0, inter_hi - inter_lo)
    union = (a.end - a.start) + (b.end - b.start) - inter
    return inter / union if union > 0 else 0.0


def main() -> None:
    np_pred = nullpii_pool_predictor(pool_size=4, threads_each=4, backend="cpu", variant="fp16")
    gl_pred = gliner_chunked_predictor(threshold=0.8)
    rg_pred = regex_recognizer_predictor(patterns=DEFAULT_REGEX_PATTERNS)
    ens = multi_ensemble_predictor(
        predictors=[np_pred, gl_pred, rg_pred], strategy="primary",
    )
    ens = boundary_refined_predictor(inner=ens)

    runs: list[tuple[str, list[Sample]]] = []
    for subset, samples in load_nullpii_bench().items():
        if subset == "adversarial":
            continue
        runs.append((f"bench-{subset}", samples))
    for loc in ("en", "it", "de", "fr"):
        runs.append((f"isotonic-{loc}", list(public_datasets._load_isotonic(1000, lang=loc).samples)))

    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)

    print(f"Running ensemble on {sum(len(s) for _, s in runs)} samples…")
    t0 = time.perf_counter()
    for name, samples in runs:
        out: list[list[Span]] = [None] * len(samples)  # type: ignore[list-item]

        def _work(idx, _samples=samples, _out=out):
            for i in idx:
                _out[i] = list(ens(_samples[i].text).spans)

        shards: list[list[int]] = [[] for _ in range(4)]
        for i in range(len(samples)):
            shards[i % 4].append(i)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            list(ex.map(_work, shards))

        for sample, preds in zip(samples, out):
            truths_remaining = list(sample.spans)
            for p in preds:
                matched_idx = -1
                for idx, t in enumerate(truths_remaining):
                    if t.label == p.label and _iou(p, t) >= 0.5:
                        matched_idx = idx
                        break
                if matched_idx >= 0:
                    tp[p.label] += 1
                    truths_remaining.pop(matched_idx)
                else:
                    fp[p.label] += 1
            for t in truths_remaining:
                fn[t.label] += 1
        print(f"  {name} ({len(samples)} samples) done")
    elapsed = time.perf_counter() - t0
    print(f"\ntotal: {elapsed:.1f}s")

    labels = sorted(set(tp) | set(fp) | set(fn))
    print()
    print(f"{'label':<20} {'TP':>5} {'FP':>5} {'FN':>5} {'support':>8} {'P':>7} {'R':>7} {'F1':>7}")
    print("-" * 70)
    macro_f1 = 0.0
    n_labels_with_support = 0
    for lbl in labels:
        tps, fps, fns = tp[lbl], fp[lbl], fn[lbl]
        support = tps + fns
        prec = tps / (tps + fps) if (tps + fps) else 0.0
        rec = tps / (tps + fns) if (tps + fns) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        if support > 0:
            macro_f1 += f1
            n_labels_with_support += 1
        print(f"{lbl:<20} {tps:>5} {fps:>5} {fns:>5} {support:>8} {prec:>7.4f} {rec:>7.4f} {f1:>7.4f}")
    print("-" * 70)
    print(f"{'macro F1':<20} {'':>5} {'':>5} {'':>5} {'':>8} {'':>7} {'':>7} {macro_f1/max(1,n_labels_with_support):>7.4f}")


if __name__ == "__main__":
    main()
