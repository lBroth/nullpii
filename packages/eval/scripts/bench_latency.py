#!/usr/bin/env python3
"""Latency SLA bench per profile × prompt size.

Measures p50 / p95 / p99 latency for each `nullpii-*` profile across
representative prompt sizes (100 / 1k / 10k chars), using the bundled
`nullpii-bench.jsonl` and synthetic-padded variants when needed.

Output: `packages/eval/results/latency-bench-<DATE>/latency.json` +
`latency.md` table for direct paste into `docs/compliance/DPIA_TEMPLATE.md`.

CLI:
  python bench_latency.py \\
    --profiles devops legal medical-experimental general \\
    --sizes 100 1000 10000 \\
    --n-per-size 100 \\
    --backend cpu \\
    --out packages/eval/results/latency-bench-20260503
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "eval" / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from nullpii_eval.adapters import (  # noqa: E402
    DEFAULT_REGEX_PATTERNS,
    MINIMAL_REGEX_PATTERNS,
    boundary_refined_predictor,
    complementary_v6_v8_predictor,
    gliner_v2_predictor,
    multi_ensemble_predictor,
    never_pii_filter_predictor,
    url_filter_predictor,
)


def build_predictor(profile: str, backend: str = "cpu", gliner_threshold: float = 0.5):
    v6 = lambda: gliner_v2_predictor(  # noqa: E731
        "onnx-community/gliner_multi_pii-v1",
        onnx_file="onnx/model.onnx",
        threshold=gliner_threshold,
    )
    v8 = lambda: gliner_v2_predictor(  # noqa: E731
        "packages/eval/results/train/gliner-v8-multidomain/final",
        device=backend if backend == "cpu" else "cuda",
        threshold=gliner_threshold,
    )

    if profile == "devops":
        return never_pii_filter_predictor(
            inner=boundary_refined_predictor(
                inner=multi_ensemble_predictor(
                    predictors=[
                        url_filter_predictor(patterns=DEFAULT_REGEX_PATTERNS),
                        v6(),
                    ],
                    strategy="primary",
                ),
            ),
            drop_rfc1918=True,
        )
    if profile in ("legal", "medical-experimental"):
        return never_pii_filter_predictor(
            inner=boundary_refined_predictor(
                inner=multi_ensemble_predictor(
                    predictors=[
                        url_filter_predictor(patterns=MINIMAL_REGEX_PATTERNS),
                        v8(),
                    ],
                    strategy="primary",
                ),
            ),
            drop_rfc1918=False,
        )
    if profile == "general":
        return never_pii_filter_predictor(
            inner=boundary_refined_predictor(
                inner=multi_ensemble_predictor(
                    predictors=[
                        url_filter_predictor(patterns=DEFAULT_REGEX_PATTERNS),
                        v6(),
                        v8(),
                    ],
                    strategy="union",
                ),
            ),
            drop_rfc1918=True,
        )
    raise ValueError(f"unknown profile: {profile}")


def load_inputs_for_size(target_chars: int, n: int, seed: int) -> list[str]:
    """Build n inputs of approximately `target_chars` length using
    nullpii-bench samples (or repetitions thereof)."""
    bench_path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-bench.jsonl"
    samples = []
    with bench_path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["subset"] in ("bundled", "long-prompts"):
                samples.append(row["text"])
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        # Combine samples until target size reached
        text_parts = []
        cur = 0
        while cur < target_chars:
            s = rng.choice(samples)
            text_parts.append(s)
            cur += len(s) + 2
        out.append("\n\n".join(text_parts)[:target_chars])
    return out


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", nargs="+",
                    default=["devops", "legal", "medical-experimental", "general"])
    ap.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    ap.add_argument("--n-per-size", type=int, default=50)
    ap.add_argument("--backend", default="cpu")
    ap.add_argument("--gliner-threshold", type=float, default=0.5)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    results: dict = {}
    print(f"[lat] profiles: {args.profiles} sizes: {args.sizes} n/size: {args.n_per_size}")

    for profile in args.profiles:
        print(f"[lat] building {profile} predictor…")
        predictor = build_predictor(profile, args.backend, args.gliner_threshold)
        results[profile] = {}
        for size in args.sizes:
            inputs = load_inputs_for_size(size, args.n_per_size, args.seed)
            # Warm up
            _ = predictor(inputs[0])
            ms_list: list[float] = []
            for text in inputs:
                t0 = time.perf_counter()
                _ = predictor(text)
                ms_list.append((time.perf_counter() - t0) * 1000)
            results[profile][str(size)] = {
                "p50_ms": percentile(ms_list, 50),
                "p95_ms": percentile(ms_list, 95),
                "p99_ms": percentile(ms_list, 99),
                "mean_ms": sum(ms_list) / len(ms_list),
                "min_ms": min(ms_list),
                "max_ms": max(ms_list),
                "n": len(ms_list),
                "sample_text_chars": size,
            }
            r = results[profile][str(size)]
            print(f"  {profile}/{size}c: p50={r['p50_ms']:.1f} p95={r['p95_ms']:.1f} p99={r['p99_ms']:.1f}")

    json_path = args.out / "latency.json"
    json_path.write_text(json.dumps(results, indent=2))

    # Markdown table
    md_lines = ["# Latency bench results", "", f"Generated: backend={args.backend}, n/size={args.n_per_size}", ""]
    md_lines.append("| Profile | Size (chars) | p50 (ms) | p95 (ms) | p99 (ms) | Mean (ms) |")
    md_lines.append("|---|---:|---:|---:|---:|---:|")
    for profile, sizes in results.items():
        for size, m in sizes.items():
            md_lines.append(
                f"| {profile} | {size} | {m['p50_ms']:.1f} | {m['p95_ms']:.1f} | "
                f"{m['p99_ms']:.1f} | {m['mean_ms']:.1f} |",
            )
    md_path = args.out / "latency.md"
    md_path.write_text("\n".join(md_lines) + "\n")
    print(f"[lat] wrote {json_path} + {md_path}")


if __name__ == "__main__":
    main()
