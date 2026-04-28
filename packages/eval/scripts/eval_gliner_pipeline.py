#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Targeted bench: nullpii pipeline ideas on top of GLiNER backbone.

Compares three predictors on every PII dataset:
- **nullpii** (full pipeline over `openai/privacy-filter`)
- **GLiNER bare** (single-call `predict_entities` on full text)
- **GLiNER + chunking** (nullpii-style sliding window + span dedupe
  on top of the same GLiNER model)

The chunked variant tests whether nullpii's runtime ideas transfer to
a different backbone. Bare GLiNER hits 0.000 on long-prompts-en because
of max-sequence-length truncation; chunked should recover those spans.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import (
    gliner_chunked_predictor,
    gliner_pii_predictor,
    nullpii_pool_predictor,
)
from nullpii_eval.datasets import load
from nullpii_eval.metrics import evaluate, macro_f1


def f1_single(pred, samples) -> tuple[float, float]:
    truths = [list(s.spans) for s in samples]
    t0 = time.perf_counter()
    out = [list(pred(s.text).spans) for s in samples]
    el = time.perf_counter() - t0
    return macro_f1(evaluate(out, truths)), el


def f1_parallel(pred, samples, *, workers: int) -> tuple[float, float]:
    truths = [list(s.spans) for s in samples]
    out: list[list] = [None] * len(samples)  # type: ignore[list-item]

    def _work(indices: list[int]) -> None:
        for i in indices:
            out[i] = list(pred(samples[i].text).spans)

    shards: list[list[int]] = [[] for _ in range(workers)]
    for i in range(len(samples)):
        shards[i % workers].append(i)

    t0 = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(_work, shards))
    el = time.perf_counter() - t0
    return macro_f1(evaluate(out, truths)), el


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--isotonic", type=int, default=2000)
    parser.add_argument("--presidio-syn", type=int, default=2000)
    parser.add_argument(
        "--out",
        default=str(
            Path(__file__).resolve().parent.parent / "results" / "gliner-pipeline.json"
        ),
    )
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    log_path = (
        out_path.parent / f"gliner-pipeline-{datetime.now():%Y%m%d-%H%M%S}.log"
    )
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("gliner-pipeline")
    log.info("starting; out=%s", out_path)

    runs: list[tuple[str, list]] = []
    for loc in ("en", "it", "de", "fr", "es"):
        runs.append((f"bundled-{loc}", list(load(loc).samples)))
    runs.append(("long-prompts-en", list(load("long-prompts-en").samples)))
    iso_n = None if args.isotonic == 0 else args.isotonic
    for loc in ("en", "it", "de", "fr"):
        runs.append((f"isotonic-{loc}", list(public_datasets._load_isotonic(iso_n, lang=loc).samples)))
    if args.presidio_syn > 0:
        runs.append((
            "presidio-synthetic",
            list(public_datasets._load_presidio_synthetic(args.presidio_syn).samples),
        ))

    n_total = sum(len(s) for _, s in runs)
    log.info("datasets: %d, total samples: %d", len(runs), n_total)

    log.info("loading predictors…")
    np_pred = nullpii_pool_predictor(pool_size=4, threads_each=2)
    log.info("  nullpii pool ready")
    gl_bare = gliner_pii_predictor(threshold=0.5)
    log.info("  GLiNER bare ready")
    gl_chunk = gliner_chunked_predictor(threshold=0.5)
    log.info("  GLiNER chunked ready")

    out: dict = {"_meta": {"started": datetime.now().isoformat(), "n_total": n_total}}
    for idx, (name, samples) in enumerate(runs, start=1):
        log.info("[%d/%d] %s n=%d…", idx, len(runs), name, len(samples))
        t_ds = time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fut_np = ex.submit(f1_parallel, np_pred, samples, workers=4)
            fut_glb = ex.submit(f1_single, gl_bare, samples)
            fut_glc = ex.submit(f1_single, gl_chunk, samples)
            np_f1, np_el = fut_np.result()
            glb_f1, glb_el = fut_glb.result()
            glc_f1, glc_el = fut_glc.result()
        ds_wall = time.perf_counter() - t_ds
        out[name] = {
            "n": len(samples),
            "nullpii_f1": np_f1,
            "gliner_bare_f1": glb_f1,
            "gliner_chunked_f1": glc_f1,
            "nullpii_s": np_el,
            "gliner_bare_s": glb_el,
            "gliner_chunked_s": glc_el,
            "wall_s": ds_wall,
        }
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        log.info(
            "  nullpii=%.4f (%.1fs)  gliner_bare=%.4f (%.1fs)  gliner_chunked=%.4f (%.1fs)  wall=%.1fs",
            np_f1, np_el, glb_f1, glb_el, glc_f1, glc_el, ds_wall,
        )

    # Aggregate latency
    predictors = ["nullpii", "gliner_bare", "gliner_chunked"]
    latency_summary: dict = {}
    for p in predictors:
        total_s = 0.0
        total_n = 0
        for name, v in out.items():
            if name == "_meta":
                continue
            total_s += v.get(f"{p}_s", 0.0)
            total_n += v["n"]
        latency_summary[p] = {
            "ms_per_sample": (total_s / total_n) * 1000 if total_n else 0.0,
            "total_samples": total_n,
        }
    out["_meta"]["finished"] = datetime.now().isoformat()
    out["_meta"]["latency_per_predictor"] = latency_summary
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    log.info("=== latency summary ===")
    for p, stat in latency_summary.items():
        log.info("  %-16s %7.2f ms/sample (%d samples)", p, stat["ms_per_sample"], stat["total_samples"])
    log.info("complete — results → %s", out_path)


if __name__ == "__main__":
    main()
