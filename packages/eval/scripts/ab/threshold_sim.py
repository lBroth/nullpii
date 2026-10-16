# SPDX-License-Identifier: Apache-2.0
"""Screen per-label score thresholds offline (PROTOCOL.md, phase D).

Input: `score_capture.mjs` output (final spans with scores at a low
threshold). For a candidate {label: threshold} map, keeps spans whose
score clears their label's threshold and reports char-level macro F2 on
the tuning set. Coordinate descent over a fixed grid picks a candidate.

This is a screen, not a verdict: a lower run threshold also changes what
dedupe keeps, so the chosen map must be confirmed by a real run.

  python threshold_sim.py --scores spans.jsonl --out sim.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import bench_full  # noqa: E402
from char_metrics import scores  # noqa: E402

GRID = [0.05, 0.075, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5, 0.6, 0.7]
BASE_THRESHOLD = 0.5
# PROTOCOL rule change 2 (U1): extra masking of developer content, in
# percentage points over the starting map, that a candidate may add.
U1_CAP_PP = 0.5
DESCENT_PASSES = 2


def load_scores(path: Path) -> dict[str, list[list]]:
    by_ds: dict[str, dict[int, list]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            by_ds.setdefault(row["dataset"], {})[row["idx"]] = row["spans"]
    return {ds: [rows[i] for i in range(len(rows))] for ds, rows in by_ds.items()}


def load_gold(datasets: list[str]) -> dict[str, list]:
    gold = {}
    for key in datasets:
        spec = next(s for s in bench_full.DATASET_CONFIGS if s.key == key)
        gold[key] = spec.loader(spec.default_n)
    return gold


class SpanTable:
    """Per-span (label, score, length, gold-overlap chars) for one dataset.

    Captured spans are disjoint (the vault merges overlaps before
    returning them), so coverage is additive over kept spans and any
    threshold map is evaluated with array sums instead of a pass over
    every document.
    """

    def __init__(self, samples: list, docs: list[list]) -> None:
        labels, scores_, lengths, hits = [], [], [], []
        gold_total = 0
        for smp, spans in zip(samples, docs, strict=True):
            n = len(smp.text)
            gold = np.zeros(n, dtype=bool)
            for g in smp.spans:
                gold[max(0, g.start) : min(n, g.end)] = True
            gold_total += int(gold.sum())
            for start, end, label, score in spans:
                a, b = max(0, start), min(n, end)
                labels.append(label)
                scores_.append(score)
                lengths.append(max(0, b - a))
                hits.append(int(gold[a:b].sum()) if b > a else 0)
        self.labels = np.array(labels)
        self.scores = np.array(scores_, dtype=float)
        self.lengths = np.array(lengths, dtype=float)
        self.hits = np.array(hits, dtype=float)
        self.gold_total = float(gold_total)

    def evaluate(self, thresholds: dict[str, float]) -> dict[str, float]:
        cut = np.full(self.scores.shape, BASE_THRESHOLD)
        for label, t in thresholds.items():
            cut[self.labels == label] = t
        keep = self.scores >= cut
        return scores(np.array([self.gold_total]), np.array([self.lengths[keep].sum()]), np.array([self.hits[keep].sum()]))


def macro_f2(tables: dict[str, SpanTable], thresholds: dict[str, float]) -> tuple[float, dict]:
    per_ds = {ds: t.evaluate(thresholds) for ds, t in tables.items()}
    return float(np.mean([v["f2"] for v in per_ds.values()])), per_ds


def dev_masked_pct(dev: list[tuple[int, list]], thresholds: dict[str, float]) -> float:
    """Masked share of developer-corpus characters under `thresholds` (U1)."""
    total = sum(n for n, _ in dev)
    kept = sum(e - s for _, spans in dev for s, e, label, score in spans if score >= thresholds.get(label, BASE_THRESHOLD))
    return 100 * kept / total


def descend(
    tables: dict[str, SpanTable], labels: list[str], start: dict[str, float], dev: list | None
) -> tuple[dict[str, float], float]:
    best = {label: start.get(label, BASE_THRESHOLD) for label in labels}
    best_f2, _ = macro_f2(tables, best)
    u1_limit = None if dev is None else dev_masked_pct(dev, best) + U1_CAP_PP
    for _ in range(DESCENT_PASSES):
        for label in labels:
            for t in GRID:
                cand = {**best, label: t}
                if u1_limit is not None and dev_masked_pct(dev, cand) > u1_limit:
                    continue
                f2, _ = macro_f2(tables, cand)
                if f2 > best_f2:
                    best, best_f2 = cand, f2
        print(f"pass: macro char-F2 {best_f2:.4f} {best}", flush=True)
    return best, best_f2


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scores", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--start", default="{}", help="JSON label->threshold map to start from (current defaults)")
    parser.add_argument("--dev-scores", type=Path, help="score_capture output on developer texts, for the U1 cap")
    parser.add_argument("--dev-texts", type=Path)
    args = parser.parse_args()
    start = json.loads(args.start)
    dev = None
    if args.dev_scores:
        lengths = {json.loads(l)["dataset"]: len(json.loads(l)["text"]) for l in args.dev_texts.read_text().splitlines() if l.strip()}
        dev = [(lengths[r["dataset"]], r["spans"]) for r in map(json.loads, args.dev_scores.read_text().splitlines()) if r]

    captured = load_scores(args.scores)
    gold = load_gold(list(captured))
    tables = {ds: SpanTable(gold[ds], docs) for ds, docs in captured.items()}
    labels = sorted({s[2] for docs in captured.values() for spans in docs for s in spans})
    base_f2, base_per_ds = macro_f2(tables, start)
    print(f"start map: macro char-F2 {base_f2:.4f}" + ("" if dev is None else f", dev masked {dev_masked_pct(dev, start):.3f}%"), flush=True)
    best, best_f2 = descend(tables, labels, start, dev)
    if dev is not None:
        print(f"best map dev masked {dev_masked_pct(dev, best):.3f}%", flush=True)
    _, best_per_ds = macro_f2(tables, best)
    args.out.write_text(
        json.dumps(
            {"base": {"macro_f2": base_f2, "per_dataset": base_per_ds},
             "best": {"thresholds": best, "macro_f2": best_f2, "per_dataset": best_per_ds}},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
