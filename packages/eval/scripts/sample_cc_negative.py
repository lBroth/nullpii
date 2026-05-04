#!/usr/bin/env python3
"""Sample Common Crawl prose snippets with NO PII for negative-class
training of the v10 LoRA adapters.

Uses HuggingFace `allenai/c4` (Apache 2.0) — Common Crawl filtered
prose. **Two-stage filter** to ensure clean negatives:

  Stage 1 (fast, regex-only): drops snippets with obvious structured
  PII (email, phone, secrets, IBAN, SSN, IP, MAC, URL). ~98% pass-rate
  on raw c4 — too permissive on its own.

  Stage 2 (slow, model-based): runs the production nullpii v6 detector
  (gliner_multi_pii-v1 + URL filter + boundary refinement + RFC
  blocklist). Drops snippets where the model detects any span. This
  catches person names, addresses, dates, and other unstructured PII
  the regex misses (~44% of regex-clean samples still contain
  model-detectable PII per validation, so this stage is mandatory).

The model-based stage costs ~30 seconds per 1000 candidates on Mac
M-series CPU. Total for 25k samples: ~10–15 min wall-clock.

Usage:
  python sample_cc_negative.py \\
    --n 25000 \\
    --max-chars 800 \\
    --out packages/eval/datasets/cc-negative-25k.jsonl \\
    --seed 42
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "eval" / "src"))

# PII regex blocklist for filtering — if any matches, drop the sample.
_PII_FILTERS = [
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),  # email
    re.compile(r"\+\d{1,3}[\s\-.]?\(?\d{1,4}\)?[\s\-.]?\d{2,4}[\s\-.]?\d{3,8}"),  # phone
    re.compile(r"\b(?:AKIA|ASIA|ABIA|ACCA|A3T)[A-Z0-9]{16}\b"),  # AWS
    re.compile(r"\bgh[oprs]_[A-Za-z0-9]{36,}\b"),  # GitHub
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),  # OpenAI / Anthropic
    re.compile(r"\bsk_(?:live|test)_[A-Za-z0-9]{24,}\b"),  # Stripe
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),  # Slack
    re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{1,4}(?:[ \t]?\d{4}){2,5}"),  # IBAN
    re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN US
    re.compile(r"\b\d{16}\b"),  # credit card-shape
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),  # IPv4
    re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b"),  # MAC
    re.compile(r"\b(?:https?://|www\.)[^\s<>\"]+"),  # URL
]


def has_regex_pii(text: str) -> bool:
    return any(p.search(text) for p in _PII_FILTERS)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=25000)
    ap.add_argument("--max-chars", type=int, default=800)
    ap.add_argument("--min-chars", type=int, default=100)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--gliner-threshold", type=float, default=0.5,
                    help="threshold for the model-based PII filter (stage 2)")
    ap.add_argument("--no-model-filter", action="store_true",
                    help="DEBUG ONLY — disable model filter (regex-only). "
                         "Validation showed 44%% of regex-clean samples still "
                         "contain model-detectable PII; do not use for training.")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    random.seed(args.seed)

    # Build the model-based filter once (loads gliner ONNX + regex pack)
    model_predictor = None
    if not args.no_model_filter:
        print("[cc-neg] loading model-based filter (nullpii v6)…")
        sys.path.insert(0, str(ROOT / "packages" / "eval" / "src"))
        from nullpii_eval.adapters import (
            DEFAULT_REGEX_PATTERNS, boundary_refined_predictor,
            gliner_v2_predictor, multi_ensemble_predictor,
            never_pii_filter_predictor, url_filter_predictor,
        )
        model_predictor = never_pii_filter_predictor(
            inner=boundary_refined_predictor(
                inner=multi_ensemble_predictor(
                    predictors=[
                        url_filter_predictor(patterns=DEFAULT_REGEX_PATTERNS),
                        gliner_v2_predictor(
                            "onnx-community/gliner_multi_pii-v1",
                            onnx_file="onnx/model.onnx",
                            threshold=args.gliner_threshold,
                        ),
                    ],
                    strategy="primary",
                ),
            ),
            drop_rfc1918=True,
        )

    print(f"[cc-neg] streaming allenai/c4 (en) until {args.n} clean samples collected…")
    from datasets import load_dataset
    stream = load_dataset("allenai/c4", "en", split="train", streaming=True)

    kept = 0
    rejected_regex = 0
    rejected_model = 0
    with args.out.open("w", encoding="utf-8") as f:
        for ex in stream:
            text = ex.get("text", "") or ""
            if len(text) < args.min_chars:
                continue
            text = text[:args.max_chars]
            # Stage 1: regex filter (fast)
            if has_regex_pii(text):
                rejected_regex += 1
                continue
            # Stage 2: model filter (slow but catches names/addresses/dates)
            if model_predictor is not None:
                result = model_predictor(text)
                if result.spans:
                    rejected_model += 1
                    continue
            row = {
                "id": f"cc-negative-{kept:06d}",
                "locale": "en",
                "subset": "cc-negative",
                "text": text,
                "spans": [],  # explicitly NO PII spans
            }
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            kept += 1
            if kept % 500 == 0:
                print(
                    f"[cc-neg] {kept}/{args.n} kept "
                    f"(regex-rejected: {rejected_regex}, model-rejected: {rejected_model})",
                    flush=True,
                )
            if kept >= args.n:
                break
    print(
        f"[cc-neg] DONE → {args.out} ({kept} samples, "
        f"regex-rejected: {rejected_regex}, model-rejected: {rejected_model})",
    )


if __name__ == "__main__":
    main()
