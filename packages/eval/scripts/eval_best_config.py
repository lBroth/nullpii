#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Apply the sweep-best bias config across all locales and the Isotonic
multi-locale dataset. Verifies the gain generalizes beyond bundled-en."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import nullpii_predictor
from nullpii_eval.datasets import load
from nullpii_eval.metrics import evaluate, macro_f1


def f1_for(samples, **kwargs) -> float:
    pred = nullpii_predictor(**kwargs)
    truths = [list(s.spans) for s in samples]
    preds = [list(pred(s.text).spans) for s in samples]
    return macro_f1(evaluate(preds, truths))


def main() -> None:
    out: dict = {}
    for loc in ("en", "it", "de", "fr", "es"):
        samples = list(load(loc).samples)
        baseline = f1_for(samples)
        tuned = f1_for(samples, continue_bias=0.5)
        out[f"bundled-{loc}"] = {
            "n": len(samples),
            "baseline": baseline,
            "tuned": tuned,
            "delta": tuned - baseline,
        }
        print(f"bundled-{loc:2}: baseline={baseline:.4f}  tuned={tuned:.4f}  Δ={tuned-baseline:+.4f}")

    for loc in ("en", "it", "de", "fr"):
        samples = list(public_datasets._load_isotonic(200, lang=loc).samples)
        baseline = f1_for(samples)
        tuned = f1_for(samples, continue_bias=0.5)
        out[f"isotonic-{loc}"] = {
            "n": len(samples),
            "baseline": baseline,
            "tuned": tuned,
            "delta": tuned - baseline,
        }
        print(f"isotonic-{loc}: baseline={baseline:.4f}  tuned={tuned:.4f}  Δ={tuned-baseline:+.4f}")

    avg_delta = sum(v["delta"] for v in out.values()) / len(out)
    print(f"\navg Δ: {avg_delta:+.4f}")
    out["_avg_delta"] = avg_delta

    out_path = Path("/tmp/nullpii-eval/best-config.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"results → {out_path}")


if __name__ == "__main__":
    main()
