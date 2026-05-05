#!/usr/bin/env python
"""Reproduce competitor claims on their own native datasets with native
label vocabulary.

Each tool is benched on ITS own training-corresponding test split, with
NO label remap to nullpii 8-class. F1 is span-level IoU≥0.5, label-match
required, on the tool's native label set. This isolates "is the
published claim reproducible on the tool's own data?" from "does scope
restriction (8-class) hurt cross-tool comparison?".

Cells:
  - presidio          → presidio-synthetic (PresidioSentenceFaker)
  - gliner-pii-base   → presidio-synthetic + nemotron-pii-test
  - piiranha          → ai4privacy-300k (their training family)
  - nemotron-pii-raw  → nemotron-pii-test (their own test)

Output: results/verify-claims/native-f1.json + per-cell details.

Usage:
    python packages/eval/scripts/verify_claims.py \\
        --out-dir packages/eval/results/verify-claims \\
        --max-per-dataset 1000
"""

from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class NativeSpan:
    label: str
    start: int
    end: int


@dataclass(frozen=True)
class NativeSample:
    text: str
    spans: tuple[NativeSpan, ...]


def _iou(a: NativeSpan, b: NativeSpan) -> float:
    inter = max(0, min(a.end, b.end) - max(a.start, b.start))
    union = (a.end - a.start) + (b.end - b.start) - inter
    return inter / union if union > 0 else 0.0


def _f1(preds: list[list[NativeSpan]],
        truths: list[list[NativeSpan]],
        ) -> tuple[float, dict[str, dict[str, int]], int, int]:
    """IoU≥0.5 partial match, strict label-match. Per-label tp/fp/fn."""
    tp: dict[str, int] = defaultdict(int)
    fp: dict[str, int] = defaultdict(int)
    fn: dict[str, int] = defaultdict(int)
    n_pred = 0
    n_truth = 0
    for ps, ts in zip(preds, truths):
        truths_remaining = list(ts)
        n_pred += len(ps)
        n_truth += len(ts)
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
    labels = set(tp) | set(fp) | set(fn)
    f1s = []
    per_label: dict[str, dict[str, int]] = {}
    for lab in labels:
        prec = tp[lab] / max(1, tp[lab] + fp[lab])
        rec = tp[lab] / max(1, tp[lab] + fn[lab])
        f1 = 2 * prec * rec / max(1e-9, prec + rec)
        f1s.append(f1)
        per_label[lab] = {
            "tp": tp[lab], "fp": fp[lab], "fn": fn[lab],
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(f1, 4),
        }
    macro_f1 = sum(f1s) / max(1, len(f1s))
    return macro_f1, per_label, n_pred, n_truth


# ─── Native dataset loaders ─────────────────────────────────────────


def load_presidio_synthetic_native(n: int) -> list[NativeSample]:
    from presidio_evaluator.data_generator import PresidioSentenceFaker
    faker = PresidioSentenceFaker(
        locale="en_US", lower_case_ratio=0.05, random_seed=2026,
    )
    rows = faker.generate_new_fake_sentences(num_samples=n)
    out: list[NativeSample] = []
    for r in rows[:n]:
        text = str(getattr(r, "fake", getattr(r, "full_text", "")))
        spans = []
        for s in getattr(r, "spans", []) or []:
            spans.append(NativeSpan(
                label=str(getattr(s, "entity_type", "")),
                start=int(getattr(s, "start_position", 0)),
                end=int(getattr(s, "end_position", 0)),
            ))
        out.append(NativeSample(text=text, spans=tuple(spans)))
    return out


def load_nemotron_pii_test_native(n: int) -> list[NativeSample]:
    """Nemotron-PII test split — native 55-class labels, no remap.

    Schema: `spans` is a JSON-encoded string (not list); each entry has
    `start`, `end`, `text`, `label` fields.
    """
    import ast
    from datasets import load_dataset
    ds = load_dataset("nvidia/Nemotron-PII", split="test", streaming=False)
    out: list[NativeSample] = []
    for i, row in enumerate(ds):
        if i >= n:
            break
        text = row.get("text", "")
        spans_raw = row.get("spans", "[]")
        try:
            ents = ast.literal_eval(spans_raw) if isinstance(spans_raw, str) else (spans_raw or [])
        except (ValueError, SyntaxError):
            ents = []
        spans = []
        for e in ents:
            if not isinstance(e, dict):
                continue
            label = str(e.get("label", ""))
            try:
                start = int(e.get("start"))
                end = int(e.get("end"))
            except (TypeError, ValueError):
                continue
            if label and 0 <= start < end <= len(text):
                spans.append(NativeSpan(label=label, start=start, end=end))
        out.append(NativeSample(text=text, spans=tuple(spans)))
    return out


def load_ai4privacy_300k_native(n: int) -> list[NativeSample]:
    """ai4privacy 300k validation split — for piiranha self-bench."""
    from datasets import load_dataset
    ds = load_dataset(
        "ai4privacy/pii-masking-300k", split="validation", streaming=False,
    )
    out: list[NativeSample] = []
    for i, row in enumerate(ds):
        if i >= n:
            break
        text = row.get("source_text", "") or row.get("unmasked_text", "")
        # ai4privacy stores spans in `privacy_mask` (list of {label, start, end, value})
        spans = []
        pm = row.get("privacy_mask", []) or []
        for e in pm:
            label = str(e.get("label", ""))
            try:
                start = int(e.get("start"))
                end = int(e.get("end"))
            except (TypeError, ValueError):
                continue
            if label and 0 <= start < end <= len(text):
                spans.append(NativeSpan(label=label, start=start, end=end))
        out.append(NativeSample(text=text, spans=tuple(spans)))
    return out


# ─── Native predictors (no nullpii 8-class remap) ──────────────────


def make_presidio_native():
    from presidio_analyzer import AnalyzerEngine
    analyzer = AnalyzerEngine()

    def predict(text: str) -> list[NativeSpan]:
        out = []
        for r in analyzer.analyze(text=text, language="en"):
            out.append(NativeSpan(
                label=r.entity_type, start=int(r.start), end=int(r.end),
            ))
        return out
    return predict


def make_gliner_pii_base_native():
    """GLiNER multi PII v1 with FULL native 8-label set (matching the
    model's training labels — NOT remapped). Same model that the bench
    rates as `gliner-onnx-pii-fp32`, but here we use the model's native
    label vocabulary directly. This is the bare baseline.
    """
    from gliner import GLiNER
    model = GLiNER.from_pretrained(
        "onnx-community/gliner_multi_pii-v1",
        load_onnx_model=True,
        onnx_model_file="onnx/model.onnx",
        local_files_only=False,
    )
    # Native GLiNER labels matching its training prompt set.
    labels = [
        "private_person", "private_email", "private_phone",
        "private_address", "private_date", "private_url",
        "account_number", "secret",
    ]

    def predict(text: str) -> list[NativeSpan]:
        out = []
        for e in model.predict_entities(text, labels, threshold=0.5):
            out.append(NativeSpan(
                label=str(e["label"]), start=int(e["start"]), end=int(e["end"]),
            ))
        return out
    return predict


def make_nemotron_pii_native():
    """nvidia/gliner-pii with FULL Nemotron 55-class label set."""
    from gliner import GLiNER
    from nullpii_eval.adapters import _NEMOTRON_PII_LABELS
    model = GLiNER.from_pretrained("nvidia/gliner-pii", local_files_only=False)
    model.eval()
    labels = list(_NEMOTRON_PII_LABELS)

    def predict(text: str) -> list[NativeSpan]:
        out = []
        for e in model.predict_entities(text, labels, threshold=0.3):
            out.append(NativeSpan(
                label=str(e["label"]), start=int(e["start"]), end=int(e["end"]),
            ))
        return out
    return predict


def make_piiranha_native():
    """piiranha with full native ai4privacy 54-label vocabulary.

    Predictor uses HF token-classification head; output BIO tags map
    to native ai4privacy labels (FIRSTNAME, LASTNAME, EMAIL, etc.).
    """
    from transformers import AutoModelForTokenClassification, AutoTokenizer
    import torch

    model_name = "iiiorg/piiranha-v1-detect-personal-information"
    tok = AutoTokenizer.from_pretrained(model_name)
    mdl = AutoModelForTokenClassification.from_pretrained(model_name)
    mdl.eval()
    id2label = mdl.config.id2label

    def predict(text: str) -> list[NativeSpan]:
        enc = tok(text, return_offsets_mapping=True, return_tensors="pt",
                  truncation=True, max_length=512)
        offsets = enc.pop("offset_mapping")[0].tolist()
        with torch.no_grad():
            logits = mdl(**enc).logits[0]
        ids = logits.argmax(dim=-1).tolist()
        # Group consecutive same-label tokens into spans. Skip O / I-O.
        spans = []
        i = 0
        while i < len(ids):
            lab = id2label[ids[i]]
            if lab in ("O", "0", "<pad>") or lab.startswith("LABEL_"):
                i += 1
                continue
            # Strip BIO prefix
            base = re.sub(r"^[BI]-", "", lab) if "-" in lab else lab
            start_off = offsets[i][0]
            end_off = offsets[i][1]
            j = i + 1
            while j < len(ids):
                lab_j = id2label[ids[j]]
                base_j = re.sub(r"^[BI]-", "", lab_j) if "-" in lab_j else lab_j
                if lab_j == "O" or base_j != base:
                    break
                end_off = offsets[j][1]
                j += 1
            if start_off != end_off:
                spans.append(NativeSpan(label=base, start=start_off, end=end_off))
            i = j
        return spans
    return predict


# ─── Bench runner ────────────────────────────────────────────────────


def run_cell(name: str, predict_fn, samples: list[NativeSample],
             ) -> dict:
    t0 = time.perf_counter()
    preds = []
    truths = []
    for s in samples:
        try:
            p = predict_fn(s.text)
        except Exception as e:
            print(f"  [{name}] ERROR on sample: {e}", flush=True)
            p = []
        preds.append(p)
        truths.append(list(s.spans))
    elapsed = time.perf_counter() - t0
    f1, per_label, n_pred, n_truth = _f1(preds, truths)
    label_dist = Counter()
    for ts in truths:
        for t in ts:
            label_dist[t.label] += 1
    return {
        "n_samples": len(samples),
        "n_predicted_spans": n_pred,
        "n_truth_spans": n_truth,
        "macro_f1_native": round(f1, 4),
        "wall_s": round(elapsed, 1),
        "samples_per_s": round(len(samples) / max(1e-3, elapsed), 1),
        "per_label": per_label,
        "gold_label_distribution": dict(label_dist.most_common()),
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--max-per-dataset", type=int, default=1000)
    ap.add_argument("--cells", default="all",
                    help="Comma-sep: presidio,gliner-pii-base,nemotron,piiranha")
    args = ap.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    n = args.max_per_dataset

    requested = (args.cells.split(",")
                 if args.cells != "all"
                 else ["presidio", "gliner-pii-base", "nemotron", "piiranha"])

    print(f"[verify] n={n} cells={requested}", flush=True)
    results: dict[str, dict] = {}

    if "presidio" in requested:
        print("\n[verify] cell=presidio @ presidio-synthetic", flush=True)
        samples = load_presidio_synthetic_native(n)
        pred = make_presidio_native()
        results["presidio @ presidio-synthetic"] = run_cell(
            "presidio", pred, samples,
        )

    if "gliner-pii-base" in requested:
        print("\n[verify] cell=gliner-pii-base @ presidio-synthetic", flush=True)
        samples = load_presidio_synthetic_native(n)
        pred = make_gliner_pii_base_native()
        results["gliner-pii-base @ presidio-synthetic"] = run_cell(
            "gliner-pii-base", pred, samples,
        )

    if "nemotron" in requested:
        print("\n[verify] cell=nemotron-pii-raw @ nemotron-pii-test (native 55-class)", flush=True)
        try:
            samples = load_nemotron_pii_test_native(n)
            pred = make_nemotron_pii_native()
            results["nemotron-pii-raw @ nemotron-pii-test"] = run_cell(
                "nemotron-pii-raw", pred, samples,
            )
        except Exception as e:
            print(f"  [nemotron] FAILED: {type(e).__name__}: {e}", flush=True)
            results["nemotron-pii-raw @ nemotron-pii-test"] = {"error": str(e)}

    if "piiranha" in requested:
        print("\n[verify] cell=piiranha @ ai4privacy-300k validation (native vocab)", flush=True)
        try:
            samples = load_ai4privacy_300k_native(n)
            pred = make_piiranha_native()
            results["piiranha @ ai4privacy-300k-val"] = run_cell(
                "piiranha", pred, samples,
            )
        except Exception as e:
            print(f"  [piiranha] FAILED: {type(e).__name__}: {e}", flush=True)
            results["piiranha @ ai4privacy-300k-val"] = {"error": str(e)}

    out_path = args.out_dir / "native-f1.json"
    out_path.write_text(json.dumps(results, indent=2))
    print(f"\n[verify] wrote {out_path}")
    print("\n=== Summary ===")
    for cell, r in results.items():
        if "error" in r:
            print(f"  {cell:50s} ERROR: {r['error']}")
        else:
            print(f"  {cell:50s} F1={r['macro_f1_native']:.4f} "
                  f"({r['n_samples']} samples, {r['n_predicted_spans']} pred, "
                  f"{r['n_truth_spans']} truth)")


if __name__ == "__main__":
    main()
