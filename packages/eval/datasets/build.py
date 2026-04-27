#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build JSONL datasets from `<locale>-templates.txt` template files.

Template format: one prompt per line. PII spans are wrapped as
`{{label|text}}` — the builder strips the markup, computes char
offsets, and emits a JSONL row `{"text": ..., "spans": [...]}`.

Multi-line prompts use `<<<` and `>>>` as delimiters:

  <<<
  multi-line prompt body with {{private_person|John Smith}} ...
  ... and {{private_email|john@example.com}}.
  >>>

Run: `python packages/eval/datasets/build.py`
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parent

LOCALES = ("en", "it", "de", "fr", "es")
SPAN_RE = re.compile(r"\{\{([a-z_]+)\|([^}]+?)\}\}")


def parse_template_file(path: Path) -> list[dict]:
    """Parse `<locale>-templates.txt`. Returns list of `{text, spans}` dicts."""
    raw = path.read_text(encoding="utf-8")
    samples: list[dict] = []
    in_block = False
    block_lines: list[str] = []
    for line in raw.split("\n"):
        if line.strip() == "<<<":
            in_block = True
            block_lines = []
            continue
        if line.strip() == ">>>":
            in_block = False
            samples.append(parse_one("\n".join(block_lines)))
            continue
        if in_block:
            block_lines.append(line)
            continue
        stripped = line.strip()
        if stripped == "" or stripped.startswith("#"):
            continue
        samples.append(parse_one(stripped))
    return samples


def parse_one(annotated: str) -> dict:
    """Strip `{{label|text}}` markers, compute spans against final text."""
    spans: list[dict] = []
    out_chars: list[str] = []
    cursor = 0
    pos = 0
    for m in SPAN_RE.finditer(annotated):
        out_chars.append(annotated[cursor:m.start()])
        prefix_len = m.start() - cursor
        pos += prefix_len
        label, text = m.group(1), m.group(2)
        out_chars.append(text)
        spans.append({"label": label, "start": pos, "end": pos + len(text)})
        pos += len(text)
        cursor = m.end()
    out_chars.append(annotated[cursor:])
    return {"text": "".join(out_chars), "spans": spans}


def main() -> None:
    for locale in LOCALES:
        template = DATASETS_DIR / f"{locale}-templates.txt"
        out = DATASETS_DIR / f"{locale}-baseline.jsonl"
        if not template.is_file():
            print(f"skip {locale} (no templates file)")
            continue
        samples = parse_template_file(template)
        with out.open("w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"{locale}: {len(samples)} samples → {out.name}")


if __name__ == "__main__":
    main()
