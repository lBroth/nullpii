# SPDX-License-Identifier: Apache-2.0
"""Per-call latency of competitor tools on the exact inputs harness.mjs times.

The latency comparison (METHOD.md) compares nullpii's p50 per call against every ML
competitor on the same machine and the same inputs. `harness.mjs
dump-corpus` writes those inputs; this script replays them through each
tool's bench_full predictor, one text per call, because a hook masks one
tool result at a time. Each tool keeps its upstream-recommended device,
chunker and decoder, exactly as bench_full configures it.

  python competitor_latency.py --inputs corpus.jsonl --tools a,b --backend mps --out lat.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from types import SimpleNamespace

SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SCRIPTS.parent / "src"))

import bench_full  # noqa: E402

GLINER_THRESHOLD = 0.5  # bench_full's default (--gliner-threshold)


def load_inputs(path: Path) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError(f"{path}: no inputs")
    return rows


def make_predictor(tool: str, backend: str):
    # No --tool-config: each tool runs at its default operating point. A tuned
    # point moves thresholds or Viterbi biases, not the forward passes timed here.
    args = SimpleNamespace(
        tools=tool, backend=backend, gliner_threshold=GLINER_THRESHOLD, drop_rfc1918=False, tool_config=None
    )
    pred = bench_full.build_tools(args)[tool]  # build_tools returns constructed predictors
    if getattr(pred, "is_batch", False):
        return lambda text: pred([text])[0]
    return pred


def time_call(pred, text: str) -> float:
    t0 = time.perf_counter()
    pred(text)
    return (time.perf_counter() - t0) * 1000


def measure(pred, inputs: list[dict]) -> dict:
    for row in (r for r in inputs if r["phase"] == "warmup"):
        time_call(pred, row["text"])
    by_size: dict[int, list[float]] = {}
    for size in sorted({r["size"] for r in inputs if r["phase"] == "measure"}):
        round_p50s, round_p95s = [], []
        for rnd in sorted({r["round"] for r in inputs if r["phase"] == "measure"}):
            rows = [r for r in inputs if r["phase"] == "measure" and r["size"] == size and r["round"] == rnd]
            times = sorted(time_call(pred, r["text"]) for r in rows)
            round_p50s.append(times[len(times) // 2])
            round_p95s.append(times[min(len(times) - 1, int(0.95 * len(times)))])
        med = statistics.median(round_p50s)
        by_size[size] = {
            "p50": med,
            "p95": statistics.median(round_p95s),
            "msPer1k": med / size * 1000,
            "spreadPct": (max(round_p50s) - min(round_p50s)) / med * 100,
            "roundP50s": round_p50s,
        }
    return by_size


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs", required=True, type=Path)
    parser.add_argument("--tools", required=True)
    parser.add_argument("--backend", default="mps", choices=["cpu", "cuda", "mps"])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    inputs = load_inputs(args.inputs)
    report = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    for tool in args.tools.split(","):
        pred = make_predictor(tool, args.backend)
        report[tool] = {"backend": args.backend, "bySize": measure(pred, inputs)}
        args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        row = {k: round(v["p50"]) for k, v in report[tool]["bySize"].items()}
        print(f"{tool}: p50 ms {row}", flush=True)


if __name__ == "__main__":
    main()
