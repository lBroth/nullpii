# SPDX-License-Identifier: Apache-2.0
"""Span-level precision / recall / F1 with exact or partial (IoU) matching."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .datasets import Span


@dataclass(frozen=True, slots=True)
class CategoryMetrics:
    label: str
    tp: int
    fp: int
    fn: int

    @property
    def precision(self) -> float:
        denom = self.tp + self.fp
        return self.tp / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.tp + self.fn
        return self.tp / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0


def _exact_match(a: Span, b: Span) -> bool:
    return a.label == b.label and a.start == b.start and a.end == b.end


def _overlap_iou(a: Span, b: Span) -> float:
    if a.label != b.label:
        return 0.0
    inter = max(0, min(a.end, b.end) - max(a.start, b.start))
    if inter == 0:
        return 0.0
    union = (a.end - a.start) + (b.end - b.start) - inter
    return inter / union if union > 0 else 0.0


def evaluate(
    predictions: list[list[Span]],
    truths: list[list[Span]],
    *,
    policy: str = "partial",
    iou_threshold: float = 0.5,
) -> dict[str, CategoryMetrics]:
    """Per-label TP/FP/FN over the whole dataset.

    `policy='exact'` requires identical (start, end, label).
    `policy='partial'` accepts same-label match if IoU ≥ threshold —
    standard NER (CoNLL, MUC) practice.
    """
    if len(predictions) != len(truths):
        raise ValueError(f"length mismatch: preds={len(predictions)} truths={len(truths)}")
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    for pred, truth in zip(predictions, truths):
        unmatched_truth = list(truth)
        for p in pred:
            hit_index = _find_match(p, unmatched_truth, policy, iou_threshold)
            if hit_index is None:
                fp[p.label] += 1
            else:
                tp[p.label] += 1
                unmatched_truth.pop(hit_index)
        for t in unmatched_truth:
            fn[t.label] += 1
    labels = sorted({*tp.keys(), *fp.keys(), *fn.keys()})
    return {l: CategoryMetrics(l, tp[l], fp[l], fn[l]) for l in labels}


def _find_match(
    p: Span, truth: list[Span], policy: str, iou_threshold: float,
) -> int | None:
    if policy == "exact":
        return next((i for i, t in enumerate(truth) if _exact_match(p, t)), None)
    if policy == "partial":
        best_i: int | None = None
        best_iou = iou_threshold
        for i, t in enumerate(truth):
            iou = _overlap_iou(p, t)
            if iou >= best_iou:
                best_iou = iou
                best_i = i
        return best_i
    raise ValueError(f"unknown policy: {policy}")


def macro_f1(metrics: dict[str, CategoryMetrics]) -> float:
    if not metrics:
        return 0.0
    return sum(m.f1 for m in metrics.values()) / len(metrics)
