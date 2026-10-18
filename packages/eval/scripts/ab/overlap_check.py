# SPDX-License-Identifier: Apache-2.0
"""Verbatim overlap between candidate evaluation sets and training or tuning
data (PROTOCOL rule change 9, step 1).

Texts are lowercased and reduced to their word tokens (`\\w+`, Unicode), so
whitespace and punctuation differences do not hide a copy. A document is
represented by its 10-word shingles; a deterministic hash keeps one shingle
in `SAMPLE_EVERY`, so memory stays bounded and both sides sample the same
shingles. For every target set and reference corpus it reports the share of
the target's sampled shingles found in the reference, and the share of
target documents with at least one hit. Prints counts only, never text.

  python overlap_check.py --targets piimb/texts.jsonl --tasks mapa-eur-lex,privy,gretel \\
      --corpus train-H3b-runtime.jsonl --tuning tuning-texts-all.jsonl --out overlap.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterable, Iterator
from pathlib import Path

SHINGLE_WORDS = 10
SAMPLE_EVERY = 8
WORD = re.compile(r"\w+")
# HF datasets the compared tools declare as training data, and the text field.
HF_REFERENCES = {
    "nemotron-pii-train": ("nvidia/Nemotron-PII", "text"),
    "ai4privacy-200k": ("ai4privacy/pii-masking-200k", "source_text"),
    "ai4privacy-400k": ("ai4privacy/pii-masking-400k", "source_text"),
    "ai4privacy-open-500k": ("ai4privacy/open-pii-masking-500k-ai4privacy", "source_text"),
    "isotonic-200k": ("Isotonic/pii-masking-200k", "unmasked_text"),
}


def shingles(text: str) -> Iterator[int]:
    """Sampled 10-word shingle hashes of `text` (stable across runs)."""
    words = WORD.findall(text.lower())
    for i in range(len(words) - SHINGLE_WORDS + 1):
        digest = hashlib.blake2b(" ".join(words[i : i + SHINGLE_WORDS]).encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        if value % SAMPLE_EVERY == 0:
            yield value


def reference_set(texts: Iterable[str]) -> set[int]:
    out: set[int] = set()
    for t in texts:
        out.update(shingles(t))
    return out


def jsonl(path: Path) -> Iterator[dict]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def corpus_texts(path: Path) -> Iterator[str]:
    """A training corpus row: raw `text`, or `tokenized_text` words."""
    for row in jsonl(path):
        yield row["text"] if "text" in row else " ".join(row["tokenized_text"])


def hf_texts(name: str, field: str) -> Iterator[str]:
    from datasets import load_dataset

    for row in load_dataset(name, split="train"):
        yield str(row[field] or "")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", type=Path, required=True, help="jsonl with `dataset` and `text` fields")
    ap.add_argument("--tasks", required=True, help="comma list of target dataset names")
    ap.add_argument("--corpus", type=Path, help="nullpii's training corpus (jsonl)")
    ap.add_argument("--tuning", type=Path, help="nullpii's tuning texts (jsonl with `text`)")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()

    tasks = args.tasks.split(",")
    targets: dict[str, list[list[int]]] = {t: [] for t in tasks}
    for row in jsonl(args.targets):
        if row["dataset"] in targets:
            targets[row["dataset"]].append(list(shingles(row["text"])))
    references: list[tuple[str, Iterable[str]]] = []
    if args.corpus:
        references.append(("nullpii-train", corpus_texts(args.corpus)))
    if args.tuning:
        references.append(("nullpii-tuning", (r["text"] for r in jsonl(args.tuning))))
    references += [(key, hf_texts(name, field)) for key, (name, field) in HF_REFERENCES.items()]

    report: dict[str, dict] = {}
    for ref_name, texts in references:
        ref = reference_set(texts)
        for task, docs in targets.items():
            total = sum(len(d) for d in docs)
            hits = sum(sum(1 for h in d if h in ref) for d in docs)
            docs_hit = sum(1 for d in docs if any(h in ref for h in d))
            report.setdefault(task, {})[ref_name] = {
                "shingle_share": hits / total if total else 0.0,
                "docs_hit_share": docs_hit / len(docs) if docs else 0.0,
                "docs": len(docs),
                "sampled_shingles": total,
            }
            print(f"{task:14s} vs {ref_name:22s} shingles {hits / total if total else 0:.4f}  docs {docs_hit}/{len(docs)}", flush=True)
        del ref
    args.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
