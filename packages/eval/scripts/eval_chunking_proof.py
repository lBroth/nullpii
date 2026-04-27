#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Chunking proof: same nullpii pipeline, two input variants.

Run on `long-prompts-en-baseline.jsonl` (PII positioned past ~750 tokens):

  1. **full**: send the entire prompt → chunked inference covers all of it.
  2. **truncated**: send only the first ~2 KB (~512 tok) → simulates the
     pre-chunking world where the model never saw the tail.

Reports macro F1 for each variant. Δ = chunking value-add.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nullpii_eval.adapters import nullpii_predictor
from nullpii_eval.datasets import Sample, Span, load
from nullpii_eval.metrics import evaluate, macro_f1

# ~4 chars/token (English, BPE) → 2048 chars approximates 512 tokens.
TRUNCATION_CHARS = 2048


def truncate_sample(s: Sample, max_chars: int) -> Sample:
    """Slice text to `max_chars`. Spans starting beyond the cutoff are kept
    as ground-truth (so they count against recall) — that's the whole point:
    in the pre-chunking world they were silently lost."""
    return Sample(text=s.text[:max_chars], spans=s.spans)


def main() -> None:
    samples = list(load("long-prompts-en").samples)
    n_total_spans = sum(len(s.spans) for s in samples)
    spans_in_first_chunk = sum(
        1 for s in samples for sp in s.spans if sp.start < TRUNCATION_CHARS
    )
    print(f"samples: {len(samples)}, spans total: {n_total_spans}")
    print(
        f"spans within first {TRUNCATION_CHARS} chars: {spans_in_first_chunk} "
        f"(rest are 'unreachable' under the old truncation regime)"
    )

    nullpii = nullpii_predictor()
    truths = [list(s.spans) for s in samples]

    # Full prompt — chunking is in effect.
    full_preds = [list(nullpii(s.text).spans) for s in samples]
    full_f1 = macro_f1(evaluate(full_preds, truths))

    # Truncated prompt — simulates pre-chunking behavior.
    trunc_samples = [truncate_sample(s, TRUNCATION_CHARS) for s in samples]
    trunc_preds = [list(nullpii(s.text).spans) for s in trunc_samples]
    trunc_f1 = macro_f1(evaluate(trunc_preds, truths))

    print()
    print(f"  truncated input F1 (simulates old behavior): {trunc_f1:.4f}")
    print(f"  full input F1      (chunking enabled):       {full_f1:.4f}")
    print(f"  Δ from chunking:                            {full_f1 - trunc_f1:+.4f}")

    out_path = Path("/tmp/nullpii-eval/chunking-proof.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "n_samples": len(samples),
                "n_total_spans": n_total_spans,
                "n_spans_within_first_chunk": spans_in_first_chunk,
                "truncated_input_f1": trunc_f1,
                "full_input_f1": full_f1,
                "delta": full_f1 - trunc_f1,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nresults → {out_path}")


if __name__ == "__main__":
    main()
