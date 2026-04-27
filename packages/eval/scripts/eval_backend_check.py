#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Compare CPU+int8 (eval default) vs MPS+fp16 (Apple Silicon optimal).

Verifies we're actually exercising the GPU/CoreML path, and quantifies
the F1 + latency tradeoff on a small bundled sample.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval.adapters import nullpii_predictor
from nullpii_eval.datasets import load
from nullpii_eval.metrics import evaluate, macro_f1


def benchmark(samples, *, backend: str, variant: str) -> tuple[float, float]:
    pred = nullpii_predictor(backend=backend, variant=variant)
    truths = [list(s.spans) for s in samples]
    # warmup
    pred(samples[0].text)
    t0 = time.perf_counter()
    preds = [list(pred(s.text).spans) for s in samples]
    elapsed_ms = (time.perf_counter() - t0) * 1000
    f1 = macro_f1(evaluate(preds, truths))
    return f1, elapsed_ms / len(samples)


def main() -> None:
    samples = list(load("en").samples)
    print(f"samples: {len(samples)} (bundled-en)\n")

    for backend, variant in [
        ("cpu", "int8"),
        ("cpu", "fp16"),
        ("mps", "fp16"),
        ("mps", "int8"),
    ]:
        try:
            f1, ms = benchmark(samples, backend=backend, variant=variant)
            print(f"  {backend:4} / {variant:4}  F1={f1:.4f}  avg={ms:6.1f} ms/sample")
        except Exception as e:  # noqa: BLE001
            print(f"  {backend:4} / {variant:4}  FAILED: {e}")


if __name__ == "__main__":
    main()
