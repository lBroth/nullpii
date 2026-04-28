#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Merge per-locale bundled datasets + adversarial + long-prompts into a
single `nullpii-bench.jsonl` shareable dataset.

Schema per row:
  {
    "text": str,                                  # original text
    "spans": [{"label": str, "start": int, "end": int}, ...],
    "locale": str,                                # 'en' / 'it' / 'de' / 'fr' / 'es' / 'multi'
    "subset": str,                                # 'bundled' / 'adversarial' / 'long-prompts'
    "id": str,                                    # stable identifier
  }
"""
from __future__ import annotations

import json
from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parent
OUT = DATASETS_DIR / "nullpii-bench.jsonl"

SOURCES = [
    # (filename, locale, subset)
    ("en-baseline.jsonl", "en", "bundled"),
    ("it-baseline.jsonl", "it", "bundled"),
    ("de-baseline.jsonl", "de", "bundled"),
    ("fr-baseline.jsonl", "fr", "bundled"),
    ("es-baseline.jsonl", "es", "bundled"),
    ("adversarial.jsonl", "en", "adversarial"),
    ("long-prompts-en-baseline.jsonl", "en", "long-prompts"),
]


def main() -> None:
    out_rows: list[dict] = []
    for filename, locale, subset in SOURCES:
        path = DATASETS_DIR / filename
        if not path.is_file():
            print(f"skip missing: {filename}")
            continue
        with path.open(encoding="utf-8") as f:
            for idx, line in enumerate(f):
                row = json.loads(line)
                out_rows.append({
                    "id": f"{subset}-{locale}-{idx:04d}",
                    "locale": locale,
                    "subset": subset,
                    "text": row["text"],
                    "spans": row["spans"],
                })
    with OUT.open("w", encoding="utf-8") as f:
        for r in out_rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"wrote {len(out_rows)} samples → {OUT.name}")
    # Quick stats
    by_subset: dict[str, int] = {}
    by_locale: dict[str, int] = {}
    total_spans = 0
    for r in out_rows:
        by_subset[r["subset"]] = by_subset.get(r["subset"], 0) + 1
        by_locale[r["locale"]] = by_locale.get(r["locale"], 0) + 1
        total_spans += len(r["spans"])
    print(f"  total spans: {total_spans}")
    print("  by subset:", by_subset)
    print("  by locale:", by_locale)


if __name__ == "__main__":
    main()
