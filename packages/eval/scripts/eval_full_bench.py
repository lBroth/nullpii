#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Full speed-optimized benchmark across every dataset on M5 Pro 48GB.

Optimizations:
- HF pipeline runs batched on MPS (`batch_size=32`); ~5-10× faster than
  the single-call path used in `eval_4way.py`.
- Larger sample caps than smoke (5k/locale Isotonic, 1k/locale WikiAnn,
  5k Presidio-synthetic) — within ~30 min wall-clock target.
- Each predictor processes the entire run before the next starts, so
  they don't compete for the same accelerator.

Tradeoff: still capped (not "full 209k Isotonic"); run with
`--max-samples 0` to remove caps if you have ~6 hours of patience.
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

# Line-buffer stdout so progress is visible in real time, even when piped
# through `tail -30` or redirected to a log file.
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import (
    nullpii_pool_predictor,
    openai_pipeline_batch_predictor,
    presidio_predictor,
    spacy_predictor,
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
    """Parallel-call variant for predictors backed by a pool (e.g. the
    nullpii pool with N daemons). Each thread loops over a shard of
    samples; preserves order on the way out for F1 scoring."""
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


def f1_batch(pred_batch, samples, *, chunk: int = 32) -> tuple[float, float]:
    truths = [list(s.spans) for s in samples]
    out: list[list] = []
    t0 = time.perf_counter()
    for i in range(0, len(samples), chunk):
        block = [s.text for s in samples[i : i + chunk]]
        results = pred_batch(block)
        out.extend(list(r.spans) for r in results)
    el = time.perf_counter() - t0
    return macro_f1(evaluate(out, truths)), el


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--isotonic",
        type=int,
        default=5000,
        help="samples per locale for isotonic (0 = no cap)",
    )
    parser.add_argument(
        "--wikiann",
        type=int,
        default=1000,
        help="samples per locale for wikiann (0 = no cap)",
    )
    parser.add_argument("--presidio-syn", type=int, default=5000)
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent.parent / "results" / "full-bench.json"),
    )
    parser.add_argument(
        "--log",
        default=str(
            Path(__file__).resolve().parent.parent
            / "results"
            / f"full-bench-{datetime.now():%Y%m%d-%H%M%S}.log"
        ),
    )
    args = parser.parse_args()

    log_path = Path(args.log)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.FileHandler(log_path), logging.StreamHandler(sys.stdout)],
    )
    log = logging.getLogger("full-bench")
    log.info("starting; out=%s log=%s", args.out, log_path)

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
    wiki_n = None if args.wikiann == 0 else args.wikiann
    for loc in ("en", "it", "de", "fr", "es"):
        runs.append((f"wikiann-{loc}", list(public_datasets._load_wikiann(wiki_n, lang=loc).samples)))

    n_total = sum(len(s) for _, s in runs)
    log.info("datasets: %d, total samples: %d", len(runs), n_total)
    for name, samples in runs:
        log.info("  %s %d", name, len(samples))

    log.info("loading predictors…")
    log.info(
        "  nullpii pool: 4 daemons × 2 threads = 8 ORT threads (cpu + fp16; "
        "cpu beats mps on this model — only ~24/365 ops are CoreML-eligible)",
    )
    np_pred = nullpii_pool_predictor(
        pool_size=4,
        threads_each=2,
        backend="cpu",
        variant="fp16",
    )
    pr_pred = presidio_predictor()
    log.info("loading OpenAI HF pipeline (batched on CPU, batch=16)…")
    log.info("  CPU beats MPS for this custom architecture (~24/365 ops")
    log.info("  CoreML-eligible) and avoids GPU memory contention")
    t0 = time.perf_counter()
    oa_batch = openai_pipeline_batch_predictor(device="cpu", batch_size=16)
    log.info("  HF pipeline loaded in %.1fs", time.perf_counter() - t0)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out: dict = {"_meta": {"started": datetime.now().isoformat(), "n_total": n_total}}
    spacy_cache: dict = {}

    def _get_spacy(locale: str):
        if locale not in spacy_cache:
            try:
                spacy_cache[locale] = spacy_predictor(locale=locale)
            except Exception as e:  # noqa: BLE001
                spacy_cache[locale] = e
        cached = spacy_cache[locale]
        return None if isinstance(cached, Exception) else cached

    for idx, (name, samples) in enumerate(runs, start=1):
        loc = name.split("-", 1)[1] if "-" in name else "en"
        if loc.startswith("prompts-") or loc == "synthetic":
            loc = "en"
        log.info(
            "[%d/%d] %s n=%d — dispatching 4 predictors in parallel…",
            idx, len(runs), name, len(samples),
        )
        ds_t0 = time.perf_counter()
        # All four predictors run concurrently per dataset. nullpii uses
        # CPU ORT (auto-threaded), HF uses MPS (separate accelerator),
        # Presidio + spaCy are CPU regex/NER. The nullpii adapter has a
        # threading.Lock around its stdin/stdout so requests don't
        # interleave; HF, Presidio, and spaCy are stateless under the GIL
        # release of their underlying C extensions.
        sp_pred = _get_spacy(loc)
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            # nullpii uses the 4-daemon pool, sharded across 4 inner
            # threads — true parallelism inside the predictor.
            fut_np = ex.submit(f1_parallel, np_pred, samples, workers=4)
            fut_oa = ex.submit(f1_batch, oa_batch, samples, chunk=16)
            fut_pr = ex.submit(f1_single, pr_pred, samples)
            fut_sp = ex.submit(f1_single, sp_pred, samples) if sp_pred else None
            np_f1, np_el = fut_np.result()
            oa_f1, oa_el = fut_oa.result()
            pr_f1, pr_el = fut_pr.result()
            sp_f1, sp_el = fut_sp.result() if fut_sp else (float("nan"), 0.0)
        ds_wall = time.perf_counter() - ds_t0
        log.info(
            "  nullpii=%.4f (%.1fs) openai=%.4f (%.1fs) presidio=%.4f (%.1fs) "
            "spacy=%.4f (%.1fs) | wall=%.1fs",
            np_f1, np_el, oa_f1, oa_el, pr_f1, pr_el, sp_f1, sp_el, ds_wall,
        )
        out[name] = {
            "n": len(samples),
            "nullpii_f1": np_f1,
            "openai_clean_f1": oa_f1,
            "presidio_f1": pr_f1,
            "spacy_f1": sp_f1,
            "nullpii_s": np_el,
            "openai_clean_s": oa_el,
            "presidio_s": pr_el,
            "spacy_s": sp_el,
            "wall_s": ds_wall,
        }
        # Persist partial results after each dataset so a crash mid-run
        # leaves us with everything completed so far.
        out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        log.info("[%d/%d] %s done — partial results written", idx, len(runs), name)
        print(
            f"{name:22} n={len(samples):>5} | "
            f"nullpii={np_f1:.4f} ({np_el:5.1f}s)  "
            f"openai={oa_f1:.4f} ({oa_el:5.1f}s)  "
            f"presidio={pr_f1:.4f} ({pr_el:5.1f}s)  "
            f"spacy={sp_f1:.4f} ({sp_el:5.1f}s)"
        )

    out["_meta"]["finished"] = datetime.now().isoformat()
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    log.info("complete — results → %s, log → %s", out_path, log_path)


if __name__ == "__main__":
    main()
