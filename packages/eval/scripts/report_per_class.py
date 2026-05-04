#!/usr/bin/env python3
"""Per-class precision/recall/F1 reporting from bench checkpoint files.

Aggregate F1 hides class-specific failures. For compliance use, false
negatives on `private_person` (GDPR Art. 4 direct identifier) are
materially different from false negatives on `private_url` (lower
re-identification risk). This script reads the bench's per-checkpoint
prediction jsonl files + reloads gold annotations, computes per-class
TP/FP/FN/precision/recall/F1, and emits a markdown report ready for
DPIA / compliance review.

Usage:
  python report_per_class.py \\
    --bench-dir packages/eval/results/v9-bench-20260502 \\
    --tools nullpii-v9 \\
    --datasets nullpii-bench tab-echr ai4privacy-300k \\
    --out packages/eval/results/v9-bench-20260502/per_class.md

The dataset loaders are imported from `bench_full.py` so dataset
identifiers must match the bench's `DATASET_CONFIGS`.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "eval" / "src"))


def _load_bench_module():
    bench_path = Path(__file__).resolve().parent / "bench_full.py"
    spec = importlib.util.spec_from_file_location("bench_full", bench_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _iou(a: tuple[int, int], b: tuple[int, int]) -> float:
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    union = (a[1] - a[0]) + (b[1] - b[0]) - inter
    return inter / union if union > 0 else 0.0


def per_class_for(checkpoint: Path, samples) -> dict:
    tally = defaultdict(lambda: {"tp": 0, "fp": 0, "fn": 0})
    with checkpoint.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            idx = row["idx"]
            if idx >= len(samples):
                continue
            sample = samples[idx]
            preds = [(int(s[0]), int(s[1]), str(s[2])) for s in row["spans"]]
            golds = [(g.start, g.end, g.label) for g in sample.spans]
            mg = [False] * len(golds)
            mp = [False] * len(preds)
            for pi, p in enumerate(preds):
                for gi, g in enumerate(golds):
                    if mg[gi] or g[2] != p[2]:
                        continue
                    if _iou((p[0], p[1]), (g[0], g[1])) >= 0.5:
                        mg[gi] = True
                        mp[pi] = True
                        tally[p[2]]["tp"] += 1
                        break
            for pi, p in enumerate(preds):
                if not mp[pi]:
                    tally[p[2]]["fp"] += 1
            for gi, g in enumerate(golds):
                if not mg[gi]:
                    tally[g[2]]["fn"] += 1
    return tally


def f1_pr(stats: dict) -> tuple[float, float, float]:
    tp, fp, fn = stats["tp"], stats["fp"], stats["fn"]
    if tp + fp == 0:
        return 0.0, 0.0, 0.0
    p = tp / (tp + fp)
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bench-dir", type=Path, required=True)
    ap.add_argument("--tools", nargs="+", required=True)
    ap.add_argument("--datasets", nargs="+", required=True)
    ap.add_argument("--max-per-dataset", type=int, default=2000)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    print(f"[per-class] loading dataset registry from bench_full…")
    bf = _load_bench_module()
    spec_by_key = {s.key: s for s in bf.DATASET_CONFIGS}

    out_lines = ["# Per-class precision / recall / F1", ""]
    out_lines.append(f"Source: `{args.bench_dir}`. n=2000 per dataset (or full if smaller).")
    out_lines.append("")
    out_lines.append("Read this for compliance use; aggregate F1 hides per-class behaviour.")
    out_lines.append("False negatives on `private_person` are GDPR Art. 4 violations; false ")
    out_lines.append("negatives on `private_url` are lower re-identification risk.")
    out_lines.append("")

    for ds in args.datasets:
        if ds not in spec_by_key:
            print(f"[per-class] WARN: dataset {ds} not in registry; skipping")
            continue
        spec = spec_by_key[ds]
        cap = args.max_per_dataset
        samples = spec.loader(cap if spec.default_n is None or cap < spec.default_n else spec.default_n)
        out_lines.append(f"## `{ds}` (n={len(samples)})")
        out_lines.append("")

        for tool in args.tools:
            checkpoint = args.bench_dir / "checkpoints" / f"{tool}-{ds}.jsonl"
            if not checkpoint.is_file():
                print(f"[per-class] WARN: missing {checkpoint}; skipping")
                continue
            tally = per_class_for(checkpoint, samples)
            out_lines.append(f"### `{tool}`")
            out_lines.append("")
            out_lines.append("| Label | TP | FP | FN | Precision | Recall | F1 |")
            out_lines.append("|---|---:|---:|---:|---:|---:|---:|")
            for label in sorted(tally.keys()):
                p, r, f1 = f1_pr(tally[label])
                t = tally[label]
                out_lines.append(
                    f"| {label} | {t['tp']} | {t['fp']} | {t['fn']} | "
                    f"{p:.3f} | {r:.3f} | {f1:.3f} |",
                )
            out_lines.append("")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(out_lines) + "\n")
    print(f"[per-class] wrote {args.out}")


if __name__ == "__main__":
    main()
