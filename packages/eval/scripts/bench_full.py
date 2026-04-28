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
    openai_pipeline_batch_predictor,
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


# Dev-focused dataset suite (open licensing only).
#
#  - bench-* — project-bundled, Apache 2.0
#  - dev-prompts-synth — local generator, Apache 2.0, fully synthetic
#  - enron-planted — Enron Email Corpus (FERC public-domain release)
#                    + planted PII at known offsets
#  - stackoverflow-planted — StackExchange CC-BY-SA archive
#                            + planted PII at known offsets
#
# Excluded:
#  - bigcode/bigcode-pii-dataset — gated, requires auth + acceptance
#  - bigcode/the-stack-smol — opt-out concerns; not safe-by-default
#  - ai4privacy / Isotonic / wikiann / conll / presidio-synthetic —
#    helpers in public_datasets.py kept for future use but not
#    registered here. Re-register if needed.
#
# ~65k samples total; nullpii cpu pool=8 → ~3h on RunPod 5090 host.
# Override with --max-per-dataset N or --no-cap.
DATASET_CONFIGS: list[DatasetSpec] = [
    DatasetSpec("bench-bundled",         lambda n: _load_nullpii_bench("bundled", n),         None),
    DatasetSpec("bench-adversarial",     lambda n: _load_nullpii_bench("adversarial", n),     None),
    DatasetSpec("bench-long-prompts",    lambda n: _load_nullpii_bench("long-prompts", n),    None),
    DatasetSpec("dev-prompts-synth",     lambda n: list(public_datasets._generate_dev_prompts(n).samples),     30_000),
    DatasetSpec("enron-planted",         lambda n: list(public_datasets._load_enron_planted(n).samples),       10_000),
    DatasetSpec("stackoverflow-planted", lambda n: list(public_datasets._load_stackoverflow_planted(n).samples), 10_000),
]


# ─── Tool builders ───────────────────────────────────────────────
def _wrap_batch(batch_pred):
    def _single(text):
        return batch_pred([text])[0]
    return _single


def build_tools(args) -> dict[str, Callable]:
    backend = args.backend
    nullpii_backend = args.nullpii_backend or backend
    openai_backend = args.openai_backend or backend
    builders: dict[str, Callable[[], Callable]] = {
        "nullpii":  lambda: nullpii_pool_predictor(
            pool_size=args.pool_size, threads_each=args.threads_each,
            backend=nullpii_backend, variant="fp16",
        ),
        "gliner":   lambda: gliner_chunked_predictor(threshold=args.gliner_threshold),
        "presidio": lambda: presidio_predictor(),
        "deberta":  lambda: _wrap_batch(deberta_pii_predictor(device=backend, batch_size=32)),
        "piiranha": lambda: _wrap_batch(piiranha_predictor(device=backend, batch_size=32)),
        # Bare openai/privacy-filter via HF transformers pipeline — no nullpii
        # pipeline overlay (no BIOES/Viterbi/chunking). Apple-to-apple delta
        # vs `nullpii` row shows what the custom pipeline adds.
        "openai":   lambda: _wrap_batch(openai_pipeline_batch_predictor(device=openai_backend, batch_size=8)),
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
    """Returns (f1, wall_seconds, n_processed, confusion_or_None).

    Resumes from checkpoint. Per-sample exceptions ARE NOT swallowed —
    they propagate up to the caller. The caller (main()) records the
    cell as CRASHED in the matrix and moves on to the next combo.
    """
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
                # No silent recovery — flush partial state then re-raise so
                # the (tool, dataset) cell is marked CRASHED at the outer
                # loop. Empty-spans fallback would silently corrupt F1.
                f.flush()
                state_path.write_text(str(i - 1))
                msg = f"{type(e).__name__}: {e}"
                print(f"  [{tool_name}/{dataset.key}] idx={i} FATAL {msg}", flush=True)
                raise RuntimeError(
                    f"{tool_name}/{dataset.key} failed at idx={i}: {msg}",
                ) from e
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
    parser.add_argument("--nullpii-backend", default="",
                        help="override backend just for nullpii (e.g. cpu when ORT MoE "
                             "kernels lack Blackwell SM_120 support). Defaults to --backend.")
    parser.add_argument("--openai-backend", default="",
                        help="override backend just for the bare openai/privacy-filter "
                             "HF pipeline (1.3B params; CPU inference is too slow). "
                             "Defaults to --backend.")
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
            msg = f"{type(e).__name__}: {e}"
            print(f"[bench] FAILED to load {ds.key}: {msg}", flush=True)
            # Record the failure visibly in the matrix so post-hoc
            # readers see WHY a dataset is missing, not just absence.
            matrix.setdefault(ds.key, {})["_load_error"] = msg
            matrix_path.write_text(json.dumps(matrix, indent=2))
            continue
        if not samples:
            print(f"[bench] {ds.key}: 0 samples — skipping", flush=True)
            matrix.setdefault(ds.key, {})["_load_error"] = "loader returned 0 samples"
            matrix_path.write_text(json.dumps(matrix, indent=2))
            continue
        cap_label = "full" if n_arg is None else f"cap {n_arg}"
        print(f"[bench] {ds.key}: {len(samples)} samples ({cap_label})", flush=True)

        def _record(tool_name: str, result: tuple | BaseException) -> None:
            if isinstance(result, BaseException):
                err = f"{type(result).__name__}: {result}"
                print(f"[bench] {tool_name}/{ds.key} CRASHED: {err}", flush=True)
                # Record CRASHED status in the matrix — invisible skips
                # would silently corrupt the comparison story.
                matrix.setdefault(ds.key, {})[tool_name] = {
                    "status": "CRASHED",
                    "error": err,
                    "f1": None,
                    "wall_s": 0.0,
                    "n": 0,
                    "samples_per_s": 0.0,
                }
                matrix_path.write_text(json.dumps(matrix, indent=2))
                return
            f1, el, n, conf = result
            matrix.setdefault(ds.key, {})[tool_name] = {
                "status": "OK",
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
    tool_cols = sorted({
        t for d in matrix.values() for t in d
        if not t.startswith("_")
    })
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["dataset", *tool_cols])
        for ds_key in sorted(matrix):
            row = [ds_key]
            for t in tool_cols:
                cell = matrix[ds_key].get(t)
                if not cell:
                    row.append("")
                elif cell.get("status") == "CRASHED":
                    row.append("CRASHED")
                elif cell.get("f1") is None:
                    row.append("")
                else:
                    row.append(f"{cell['f1']:.4f}")
            w.writerow(row)
    print(f"\n[bench] matrix → {matrix_path}", flush=True)
    print(f"[bench] csv    → {csv_path}", flush=True)

    # Summary: surface failures explicitly so they cannot be missed.
    failures: list[str] = []
    for ds_key, cells in matrix.items():
        if "_load_error" in cells:
            failures.append(f"  LOAD_FAIL  {ds_key}: {cells['_load_error']}")
        for tname, cell in cells.items():
            if tname.startswith("_"):
                continue
            if cell.get("status") == "CRASHED":
                failures.append(f"  CRASHED    {tname}/{ds_key}: {cell.get('error', '?')}")
    if failures:
        print(f"\n[bench] {len(failures)} CELLS WITH FAILURES:", flush=True)
        for line in failures:
            print(line, flush=True)
    else:
        print("\n[bench] no failures recorded.", flush=True)


if __name__ == "__main__":
    main()
