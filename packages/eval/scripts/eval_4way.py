#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""4-way head-to-head: nullpii (full pipeline) vs OpenAI bare HF pipeline
vs Presidio vs spaCy.

The "OpenAI clean" leg loads `openai/privacy-filter` via
`transformers.pipeline` — bare model, no chunking, no Viterbi biases,
no posterior scoring. If nullpii's runtime additions are worth keeping
they should beat this baseline on long inputs and not regress on short
ones.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import (
    nullpii_predictor,
    openai_pipeline_predictor,
    presidio_predictor,
    spacy_predictor,
)
from nullpii_eval.datasets import load
from nullpii_eval.metrics import evaluate, macro_f1


def f1_for(pred, samples) -> float:
    truths = [list(s.spans) for s in samples]
    out = [list(pred(s.text).spans) for s in samples]
    return macro_f1(evaluate(out, truths))


def main() -> None:
    np_pred = nullpii_predictor()
    print("loading OpenAI HF pipeline (first run downloads ~5GB)…")
    t0 = time.perf_counter()
    oa_pred = openai_pipeline_predictor()
    print(f"  loaded in {time.perf_counter() - t0:.1f}s")
    pr_pred = presidio_predictor()

    runs: list[tuple[str, list]] = []
    for loc in ("en", "it", "de", "fr", "es"):
        runs.append((f"bundled-{loc}", list(load(loc).samples)))
    runs.append(("long-prompts-en", list(load("long-prompts-en").samples)))
    for loc in ("en", "it", "de", "fr"):
        runs.append((
            f"isotonic-{loc}",
            list(public_datasets._load_isotonic(200, lang=loc).samples),
        ))

    out: dict = {}
    for name, samples in runs:
        nullpii = f1_for(np_pred, samples)
        openai = f1_for(oa_pred, samples)
        presidio = f1_for(pr_pred, samples)
        try:
            sp = spacy_predictor(locale=name.split("-", 1)[1])
            spacy = f1_for(sp, samples)
        except Exception:  # noqa: BLE001
            spacy = float("nan")
        out[name] = {
            "n": len(samples),
            "nullpii": nullpii,
            "openai_clean": openai,
            "presidio": presidio,
            "spacy": spacy,
            "nullpii_minus_openai": nullpii - openai,
        }
        print(
            f"{name:14}: nullpii={nullpii:.4f}  openai={openai:.4f}  "
            f"presidio={presidio:.4f}  spacy={spacy:.4f}  Δ(np-oa)={nullpii-openai:+.4f}"
        )

    out_path = Path("/tmp/nullpii-eval/4way.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    avg_delta = sum(v["nullpii_minus_openai"] for v in out.values()) / len(out)
    print(f"\navg Δ(nullpii - openai_clean): {avg_delta:+.4f}")
    print(f"results → {out_path}")


if __name__ == "__main__":
    main()
