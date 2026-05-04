#!/usr/bin/env python3
"""Generate third-party adversarial PII corpus via TextAttack.

Uses TextAttack (UVA-NLP, ACL 2020, Apache 2.0) — independent NLP
adversarial-attack framework — to perturb PII spans in ai4privacy
samples. The perturbations and their parameters come from the
TextAttack library, NOT from this project. This produces an
adversarial corpus whose pattern distribution is independent of the
nullpii pipeline development.

Source data:
  - ai4privacy rows 0–N (disjoint from bench eval offset 300k+)
  - 1000 samples sampled per locale; per-span perturbation applied

Perturbations applied (TextAttack `transformations.word_swaps`):
  1. WordSwapHomoglyphSwap — Latin → Unicode homoglyph (Cyrillic а/о,
     Greek е/р/о, etc.)
  2. WordSwapNeighboringCharacterSwap — adjacent char swap (typos)
  3. WordSwapRandomCharacterDeletion — single-char drop
  4. WordSwapRandomCharacterInsertion — single-char insert
  5. WordSwapRandomCharacterSubstitution — single-char replace

Each gold span gets one perturbation applied, yielding ~5x more
adversarial samples than the source (one per perturbation type).

Output schema matches `nullpii-bench.jsonl`:
  `{id, locale, subset, text, spans}`

Subset names map to perturbation type (textattack-homoglyph,
textattack-charswap, textattack-chardelete, textattack-charinsert,
textattack-charsub).
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages" / "eval" / "src"))

from nullpii_eval import public_datasets  # noqa: E402

SEED = 4242


def _build_perturbations():
    from textattack.shared import AttackedText
    from textattack.transformations import (  # noqa: I001
        WordSwapHomoglyphSwap,
        WordSwapNeighboringCharacterSwap,
        WordSwapRandomCharacterDeletion,
        WordSwapRandomCharacterInsertion,
        WordSwapRandomCharacterSubstitution,
    )

    return {
        "textattack-homoglyph": WordSwapHomoglyphSwap(),
        "textattack-charswap": WordSwapNeighboringCharacterSwap(
            random_one=True, skip_first_char=False, skip_last_char=False,
        ),
        "textattack-chardelete": WordSwapRandomCharacterDeletion(
            random_one=True,
        ),
        "textattack-charinsert": WordSwapRandomCharacterInsertion(
            random_one=True,
        ),
        "textattack-charsub": WordSwapRandomCharacterSubstitution(
            random_one=True,
        ),
    }, AttackedText


def _perturb_span(span_text: str, transformation, attacked_text_cls) -> str | None:
    """Apply a TextAttack transformation to `span_text`. Returns the
    perturbed string, or None if the transformation produces no change.

    The transformation operates on AttackedText with a single word of
    interest — we wrap the span text in a sentinel context and extract.
    """
    if not span_text or not span_text.strip():
        return None
    try:
        at = attacked_text_cls(span_text)
        # Get all candidate transformations for the AttackedText. Use
        # all word indices so any word in the span can be perturbed.
        word_indices = list(range(len(at.words)))
        if not word_indices:
            return None
        transformed = transformation(at, indices_to_modify=word_indices)
        if not transformed:
            return None
        # Pick the first transformation result (TextAttack returns
        # multiple variants; we deterministically use the first).
        return transformed[0].text
    except Exception:  # noqa: BLE001
        return None


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n-samples", type=int, default=1000)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()

    random.seed(SEED)

    print(f"[gen] loading ai4privacy 0–{args.n_samples} (disjoint from bench)…")
    samples = list(public_datasets._load_ai4privacy(args.n_samples, offset=0).samples)
    print(f"[gen] loaded {len(samples)} samples")

    print("[gen] building TextAttack transformations…")
    perturbations, attacked_text_cls = _build_perturbations()

    args.out.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    sample_id = 0

    for sample in samples:
        if not sample.spans:
            continue
        for sub_name, transformation in perturbations.items():
            new_text = sample.text
            new_spans = []
            offset_delta = 0
            # Apply perturbation to each gold span; rewrite text + adjust
            # span positions.
            sorted_gold = sorted(sample.spans, key=lambda s: s.start)
            for gs in sorted_gold:
                orig = sample.text[gs.start:gs.end]
                perturbed = _perturb_span(orig, transformation, attacked_text_cls)
                if perturbed is None or perturbed == orig:
                    # Keep span unchanged
                    adjusted_start = gs.start + offset_delta
                    adjusted_end = gs.end + offset_delta
                    new_spans.append({
                        "label": gs.label,
                        "start": adjusted_start,
                        "end": adjusted_end,
                    })
                    continue
                # Replace original span text with perturbed
                adj_start = gs.start + offset_delta
                adj_end = gs.end + offset_delta
                new_text = new_text[:adj_start] + perturbed + new_text[adj_end:]
                new_spans.append({
                    "label": gs.label,
                    "start": adj_start,
                    "end": adj_start + len(perturbed),
                })
                offset_delta += len(perturbed) - (gs.end - gs.start)
            rows.append({
                "id": f"{sub_name}_{sample_id:05d}",
                "locale": "mixed",
                "subset": sub_name,
                "text": new_text,
                "spans": new_spans,
            })
        sample_id += 1
        if sample_id % 100 == 0:
            print(f"[gen] {sample_id}/{len(samples)} → {len(rows)} rows so far")

    with args.out.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    print(f"[gen] wrote {len(rows)} rows → {args.out}")
    by_subset: dict[str, int] = {}
    for r in rows:
        by_subset[r["subset"]] = by_subset.get(r["subset"], 0) + 1
    for s, n in sorted(by_subset.items()):
        print(f"  {s}: {n}")


if __name__ == "__main__":
    main()
