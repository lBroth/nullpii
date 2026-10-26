# SPDX-License-Identifier: Apache-2.0
"""Convert span offsets captured before 2026-10-18 from UTF-16 code units
to code points.

`score_capture.mjs` wrote the runtime's offsets as they are, and JavaScript
indexes strings by UTF-16 code unit. The gold spans and every scorer are
Python, which indexes code points. Each astral character (most emoji) is two
units and one code point, so every nullpii span after one landed one position
early per such character. Competitor captures come from Python and were never
affected. This rewrites a capture with code-point offsets.

  python utf16_offsets.py --texts tuning-texts-all.jsonl --in A.jsonl --out B.jsonl [--dataset D]

`--dataset` is required for a checkpoint file (`{idx, spans}` rows, one file
per dataset); a spans file (`{dataset, idx, spans}` rows) carries its own.
Prints how many rows and spans changed; never prints text.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def unit_to_point(text: str) -> list[int]:
    """`m[u]` is the code-point offset of UTF-16 offset `u` in `text`."""
    m: list[int] = []
    for cp, ch in enumerate(text):
        m.append(cp)
        if ord(ch) > 0xFFFF:
            m.append(cp)
    m.append(len(text))
    return m


def load_texts(path: Path) -> dict[tuple[str, int], str]:
    texts = {}
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                texts[(row["dataset"], row["idx"])] = row["text"]
    return texts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--texts", type=Path, required=True)
    ap.add_argument("--in", dest="src", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--dataset", help="the dataset of a checkpoint file")
    args = ap.parse_args()
    if args.src.resolve() == args.out.resolve():
        raise SystemExit("--out must differ from --in")
    texts = load_texts(args.texts)
    rows = changed_rows = changed_spans = 0
    with args.src.open(encoding="utf-8") as f, args.out.open("w", encoding="utf-8") as out:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            dataset = row.get("dataset", args.dataset)
            if dataset is None:
                raise SystemExit("a checkpoint file needs --dataset")
            text = texts[(dataset, row["idx"])]
            m = unit_to_point(text)
            spans = []
            for span in row["spans"]:
                start, end, *rest = span
                if end > len(m) - 1:
                    raise SystemExit(f"{dataset}:{row['idx']}: offset {end} beyond the text's {len(m) - 1} UTF-16 units")
                spans.append([m[start], m[end], *rest])
            moved = sum(1 for a, b in zip(row["spans"], spans) if a[:2] != b[:2])
            rows += 1
            changed_rows += moved > 0
            changed_spans += moved
            out.write(json.dumps({**row, "spans": spans}, ensure_ascii=False) + "\n")
    print(json.dumps({"rows": rows, "rows_changed": changed_rows, "spans_changed": changed_spans}))


if __name__ == "__main__":
    main()
