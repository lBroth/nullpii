# SPDX-License-Identifier: Apache-2.0
"""Generate the traces-v3 set.

    python3.12 generate.py                      # seed 2026, 600 documents, files in this directory
    python3.12 generate.py --update-readme      # also refresh the statistics block in README.md

Writes traces-v3.jsonl, traces-v3-distractors.jsonl, traces-v3-meta.jsonl and
traces-v3-stats.json, re-reads the JSONL files to re-check the invariants, and
prints the SHA-256 of the JSONL files.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

from tracegen.build import build_corpus
from tracegen.core import DISTRACTOR_SET, GOLD_SET, InvariantError
from tracegen.stats import compute, to_markdown

HERE = os.path.dirname(os.path.abspath(__file__))
README_BEGIN = "<!-- STATS:BEGIN -->"
README_END = "<!-- STATS:END -->"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_jsonl(path: str, rows: list[dict]) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def verify_files(gold_path: str, dist_path: str, expected: int) -> None:
    """Re-read the written files and re-check the invariants on the serialized data."""
    with open(gold_path, encoding="utf-8") as f:
        golds = [json.loads(line) for line in f]
    with open(dist_path, encoding="utf-8") as f:
        dists = [json.loads(line) for line in f]
    if len(golds) != expected or len(dists) != expected:
        raise InvariantError("line count mismatch")
    for g, dd in zip(golds, dists):
        if g["id"] != dd["id"]:
            raise InvariantError("id order mismatch between files")
        n = len(g["text"])
        if not (300 <= n <= 20000):
            raise InvariantError(f"{g['id']} length {n}")
        marks = []
        for s in g["spans"]:
            if s["label"] not in GOLD_SET or not (0 <= s["start"] < s["end"] <= n):
                raise InvariantError(f"{g['id']} bad span {s}")
            marks.append((s["start"], s["end"], "g"))
        for r in dd["regions"]:
            if r["class"] not in DISTRACTOR_SET or not (0 <= r["start"] < r["end"] <= n):
                raise InvariantError(f"{g['id']} bad region {r}")
            marks.append((r["start"], r["end"], "d"))
        marks.sort()
        end_any = end_gold = -1
        for s, e, k in marks:
            if (k == "g" and s < end_any) or (k == "d" and s < end_gold):
                raise InvariantError(f"{g['id']} overlap at {s}")
            end_any = max(end_any, e)
            if k == "g":
                end_gold = max(end_gold, e)


CONVERSATION_LANGUAGES = frozenset({"en", "it", "de", "fr", "es"})


def verify_meta(meta_path: str, gold_rows: list[dict]) -> None:
    """The metadata file has one line per document, same order and ids, valid ISO 639-1 codes."""
    with open(meta_path, encoding="utf-8") as f:
        metas = [json.loads(line) for line in f]
    if len(metas) != len(gold_rows):
        raise InvariantError("meta line count mismatch")
    for m, g in zip(metas, gold_rows):
        if m["id"] != g["id"] or m["template_id"] != g["template_id"]:
            raise InvariantError(f"meta order mismatch at {m['id']}")
        if m["conversation_language"] not in CONVERSATION_LANGUAGES:
            raise InvariantError(f"{m['id']}: bad conversation_language {m['conversation_language']!r}")


def update_readme(md: str, cmd: str, sha_gold: str, sha_dist: str, sha_meta: str) -> None:
    path = os.path.join(HERE, "README.md")
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if README_BEGIN not in text or README_END not in text:
        raise SystemExit("README.md has no statistics markers")
    block = (f"{README_BEGIN}\n\nCommand: `{cmd}`\n\n"
             f"| file | SHA-256 |\n|---|---|\n| `traces-v3.jsonl` | `{sha_gold}` |\n"
             f"| `traces-v3-distractors.jsonl` | `{sha_dist}` |\n| `traces-v3-meta.jsonl` | `{sha_meta}` |\n\n"
             f"{md}\n{README_END}")
    head, rest = text.split(README_BEGIN, 1)
    _, tail = rest.split(README_END, 1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(head + block + tail)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--out", default=HERE)
    ap.add_argument("--update-readme", action="store_true")
    args = ap.parse_args()

    docs = build_corpus(args.seed, args.n)
    gold_rows = [{"id": d.doc_id, "template_id": d.template_id, "text": d.assembled.text, "spans": d.assembled.spans}
                 for d in docs]
    dist_rows = [{"id": d.doc_id, "regions": d.assembled.regions} for d in docs]
    os.makedirs(args.out, exist_ok=True)
    gold_path = os.path.join(args.out, "traces-v3.jsonl")
    dist_path = os.path.join(args.out, "traces-v3-distractors.jsonl")
    meta_rows = [{"id": d.doc_id, "template_id": d.template_id, "conversation_language": d.lang} for d in docs]
    meta_path = os.path.join(args.out, "traces-v3-meta.jsonl")
    write_jsonl(gold_path, gold_rows)
    write_jsonl(dist_path, dist_rows)
    write_jsonl(meta_path, meta_rows)
    verify_files(gold_path, dist_path, args.n)
    verify_meta(meta_path, gold_rows)
    st = compute(docs)
    sha_gold, sha_dist, sha_meta = sha256_file(gold_path), sha256_file(dist_path), sha256_file(meta_path)
    st["sha256"] = {"traces-v3.jsonl": sha_gold, "traces-v3-distractors.jsonl": sha_dist,
                    "traces-v3-meta.jsonl": sha_meta}
    st["command"] = f"python3.12 generate.py --seed {args.seed} --n {args.n}"
    with open(os.path.join(args.out, "traces-v3-stats.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(st, f, ensure_ascii=False, indent=2)
        f.write("\n")
    md = to_markdown(st)
    if args.update_readme:
        update_readme(md, st["command"], sha_gold, sha_dist, sha_meta)
    print(f"command: {st['command']}")
    print(f"sha256  {sha_gold}  traces-v3.jsonl")
    print(f"sha256  {sha_dist}  traces-v3-distractors.jsonl")
    print(f"sha256  {sha_meta}  traces-v3-meta.jsonl")
    print(f"documents {st['documents']}, templates {st['templates']}, gold spans {st['total_gold_spans']}, "
          f"distractor regions {st['total_distractor_regions']}, no-secret {st['documents_without_gold_secret']}, "
          f"no-gold {st['documents_without_any_gold']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
