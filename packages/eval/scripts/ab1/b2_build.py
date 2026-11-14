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

A longest run in key position is the key's name, not its value (#104):
an identifier followed by an assignment (`password: …`, `"db_user": …`,
`TOKEN="…"`, `secret => …`) whose last word, or last two, name a
credential (`spring.datasource.password`, `x-api-key`), or that is a name
of two or more words in letters only joined by `_`, `-` or lowerCamelCase
(`client_id`, `dbUser`; not a dotted host or a `ValueError`). The item is
then the value after the assignment, if it lies inside the candidate; it
is AMBIGUOUS if that value is shorter than 8 characters, and the key's
name is AMBIGUOUS if the value is missing, on the next line or outside the
candidate. The documents do not change.

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

WINDOW = 1000
SEED = 0
MIN_CORE = 8
CORE = re.compile(r"[A-Za-z0-9+/_\-.~%=]+")
# A run that opens with a key name and `=` (`api_key=…`,
# `spring.datasource.password=…`) carries the name; the value is what
# follows. A trailing `=` (base64 padding) is not a separator.
KEY_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*=(?=[^=])")
# What follows a key's name: `:` with a blank or a line end after it
# (not `host:port` or `user:pass`), `=`, `=>` or `:=` with any blanks, or
# a quoted key's `":`; each with the value's opening quote.
ASSIGNMENT = re.compile(
    r"""["'`]?[ \t]*(?::=|=>|=|:(?=[ \t]|\r?\n|$))[ \t]*["'`]?|["'`][ \t]*:[ \t]*["'`]?""")
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")
WORD_SEPARATOR = re.compile(r"[_.\-]+")
NAME_SEPARATOR = re.compile(r"[_\-]+")
CAMEL_HUMP = re.compile(r"([a-z0-9])([A-Z])")
# A word of a name: letters, then digits if any (`oauth2`, `password2`).
NAME_WORD = re.compile(r"[a-z]+[0-9]*")
TRAILING_DIGITS = re.compile(r"[0-9]+$")
ONE_CASE_WORD = re.compile(r"[a-z]+|[A-Z]+")
LOWER_CAMEL_WORD = re.compile(r"[a-z]{2,}(?:[A-Z][a-z]{2,})+")
# The last words of src/credential-keys.ts.
CREDENTIAL_LAST_WORDS = frozenset({
    ("password",), ("passwd",), ("pass",), ("pwd",), ("passphrase",), ("secret",), ("token",), ("credential",),
    ("credentials",), ("auth",), ("authorization",), ("authtoken",), ("apikey",), ("api", "key"),
    ("access", "key"), ("private", "key"), ("secret", "key"), ("session",), ("sessionid",), ("session", "id"),
    ("key",), ("bearer",),
})


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


def key_words(run: str) -> list[str]:
    """A name's words, lowercase, split at `_`, `.`, `-` and camelCase humps."""
    return [w.lower() for w in WORD_SEPARATOR.split(CAMEL_HUMP.sub(r"\1_\2", run)) if w]


def names_credential(words: list[str]) -> bool:
    """Whether a name's last word, or last two, name a credential."""
    last = [TRAILING_DIGITS.sub("", w) for w in words[-2:]]
    return tuple(last[-1:]) in CREDENTIAL_LAST_WORDS or (len(last) == 2 and tuple(last) in CREDENTIAL_LAST_WORDS)


def is_key_name(run: str) -> bool:
    """Whether `run` reads as a key's name: an identifier made of words
    whose last ones name a credential, or of two or more words in letters
    only joined by `_`, `-` or lowerCamelCase. A random run (digits inside
    a word, one word, short humps), a dotted host and a `ValueError` read
    as a value."""
    if not IDENTIFIER.fullmatch(run):
        return False
    words = key_words(run)
    if not words or not all(NAME_WORD.fullmatch(w) for w in words):
        return False
    if names_credential(words):
        return True
    parts = [p for p in NAME_SEPARATOR.split(run) if p]
    return len(words) >= 2 and "." not in run and all(
        ONE_CASE_WORD.fullmatch(p) or LOWER_CAMEL_WORD.fullmatch(p) for p in parts)


def scored_span(body: str, at: int, candidate: str, run: tuple[int, int]) -> tuple[int, int, str]:
    """The scored item in body offsets, and why: `value`, `name_cut`
    (the run without a leading `name=`), `key_value` (the value after a
    key's name), `key_no_value` (a key's name whose value is missing or
    outside the candidate: AMBIGUOUS whatever its length)."""
    v = value_part(candidate, run)
    if v != run:
        return at + v[0], at + v[1], "name_cut"
    # `PASSWORD="…"` or `KEY=` with nothing after: the run ends in the
    # assignment's `=`, which `value_part` leaves on it.
    name = candidate[run[0]:run[1]].rstrip("=")
    if not is_key_name(name):
        return at + run[0], at + run[1], "value"
    sep = ASSIGNMENT.match(body, at + run[0] + len(name))
    if sep is None:
        return at + run[0], at + run[1], "value"
    value = CORE.match(body, sep.end())
    if value is None or value.end() > at + len(candidate):
        return at + run[0], at + run[1], "key_no_value"
    return value.start(), value.end(), "key_value"


def documents(df, stats: collections.Counter) -> list[dict]:
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
        # Duplicates by the longest run, as in the first build: the
        # document set does not depend on which item is scored.
        key = (text, at - lo + c[0], at - lo + c[1])
        if key in seen:
            stats[f"drop_duplicate_{row.label}"] += 1
            continue
        seen.add(key)
        secret = int(row.label) == 1
        start, end, why = scored_span(body, at, cand, c)
        if why != "value":
            stats[f"{why}_{row.label}"] += 1
        ambiguous = why == "key_no_value" or end - start < MIN_CORE
        if ambiguous:
            stats[f"ambiguous_{row.label}"] += 1
        docs.append({
            "text": text,
            "items": [{"start": start - lo, "end": end - lo,
                       "class": "AMBIGUOUS" if ambiguous else "MUST_MASK" if secret else "MUST_KEEP",
                       "category": "secret" if secret else "non_secret", "kind": str(row.secret_type),
                       "encoded_of": None}],
        })
    return docs


def main() -> None:
    import pandas as pd

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
