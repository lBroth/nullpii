# SPDX-License-Identifier: Apache-2.0
"""Screen per-label score thresholds offline (PROTOCOL.md, phase D).

Input: `score_capture.mjs` output (final spans with scores at a low
threshold), or a competitor's `bench_full.py` checkpoints captured the
same way (rule change 9, item 3). For a candidate {label: threshold} map,
keeps spans whose score clears their label's threshold and reports
char-level macro F2 on the tuning set. An optional global sweep tries one
threshold for every label; coordinate descent over a fixed grid then
picks the per-label map.

This is a screen, not a verdict: a lower run threshold also changes what
dedupe keeps, so the chosen map must be confirmed by a real run.

  python threshold_sim.py --scores spans.jsonl --out sim.json
  python threshold_sim.py --checkpoints DIR --tool nemotron-pii-raw \
      --datasets isotonic-en-heldout,... --base 0.3 --global-sweep --out sim.json
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

# The values below 0.05 and above 0.7 were added during competitor tuning
# (rule change 9), in three rounds, as tuned cuts kept settling on the edges.
# A value below the run's own score floor keeps nothing more than the floor
# does. Token classifiers score near 1, so their cuts can sit above 0.99.
GRID = [
    0.001, 0.003, 0.005, 0.01, 0.02, 0.03, 0.05, 0.075, 0.1, 0.125, 0.15, 0.2, 0.25, 0.3,
    0.35, 0.4, 0.45, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95, 0.99, 0.995, 0.999,
]
BASE_THRESHOLD = 0.5
# PROTOCOL rule change 2 (U1): extra masking of developer content, in
# percentage points over the starting map, that a candidate may add.
U1_CAP_PP = 0.5
DESCENT_PASSES = 2


def load_checkpoints(ckpt_dir: Path, tool: str, datasets: list[str]) -> dict[str, list[list]]:
    """`bench_full.py` rows `{idx, spans: [[start, end, label, score]]}`."""
    out: dict[str, list[list]] = {}
    for ds in datasets:
        rows = {}
        for line in (ckpt_dir / f"{tool}-{ds}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["idx"]] = row["spans"]
        if any(len(sp) != 4 for spans in rows.values() for sp in spans):
            raise ValueError(f"{tool}-{ds}: checkpoint spans carry no score")
        out[ds] = [rows[i] for i in range(len(rows))]
    return out


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
    """Char-level counts of one dataset under any threshold map.

    Each document is cut into elementary segments at every span boundary,
    so the set of spans covering a segment is fixed. A segment is masked
    iff any covering span is kept. Masked and correctly masked characters
    are then exact array sums even where spans overlap (Presidio, token
    classifiers, GLiNER across labels), and equal plain per-span sums where
    they do not (nullpii, whose vault merges overlaps).
    """

    def __init__(self, samples: list, docs: list[list]) -> None:
        labels, scores_ = [], []
        seg_len, seg_gold, inc_seg, inc_span = [], [], [], []
        gold_total = 0
        for smp, spans in zip(samples, docs, strict=True):
            n = len(smp.text)
            gold = np.zeros(n, dtype=bool)
            for g in smp.spans:
                gold[max(0, g.start) : min(n, g.end)] = True
            gold_total += int(gold.sum())
            clipped = [(max(0, a), min(n, b), label, score) for a, b, label, score in spans]
            clipped = [c for c in clipped if c[1] > c[0]]
            if not clipped:
                continue
            prefix = np.concatenate(([0], np.cumsum(gold)))
            cuts = sorted({p for a, b, _, _ in clipped for p in (a, b)})
            first = len(seg_len)
            pos = {p: first + i for i, p in enumerate(cuts)}
            for a, b in zip(cuts, cuts[1:]):
                seg_len.append(b - a)
                seg_gold.append(int(prefix[b] - prefix[a]))
            for a, b, label, score in clipped:
                span_id = len(labels)
                labels.append(label)
                scores_.append(score)
                inc_seg.extend(range(pos[a], pos[b]))
                inc_span.extend([span_id] * (pos[b] - pos[a]))
            seg_len.append(0)  # the slot after the last cut; never covered
            seg_gold.append(0)
        self.labels = np.array(labels)
        self.scores = np.array(scores_, dtype=float)
        self.seg_len = np.array(seg_len, dtype=np.int64)
        self.seg_gold = np.array(seg_gold, dtype=np.int64)
        self.inc_seg = np.array(inc_seg, dtype=np.int64)
        self.inc_span = np.array(inc_span, dtype=np.int64)
        self.gold_total = float(gold_total)

    def evaluate(self, thresholds: dict[str, float], base: float = BASE_THRESHOLD) -> dict[str, float]:
        cut = np.full(self.scores.shape, base)
        for label, t in thresholds.items():
            cut[self.labels == label] = t
        keep = (self.scores >= cut).astype(float)
        covered = np.bincount(self.inc_seg, weights=keep[self.inc_span], minlength=len(self.seg_len)) > 0
        return scores(
            np.array([self.gold_total]),
            np.array([float(self.seg_len[covered].sum())]),
            np.array([float(self.seg_gold[covered].sum())]),
        )


def macro_f2(tables: dict[str, SpanTable], thresholds: dict[str, float], base: float = BASE_THRESHOLD) -> tuple[float, dict]:
    per_ds = {ds: t.evaluate(thresholds, base) for ds, t in tables.items()}
    return float(np.mean([v["f2"] for v in per_ds.values()])), per_ds


def dev_masked_pct(dev: list[tuple[int, list]], thresholds: dict[str, float]) -> float:
    """Masked share of developer-corpus characters under `thresholds` (U1)."""
    total = sum(n for n, _ in dev)
    kept = sum(e - s for _, spans in dev for s, e, label, score in spans if score >= thresholds.get(label, BASE_THRESHOLD))
    return 100 * kept / total


def global_sweep(tables: dict[str, SpanTable], labels: list[str]) -> tuple[dict[str, float], float]:
    """The best single threshold for every label on GRID."""
    best, best_f2 = {}, -1.0
    for t in GRID:
        cand = dict.fromkeys(labels, t)
        f2, _ = macro_f2(tables, cand)
        print(f"global {t:.3f}: macro char-F2 {f2:.4f}", flush=True)
        if f2 > best_f2:
            best, best_f2 = cand, f2
    return best, best_f2


def descend(
    tables: dict[str, SpanTable], labels: list[str], start: dict[str, float], dev: list | None,
    base: float = BASE_THRESHOLD,
) -> tuple[dict[str, float], float]:
    best = {label: start.get(label, base) for label in labels}
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
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--scores", type=Path)
    source.add_argument("--checkpoints", type=Path, help="bench_full.py checkpoint dir with scored spans")
    parser.add_argument("--tool", help="tool name of the checkpoints")
    parser.add_argument("--datasets", help="comma list of tuning datasets in the checkpoints")
    parser.add_argument("--base", type=float, default=BASE_THRESHOLD,
                        help="the tool's own default threshold, for labels the start map does not list")
    parser.add_argument("--global-sweep", action="store_true",
                        help="try one threshold for every label first; descent starts from the better map")
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

    if args.checkpoints:
        if not (args.tool and args.datasets):
            parser.error("--checkpoints needs --tool and --datasets")
        captured = load_checkpoints(args.checkpoints, args.tool, args.datasets.split(","))
    else:
        captured = load_scores(args.scores)
    gold = load_gold(list(captured))
    tables = {ds: SpanTable(gold[ds], docs) for ds, docs in captured.items()}
    labels = sorted({s[2] for docs in captured.values() for spans in docs for s in spans})
    start = {label: start.get(label, args.base) for label in labels}
    base_f2, base_per_ds = macro_f2(tables, start)
    print(f"start map: macro char-F2 {base_f2:.4f}" + ("" if dev is None else f", dev masked {dev_masked_pct(dev, start):.3f}%"), flush=True)
    sweep = None
    if args.global_sweep:
        sweep_map, sweep_f2 = global_sweep(tables, labels)
        sweep = {"thresholds": sweep_map, "macro_f2": sweep_f2}
        if sweep_f2 > base_f2:
            start = sweep_map
    best, best_f2 = descend(tables, labels, start, dev, args.base)
    if dev is not None:
        print(f"best map dev masked {dev_masked_pct(dev, best):.3f}%", flush=True)
    _, best_per_ds = macro_f2(tables, best)
    args.out.write_text(
        json.dumps(
            {"base": {"macro_f2": base_f2, "per_dataset": base_per_ds},
             "global_sweep": sweep,
             "best": {"thresholds": best, "macro_f2": best_f2, "per_dataset": best_per_ds},
             # The `--tool-config` entry of bench_full.py for this map.
             "label_cut": {"default": args.base, "thresholds": best}},
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
