#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Full comparison bench: tool × dataset matrix with checkpoint resume.

Single unified bench script — replaces older quick_*/eval_ensemble
scripts. Designed for serial multi-day runs on a 4090 RunPod.

Each (tool, dataset) combination writes:
  - {checkpoint_dir}/{tool}-{dataset}.jsonl  (one prediction per line)
  - {checkpoint_dir}/{tool}-{dataset}.state  (last completed idx)

Re-running the script picks up from `.state` and skips finished
combinations entirely. Final results:
  - {out_dir}/matrix.json   per-cell F1 / wall / throughput
  - {out_dir}/matrix.csv    pivot table
  - {out_dir}/confusion.json (if --confusion) per-label TP/FP/FN

Per-dataset default caps live in `DATASET_CONFIGS` so a default run
finishes in ~1 day on 4090. Override:
  --max-per-dataset N  applies a global cap to every dataset
  --no-cap             ignores all per-dataset defaults (full)

CLI:
  --tools      comma list of {nullpii, gliner, presidio, deberta,
               piiranha, regex, ensemble}
  --backend    cpu | cuda
  --datasets   all | <comma list>  — pick a subset by key
  --confusion  emit per-label TP/FP/FN breakdown for each cell
  --pool-size N         nullpii daemon pool (default 4)
  --threads-each N      ORT thread count per daemon (default 4)
  --gliner-threshold F  default 0.8

Single-dataset run example:
  python bench_full.py --datasets bench-bundled --tools nullpii,gliner \\
      --out-dir results/single
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval import public_datasets
from nullpii_eval.adapters import (
    DEFAULT_REGEX_PATTERNS,
    boundary_refined_predictor,
    deberta_pii_predictor,
    gliner_chunked_predictor,
    multi_ensemble_predictor,
    nullpii_pool_predictor,
    piiranha_predictor,
    presidio_predictor,
    regex_recognizer_predictor,
)
from nullpii_eval.datasets import Sample, Span, load
from nullpii_eval.metrics import evaluate, macro_f1


# ─── Dataset registry ────────────────────────────────────────────
@dataclass(frozen=True, slots=True)
class DatasetSpec:
    key: str
    loader: Callable[[int | None], list[Sample]]
    default_n: int | None  # None = use full dataset by default


def _isotonic(loc: str) -> Callable[[int | None], list[Sample]]:
    return lambda n: list(public_datasets._load_isotonic(n, lang=loc).samples)


def _load_nullpii_bench(subset: str, n: int | None) -> list[Sample]:
    path = Path(__file__).resolve().parent.parent / "datasets" / "nullpii-bench.jsonl"
    out: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row["subset"] != subset:
                continue
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            out.append(Sample(row["text"], spans))
            if n and len(out) >= n:
                break
    return out


# default_n picked so a complete run on 4090 finishes <2 days. Override
# globally with --max-per-dataset N (caps everything to N) or --no-cap
# (ignores all defaults, runs full).
DATASET_CONFIGS: list[DatasetSpec] = [
    DatasetSpec("bench-bundled",         lambda n: _load_nullpii_bench("bundled", n),         None),
    DatasetSpec("bench-adversarial",     lambda n: _load_nullpii_bench("adversarial", n),     None),
    DatasetSpec("bench-long-prompts",    lambda n: _load_nullpii_bench("long-prompts", n),    None),
    DatasetSpec("isotonic-en",           _isotonic("en"),                                     30_000),
    DatasetSpec("isotonic-it",           _isotonic("it"),                                     30_000),
    DatasetSpec("isotonic-de",           _isotonic("de"),                                     30_000),
    DatasetSpec("isotonic-fr",           _isotonic("fr"),                                     30_000),
    DatasetSpec("isotonic-es",           _isotonic("es"),                                     30_000),
    DatasetSpec("presidio-synthetic",    lambda n: list(public_datasets._load_presidio_synthetic(n).samples),  5_000),
    DatasetSpec("ai4privacy-300k",       lambda n: list(public_datasets._load_ai4privacy(n).samples),          30_000),
    DatasetSpec("ai4privacy-400k",       lambda n: list(public_datasets._load_ai4privacy_400k(n).samples),     30_000),
    DatasetSpec("bigcode-pii",           lambda n: list(public_datasets._load_bigcode_pii(n).samples),         20_000),
    DatasetSpec("dev-prompts-synth",     lambda n: list(public_datasets._generate_dev_prompts(n).samples),     10_000),
    DatasetSpec("enron-planted",         lambda n: list(public_datasets._load_enron_planted(n).samples),       5_000),
    DatasetSpec("stackoverflow-planted", lambda n: list(public_datasets._load_stackoverflow_planted(n).samples), 5_000),
    DatasetSpec("thestack-planted",      lambda n: list(public_datasets._load_thestack_planted(n).samples),    5_000),
    DatasetSpec("wikiann-en",            lambda n: list(public_datasets._load_wikiann(n, lang="en").samples),   5_000),
    DatasetSpec("conll2003",             lambda n: list(public_datasets._load_conll(n).samples),                None),
]


# ─── Tool builders ───────────────────────────────────────────────
def _wrap_batch(batch_pred):
    def _single(text):
        return batch_pred([text])[0]
    return _single


def build_tools(args) -> dict[str, Callable]:
    backend = args.backend
    builders: dict[str, Callable[[], Callable]] = {
        "nullpii":  lambda: nullpii_pool_predictor(
            pool_size=args.pool_size, threads_each=args.threads_each,
            backend=backend, variant="fp16",
        ),
        "gliner":   lambda: gliner_chunked_predictor(threshold=args.gliner_threshold),
        "presidio": lambda: presidio_predictor(),
        "deberta":  lambda: _wrap_batch(deberta_pii_predictor(device=backend, batch_size=32)),
        "piiranha": lambda: _wrap_batch(piiranha_predictor(device=backend, batch_size=32)),
        "regex":    lambda: regex_recognizer_predictor(patterns=DEFAULT_REGEX_PATTERNS),
    }
    requested = [t.strip() for t in args.tools.split(",") if t.strip()]
    out: dict[str, Callable] = {}
    for t in requested:
        if t == "ensemble":
            continue
        if t not in builders:
            raise SystemExit(f"unknown tool: {t}")
        print(f"[bench] loading {t} ({backend})…", flush=True)
        out[t] = builders[t]()
    if "ensemble" in requested:
        # Best-known config: nullpii + gliner + regex, primary, boundary refine.
        if not all(k in out for k in ("nullpii", "gliner", "regex")):
            raise SystemExit("ensemble requires nullpii,gliner,regex in --tools")
        ens = multi_ensemble_predictor(
            predictors=[out["nullpii"], out["gliner"], out["regex"]],
            strategy="primary",
        )
        out["ensemble"] = boundary_refined_predictor(inner=ens)
        print("[bench] ensemble built (primary + boundary refine)", flush=True)
    return out


# ─── Checkpointed worker ─────────────────────────────────────────
def _checkpoint_paths(ckpt_dir: Path, tool: str, dataset: str) -> tuple[Path, Path]:
    return (
        ckpt_dir / f"{tool}-{dataset}.jsonl",
        ckpt_dir / f"{tool}-{dataset}.state",
    )


def _load_done_idx(state_path: Path) -> int:
    if not state_path.exists():
        return -1
    try:
        return int(state_path.read_text().strip())
    except ValueError:
        return -1


def _iou(a: Span, b: Span) -> float:
    inter = max(0, min(a.end, b.end) - max(a.start, b.start))
    union = (a.end - a.start) + (b.end - b.start) - inter
    return inter / union if union > 0 else 0.0


def _confusion(preds: list[list[Span]], truths: list[list[Span]],
               ) -> dict[str, dict[str, int]]:
    """Per-label TP/FP/FN at IoU≥0.5, same-label match."""
    from collections import defaultdict
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    for ps, ts in zip(preds, truths):
        truths_remaining = list(ts)
        for p in ps:
            matched = -1
            for i, t in enumerate(truths_remaining):
                if t.label == p.label and _iou(p, t) >= 0.5:
                    matched = i
                    break
            if matched >= 0:
                tp[p.label] += 1
                truths_remaining.pop(matched)
            else:
                fp[p.label] += 1
        for t in truths_remaining:
            fn[t.label] += 1
    return {
        lbl: {"tp": tp[lbl], "fp": fp[lbl], "fn": fn[lbl]}
        for lbl in set(tp) | set(fp) | set(fn)
    }


def run_combo(
    tool_name: str, predictor: Callable, dataset: DatasetSpec, samples: list[Sample],
    ckpt_dir: Path, *, want_confusion: bool,
) -> tuple[float, float, int, dict | None]:
    """Returns (f1, wall_seconds, n_processed, confusion_or_None). Resumes from checkpoint."""
    pred_path, state_path = _checkpoint_paths(ckpt_dir, tool_name, dataset.key)
    done_idx = _load_done_idx(state_path)

    truths = [list(s.spans) for s in samples]
    preds: list[list[Span]] = []
    if done_idx >= 0 and pred_path.exists():
        with pred_path.open(encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                preds.append([Span(s[2], int(s[0]), int(s[1])) for s in row["spans"]])
        if len(preds) > done_idx + 1:
            preds = preds[: done_idx + 1]
        elif len(preds) < done_idx + 1:
            done_idx = len(preds) - 1
    print(f"  [{tool_name}/{dataset.key}] resume idx={done_idx + 1}/{len(samples)}", flush=True)

    t0 = time.perf_counter()
    flush_every = 100
    with pred_path.open("a", encoding="utf-8") as f:
        for i in range(done_idx + 1, len(samples)):
            try:
                spans = list(predictor(samples[i].text).spans)
            except Exception as e:
                print(f"  [{tool_name}/{dataset.key}] idx={i} ERROR {type(e).__name__}: {e}", flush=True)
                spans = []
            preds.append(spans)
            f.write(json.dumps({"idx": i, "spans": [(s.start, s.end, s.label) for s in spans]}) + "\n")
            if (i + 1) % flush_every == 0:
                f.flush()
                state_path.write_text(str(i))
                pct = (i + 1) * 100 / max(1, len(samples))
                el = time.perf_counter() - t0
                rate = (i - done_idx) / max(1e-3, el)
                print(f"  [{tool_name}/{dataset.key}] {i + 1}/{len(samples)} "
                      f"({pct:.1f}%) {rate:.1f} samp/s", flush=True)
    state_path.write_text(str(len(samples) - 1))
    el = time.perf_counter() - t0
    f1 = macro_f1(evaluate(preds, truths))
    conf = _confusion(preds, truths) if want_confusion else None
    return f1, el, len(samples), conf


# ─── Main ────────────────────────────────────────────────────────
def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tools", default="nullpii,gliner,presidio,deberta,piiranha,regex,ensemble")
    parser.add_argument("--backend", default="cuda", choices=["cpu", "cuda"])
    parser.add_argument("--datasets", default="all")
    parser.add_argument("--max-per-dataset", type=int, default=0,
                        help="0 = use per-dataset defaults; >0 = cap every dataset to N")
    parser.add_argument("--no-cap", action="store_true",
                        help="ignore per-dataset default caps (full no-cap bench)")
    parser.add_argument("--confusion", action="store_true",
                        help="emit per-label TP/FP/FN to confusion.json")
    parser.add_argument("--out-dir", required=True)
    parser.add_argument("--checkpoint-dir", default="")
    parser.add_argument("--pool-size", type=int, default=4)
    parser.add_argument("--threads-each", type=int, default=4)
    parser.add_argument("--gliner-threshold", type=float, default=0.8)
    parser.add_argument("--parallel-tools", type=int, default=1,
                        help="run N tools concurrently within each dataset (1=serial). "
                             "32GB 5090 fits 4-6 ML tools simultaneously.")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ckpt_dir = Path(args.checkpoint_dir or (out_dir / "checkpoints"))
    ckpt_dir.mkdir(parents=True, exist_ok=True)

    if args.datasets == "all":
        datasets = list(DATASET_CONFIGS)
    else:
        keep = {d.strip() for d in args.datasets.split(",")}
        datasets = [d for d in DATASET_CONFIGS if d.key in keep]
    if not datasets:
        raise SystemExit("no datasets selected")

    print(f"[bench] backend={args.backend} datasets={[d.key for d in datasets]}", flush=True)
    if args.max_per_dataset:
        print(f"[bench] global cap: {args.max_per_dataset} per dataset", flush=True)
    elif args.no_cap:
        print("[bench] no-cap: full datasets (may take days)", flush=True)
    else:
        print("[bench] using per-dataset default caps", flush=True)

    tools = build_tools(args)
    print(f"[bench] tools loaded: {list(tools.keys())}", flush=True)

    matrix: dict[str, dict[str, dict]] = {}
    matrix_path = out_dir / "matrix.json"
    if matrix_path.exists():
        matrix = json.loads(matrix_path.read_text())
    confusion_all: dict[str, dict[str, dict]] = {}
    confusion_path = out_dir / "confusion.json"
    if args.confusion and confusion_path.exists():
        confusion_all = json.loads(confusion_path.read_text())

    for ds in datasets:
        print(f"\n[bench] === DATASET {ds.key} ===", flush=True)
        if args.max_per_dataset:
            n_arg = args.max_per_dataset
        elif args.no_cap:
            n_arg = None
        else:
            n_arg = ds.default_n  # may be None for small datasets
        try:
            samples = ds.loader(n_arg)
        except Exception as e:
            print(f"[bench] FAILED to load {ds.key}: {type(e).__name__}: {e}", flush=True)
            continue
        if not samples:
            print(f"[bench] {ds.key}: 0 samples — skipping", flush=True)
            continue
        cap_label = "full" if n_arg is None else f"cap {n_arg}"
        print(f"[bench] {ds.key}: {len(samples)} samples ({cap_label})", flush=True)

        def _record(tool_name: str, result: tuple[float, float, int, dict | None] | BaseException) -> None:
            if isinstance(result, BaseException):
                print(f"[bench] {tool_name}/{ds.key} CRASHED: "
                      f"{type(result).__name__}: {result}", flush=True)
                return
            f1, el, n, conf = result
            matrix.setdefault(ds.key, {})[tool_name] = {
                "f1": f1, "wall_s": el, "n": n,
                "samples_per_s": n / max(1e-3, el),
            }
            matrix_path.write_text(json.dumps(matrix, indent=2))
            if conf is not None:
                confusion_all.setdefault(ds.key, {})[tool_name] = conf
                confusion_path.write_text(json.dumps(confusion_all, indent=2))
            print(f"[bench] {tool_name}/{ds.key} F1={f1:.4f} {el:.1f}s "
                  f"({n / max(1e-3, el):.1f} samp/s)", flush=True)

        if args.parallel_tools <= 1:
            for tool_name, predictor in tools.items():
                try:
                    res = run_combo(
                        tool_name, predictor, ds, samples, ckpt_dir,
                        want_confusion=args.confusion,
                    )
                    _record(tool_name, res)
                except Exception as e:
                    _record(tool_name, e)
        else:
            print(f"[bench] running {len(tools)} tools in parallel "
                  f"(max_workers={args.parallel_tools})", flush=True)
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel_tools) as ex:
                fut_to_name = {
                    ex.submit(
                        run_combo, tname, pred, ds, samples, ckpt_dir,
                        want_confusion=args.confusion,
                    ): tname
                    for tname, pred in tools.items()
                }
                for fut in concurrent.futures.as_completed(fut_to_name):
                    tname = fut_to_name[fut]
                    try:
                        _record(tname, fut.result())
                    except Exception as e:
                        _record(tname, e)

    # CSV matrix view: rows = datasets, cols = tools.
    csv_path = out_dir / "matrix.csv"
    tool_cols = sorted({t for d in matrix.values() for t in d})
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset", *tool_cols])
        for ds_key in sorted(matrix):
            row = [ds_key]
            for t in tool_cols:
                cell = matrix[ds_key].get(t)
                row.append(f"{cell['f1']:.4f}" if cell else "")
            w.writerow(row)
    print(f"\n[bench] matrix → {matrix_path}", flush=True)
    print(f"[bench] csv    → {csv_path}", flush=True)


if __name__ == "__main__":
    main()
