# SPDX-License-Identifier: Apache-2.0
"""Developer QA: look for personal-data-looking strings left untagged
(outside every gold span and distractor region) in documents generated with
the development seed. Prints suspicious matches per template.

usage: python qa_untagged.py [--n N] [TEMPLATE_ID ...]
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict

from tracegen.build import build_one
from tracegen.doc import Mode
from tracegen.lists import FAMILY, GIVEN_F, GIVEN_M
from tracegen.templates import load_all

PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "ipv4": re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])"),
    "ipv6": re.compile(r"(?<![:\w])(?:[0-9a-fA-F]{1,4}:){2,7}[0-9a-fA-F]{1,4}(?![:\w])"),
    "mac": re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![\w:])"),
    "iban": re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){3,7}\b"),
    "jwt": re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    "vendor_key": re.compile(r"\b(?:AKIA[A-Z2-7]{16}|ghp_[A-Za-z0-9]{36}|sk_live_\w+|xox[bp]-[\w-]+|glpat-[\w-]{20}|AIza[\w-]{35}|npm_\w{36}|hf_[A-Za-z]{34})"),
    "pem": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "phone": re.compile(r"(?<![\w.])\+\d{1,3}[ -]?\(?\d{1,4}\)?(?:[ .-]?\d{2,4}){2,4}(?![\w.])"),
    "card": re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"),
    "geo": re.compile(r"-?\d{1,2}\.\d{4,7},\s?-?\d{1,3}\.\d{4,7}"),
}

ALL_GIVEN = {n for v in list(GIVEN_F.values()) + list(GIVEN_M.values()) for n in v}
ALL_FAMILY = {n for v in FAMILY.values() for n in v if len(n) > 3}
NAME_RE = re.compile(r"\b([A-ZÀ-Þ][a-zà-ÿ]+)\s+([A-ZÀ-Þ][a-zà-ÿ']+)\b")


def untagged_ranges(a):
    marks = sorted([(s["start"], s["end"]) for s in a.spans] + [(r["start"], r["end"]) for r in a.regions])
    out, pos = [], 0
    for s, e in marks:
        if s > pos:
            out.append((pos, s))
        pos = max(pos, e)
    out.append((pos, len(a.text)))
    return out


def scan(a):
    hits = []
    for s, e in untagged_ranges(a):
        chunk = a.text[s:e]
        for name, rx in PATTERNS.items():
            for m in rx.finditer(chunk):
                hits.append((name, m.group(0)))
        for m in NAME_RE.finditer(chunk):
            if m.group(1) in ALL_GIVEN and m.group(2) in ALL_FAMILY:
                hits.append(("name", m.group(0)))
    return hits


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("tids", nargs="*")
    ap.add_argument("--n", type=int, default=2)
    args = ap.parse_args()
    reg = load_all()
    tids = args.tids or sorted(reg)
    total = 0
    for tid in tids:
        found = defaultdict(set)
        for i in range(args.n):
            for mode in (Mode.FULL, Mode.NO_SECRET, Mode.CLEAN):
                for lang in ("en", "it", "de", "fr", "es"):
                    bd = build_one(reg[tid], "qa", mode, lang, f"qa-3:{tid}:{i}:{mode}:{lang}")
                    for kind, val in scan(bd.assembled):
                        found[kind].add(val)
        if found:
            total += 1
            print(f"== {tid}")
            for kind, vals in sorted(found.items()):
                print(f"   {kind}: {sorted(vals)[:8]}")
    print(f"templates with suspicious untagged strings: {total}/{len(tids)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
