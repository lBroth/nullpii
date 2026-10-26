# SPDX-License-Identifier: Apache-2.0
"""AB-1 component B2 (AB-1 SPEC.md): GitHub issue secret candidates
(Zenodo 17430335, CC BY 4.0) as documents for masking tools.

Every true secret plus an equal seeded sample of non-secrets. A document is
the issue body around the candidate, 1,000 characters each side, cut at
whitespace. The scored item is the candidate's core value: its longest run
of value characters (the candidate string sometimes carries the key name,
quotes or the next line, which no masker is expected to hide), without a
leading `name=` (review, 25 Oct). Rows whose candidate is not in the body,
or whose longest run is shorter than 8 characters, are dropped and counted;
exact duplicate documents are collapsed. An item whose value after the
name is shorter than 8 characters is AMBIGUOUS, scored neither way; its
document stays, so the document set and order are those of the first
build, which every tool ran on.

Values are treated as live: this script prints counts only.

  python b2_build.py --csv main_data.csv --out b2.jsonl
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import random
import re

import pandas as pd

WINDOW = 1000
SEED = 0
MIN_CORE = 8
CORE = re.compile(r"[A-Za-z0-9+/_\-.~%=]+")
# A run that opens with a key name and `=` (`api_key=…`,
# `spring.datasource.password=…`) carries the name; the value is what
# follows. A trailing `=` (base64 padding) is not a separator.
KEY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*=(?=[^=])")


def cut(body: str, start: int, end: int) -> tuple[str, int]:
    """Text around [start, end) widened by WINDOW, cut at whitespace; the
    returned offset is where the text starts in body."""
    lo = max(0, start - WINDOW)
    hi = min(len(body), end + WINDOW)
    if lo > 0:
        m = re.search(r"\s", body[lo:start])
        lo = lo + m.end() if m else start
    if hi < len(body):
        tail = body[end:hi]
        ws = [m.start() for m in re.finditer(r"\s", tail)]
        hi = end + ws[-1] if ws else end
    return body[lo:hi], lo


def core(candidate: str) -> tuple[int, int] | None:
    runs = [(m.start(), m.end()) for m in CORE.finditer(candidate)]
    if not runs:
        return None
    best = max(runs, key=lambda r: (r[1] - r[0], -r[0]))
    return best if best[1] - best[0] >= MIN_CORE else None


def value_part(candidate: str, run: tuple[int, int]) -> tuple[int, int]:
    """`run` without a leading key name and `=`."""
    m = KEY_NAME.match(candidate, run[0], run[1])
    return (m.end(), run[1]) if m else run


def documents(df: pd.DataFrame, stats: collections.Counter) -> list[dict]:
    docs, seen = [], set()
    for row in df.itertuples(index=False):
        body, cand = str(row.body), str(row.candidate_string)
        at = body.find(cand)
        if at < 0:
            stats[f"drop_not_in_body_{row.label}"] += 1
            continue
        c = core(cand)
        if c is None:
            stats[f"drop_short_core_{row.label}"] += 1
            continue
        text, lo = cut(body, at, at + len(cand))
        start, end = at - lo + c[0], at - lo + c[1]
        key = (text, start, end)
        if key in seen:
            stats[f"drop_duplicate_{row.label}"] += 1
            continue
        seen.add(key)
        secret = int(row.label) == 1
        v = value_part(cand, c)
        if v != c:
            stats[f"key_name_cut_{row.label}"] += 1
        short = v[1] - v[0] < MIN_CORE
        if short:
            stats[f"ambiguous_short_value_{row.label}"] += 1
        start, end = at - lo + v[0], at - lo + v[1]
        docs.append({
            "text": text,
            "items": [{"start": start, "end": end,
                       "class": "AMBIGUOUS" if short else "MUST_MASK" if secret else "MUST_KEEP",
                       "category": "secret" if secret else "non_secret", "kind": str(row.secret_type),
                       "encoded_of": None}],
        })
    return docs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    df = pd.read_csv(args.csv)
    stats: collections.Counter = collections.Counter()
    true_docs = documents(df[df.label == 1], stats)
    false_docs = documents(df[df.label == 0], stats)
    rng = random.Random(SEED)
    false_docs = rng.sample(false_docs, len(true_docs))
    rows = true_docs + false_docs
    rng.shuffle(rows)
    lines = [json.dumps({"id": f"b2-{i:05d}", "split": "test", "kind": "b2", "lang": "en", "origin": "b2",
                         "carrier": None, **d}, ensure_ascii=False) for i, d in enumerate(rows)]
    text = "\n".join(lines) + "\n"
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(text)
    print(json.dumps({"docs": len(rows), "secrets": len(true_docs), "non_secrets": len(false_docs), **stats,
                      "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}))


if __name__ == "__main__":
    main()
