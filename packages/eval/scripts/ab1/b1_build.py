# SPDX-License-Identifier: Apache-2.0
"""AB-1 component B1: CredData (Samsung/CredData) secret/non-secret markup as
documents for masking tools.  2,000 true-secret rows and 2,000 labelled
non-secret rows, stratified by Category, one document per row: the labelled
line(s) with 5 lines of context each side.

UPSTREAM CONVENTION (what LineStart/LineEnd/ValueStart/ValueEnd mean)
--------------------------------------------------------------------
Every rule below is taken from the repository's own code, which is the only
consumer of these columns:

* The file is decoded and split exactly as obfuscate_creds.py:554-555 and
  review_data.py:39-40 do it:
      f.read().decode().replace("\r\n", "\n").replace("\r", "\n").split("\n")
  (UTF-8, CRLF/CR normalised to LF, split on LF; a trailing newline yields a
  final empty element).

* LineStart/LineEnd are 1-based and LineEnd is INCLUSIVE: single line is
  lines[LineStart-1] (obfuscate_creds.py:535, review_data.py:46), a multi-line
  markup is "\n".join(lines[LineStart-1:LineEnd]) (review_data.py:49).

* ValueStart/ValueEnd are 0-based CHARACTER offsets, ValueEnd exclusive:
  old_line[ValueStart:ValueEnd] (obfuscate_creds.py:536).

* A missing/empty column is read as -1 (meta_row.py:51-52).

* Negative offsets mean "no value markup" and upstream resolves them in
  review_data.py:97-109:
      ValueStart >= 0 and ValueEnd >= 0  -> data_line[ValueStart:ValueEnd + off]
      ValueStart >= 0 >  ValueEnd       -> data_line[ValueStart:]  (to end of line)
      otherwise (ValueStart < 0)        -> the whole line / whole segment
  with off = len(data_line) - len(lines[LineEnd-1]) (review_data.py:50).  So for
  a multi-line row ValueStart is relative to the start of LineStart and ValueEnd
  is relative to the start of LineEnd -- the two are independent, as meta_row.py
  :78-80 states ("multiline value positions are independent").  This is what
  makes multi-line PEM keys work: all 1,003 true-secret rows with negative
  offsets are multi-line "PEM Private Key" rows, so negative == whole segment.

Values are treated as live secrets: this script prints counts and lengths only,
never values or file contents.

  python3 -I b1_build.py --root ../input/CredData --out out/
"""
from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import math
import os
import random
import typing

SEED = 0
PER_CLASS = 2000
CONTEXT = 5
META_FIELDS = ["Id", "FileID", "Domain", "RepoName", "FilePath", "LineStart", "LineEnd",
               "GroundTruth", "ValueStart", "ValueEnd", "CryptographyKey", "PredefinedPattern",
               "Category"]
KEEP_LABELS = ("T", "F")
DROP_LABELS = ("X",)
# Every drop reason is always reported, even when zero.
DROP_REASONS = ("label_X", "file_missing", "offsets_unusable", "offsets_outside_line",
                "empty_value", "duplicate")


class MetaMarkup(typing.NamedTuple):
    """A meta/*.csv row as read, with -1 for a missing offset column."""
    id: int
    file_path: str
    line_start: int
    line_end: int
    label: str
    value_start: int
    value_end: int
    category: str


class Markup(typing.NamedTuple):
    """A meta row resolved against its file: the value and where it sits."""
    meta: MetaMarkup
    start: int
    end: int
    value: str


def fail(message: str) -> None:
    """Fail loud: no silent fallback anywhere in this script."""
    raise SystemExit(f"ERROR: {message}")


def read_lines(root: str, file_path: str) -> list:
    """Upstream file decoding (obfuscate_creds.py:554-555)."""
    with open(os.path.join(root, file_path), "rb") as fh:
        return fh.read().decode().replace("\r\n", "\n").replace("\r", "\n").split("\n")


def to_offset(raw: str) -> int:
    """meta_row.py:51-52 -- an empty column is -1."""
    raw = raw.strip()
    if not raw:
        return -1
    try:
        return int(raw)
    except ValueError:
        fail(f"non-integer meta offset {raw!r}")


def to_line(raw: str) -> int:
    try:
        return int(raw.strip())
    except ValueError:
        fail(f"non-integer meta line number {raw!r}")


def upstream_span(lines: list, line_start: int, line_end: int, value_start: int,
                  value_end: int) -> tuple:
    """Return (segment, start, end) exactly as upstream resolves a markup row.

    segment is the markup text, start/end are character offsets into it."""
    if line_start < 1 or line_end < line_start:
        return None
    if line_end > len(lines):
        return None
    if line_start == line_end:
        segment = lines[line_start - 1]
        tail = 0
    else:
        segment = "\n".join(lines[line_start - 1:line_end])
        # review_data.py:50
        tail = len(segment) - len(lines[line_end - 1])
    if 0 <= value_start and 0 <= value_end:
        # review_data.py:97-103
        return segment, value_start, value_end + tail
    if 0 <= value_start > value_end:
        # review_data.py:104-107 -- from ValueStart to the end of the line
        return segment, value_start, len(segment)
    # review_data.py:108-109 -- no usable markup: the whole line / whole segment
    return segment, 0, len(segment)


def read_meta(root: str) -> tuple:
    """Every meta/*.csv row, in sorted-file, in-file order."""
    meta_dir = os.path.join(root, "meta")
    if not os.path.isdir(meta_dir):
        fail(f"no meta directory at {meta_dir}")
    names = sorted(n for n in os.listdir(meta_dir) if n.endswith(".csv"))
    if not names:
        fail(f"no *.csv under {meta_dir}")
    rows = []
    for name in names:
        with open(os.path.join(meta_dir, name), newline="") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames != META_FIELDS:
                fail(f"{name}: unexpected header {reader.fieldnames}")
            for row in reader:
                label = row["GroundTruth"]
                if label not in KEEP_LABELS + DROP_LABELS:
                    fail(f"{name}: bad GroundTruth {label!r}")
                rows.append(MetaMarkup(int(row["Id"]), row["FilePath"],
                                       to_line(row["LineStart"]), to_line(row["LineEnd"]), label,
                                       to_offset(row["ValueStart"]),
                                       to_offset(row["ValueEnd"]), row["Category"]))
    return rows, len(names)


def eligible(root: str, rows: list, drops: collections.Counter) -> list:
    """Resolve every row's span, count the drops, return the usable rows."""
    by_file = collections.OrderedDict()
    for meta in rows:
        if meta.label in DROP_LABELS:
            drops["label_X"] += 1
            continue
        by_file.setdefault(meta.file_path, []).append(meta)

    usable = []
    seen = set()
    for file_path, file_rows in by_file.items():
        if not os.path.isfile(os.path.join(root, file_path)):
            drops["file_missing"] += len(file_rows)
            continue
        lines = read_lines(root, file_path)
        for meta in file_rows:
            span = upstream_span(lines, meta.line_start, meta.line_end, meta.value_start,
                                 meta.value_end)
            if span is None:
                drops["offsets_unusable"] += 1
                continue
            segment, start, end = span
            if start < 0 or end < start:
                drops["offsets_unusable"] += 1
                continue
            if start > len(segment) or end > len(segment):
                drops["offsets_outside_line"] += 1
                continue
            value = segment[start:end]
            if not value.strip():
                drops["empty_value"] += 1
                continue
            key = (file_path, meta.line_start, meta.line_end, meta.value_start, meta.value_end)
            if key in seen:
                drops["duplicate"] += 1
                continue
            seen.add(key)
            usable.append(Markup(meta, start, end, value))
    return usable


def allocate(counts: dict, seats: int) -> dict:
    """Largest-remainder apportionment; ties broken by category name."""
    total = sum(counts.values())
    if total < seats:
        fail(f"only {total} usable rows for {seats} seats")
    quota = {c: seats * n / total for c, n in counts.items()}
    base = {c: int(math.floor(q)) for c, q in quota.items()}
    left = seats - sum(base.values())
    order = sorted(counts, key=lambda c: (-(quota[c] - base[c]), c))
    for category in order[:left]:
        base[category] += 1
    for category, take in base.items():
        if take > counts[category]:
            fail(f"allocated {take} rows of category {category!r} but only "
                 f"{counts[category]} available")
    return {c: k for c, k in base.items() if k}


def sample(usable: list, label: str, rng: random.Random) -> list:
    """Stratified draw of PER_CLASS rows of one label."""
    pool = [r for r in usable if r.meta.label == label]
    if len(pool) < PER_CLASS:
        fail(f"only {len(pool)} usable {label} rows, need {PER_CLASS}")
    counts = collections.Counter(r.meta.category for r in pool)
    plan = allocate(counts, PER_CLASS)
    by_category = collections.defaultdict(list)
    for row in pool:
        by_category[row.meta.category].append(row)
    picked = []
    for category in sorted(plan):  # rows sorted by Id within the category
        picked.extend(rng.sample(sorted(by_category[category], key=lambda r: r.meta.id),
                                 plan[category]))
    if len(picked) != PER_CLASS:
        fail(f"{label} sample has {len(picked)} rows, expected {PER_CLASS}")
    return picked


def build_document(root: str, row: Markup) -> dict:
    """The labelled line(s) plus CONTEXT lines each side."""
    meta = row.meta
    lines = read_lines(root, meta.file_path)
    first = max(0, meta.line_start - 1 - CONTEXT)
    last = min(len(lines), meta.line_end + CONTEXT)
    head = lines[first:meta.line_start - 1]
    text = "\n".join(lines[first:last])
    base = len("\n".join(head)) + 1 if head else 0
    doc_start, doc_end = base + row.start, base + row.end
    if text[doc_start:doc_end] != row.value:
        fail("document window does not carry upstream's value at the item offsets")
    return {
        "text": text,
        "items": [{
            "start": doc_start,
            "end": doc_end,
            "class": "MUST_MASK" if meta.label == "T" else "MUST_KEEP",
            "category": "secret" if meta.label == "T" else "non_secret",
            "kind": meta.category,
        }],
        "source": {"meta_id": meta.id, "file": meta.file_path, "line_start": meta.line_start,
                   "line_end": meta.line_end},
        "_meta": (meta.value_start, meta.value_end),
    }


def check_documents(root: str, documents: list) -> int:
    """Fail loud if any document is not exactly upstream's markup."""
    if len(documents) != 2 * PER_CLASS:
        fail(f"{len(documents)} documents, expected {2 * PER_CLASS}")
    ids = [d["source"]["meta_id"] for d in documents]
    if len(set(ids)) != len(ids):
        fail("duplicate sampled meta Id")
    multi_line = 0
    by_file = collections.defaultdict(list)
    for doc in documents:
        by_file[doc["source"]["file"]].append(doc)
    for file_path, docs in by_file.items():
        lines = read_lines(root, file_path)
        for doc in docs:
            text, item = doc["text"], doc["items"][0]
            start, end = item["start"], item["end"]
            if not 0 <= start < end <= len(text):
                fail(f"item span {start}:{end} outside document of length {len(text)}")
            src = doc["source"]
            # Re-derive the value independently: fresh file read, fresh upstream
            # span resolution from the raw meta offsets.
            value_start, value_end = doc["_meta"]
            span = upstream_span(lines, src["line_start"], src["line_end"], value_start, value_end)
            if span is None:
                fail("markup row is not resolvable in the re-read file")
            raw = span[0][span[1]:span[2]]
            if text[start:end] != raw:
                fail("item text differs from the value cut from the file")
            # Edge whitespace must come from upstream's own span, never from our
            # window or from trimming.
            edge = raw[:1].isspace() or raw[-1:].isspace()
            if (edge != (text[start:end][:1].isspace() or text[start:end][-1:].isspace())):
                fail("edge whitespace of the item does not match upstream's span")
            if src["line_start"] != src["line_end"]:
                multi_line += 1
    return multi_line


def main() -> None:
    parser = argparse.ArgumentParser(prog="python3 -I b1_build.py")
    parser.add_argument("--root", required=True, help="CredData root (meta/ and data/)")
    parser.add_argument("--out", required=True, help="output directory")
    args = parser.parse_args()

    drops: collections.Counter = collections.Counter({reason: 0 for reason in DROP_REASONS})
    rows, meta_files = read_meta(args.root)
    usable = eligible(args.root, rows, drops)

    rng = random.Random(SEED)
    true_rows = sample(usable, "T", rng)   # T sample first, then F, same rng
    false_rows = sample(usable, "F", rng)
    chosen = true_rows + false_rows
    rng.shuffle(chosen)

    documents = []
    for row in chosen:
        doc = build_document(args.root, row)
        documents.append(doc)
    multi_line = check_documents(args.root, documents)

    lines_out = []
    for number, doc in enumerate(documents):
        doc.pop("_meta")
        row = {"id": f"b1-{number:05d}", "split": "test", "kind": "b1", "lang": "en",
               "origin": "b1", "text": doc["text"], "items": doc["items"],
               "source": doc["source"]}
        lines_out.append(json.dumps(row, ensure_ascii=False))

    os.makedirs(args.out, exist_ok=True)
    jsonl = "\n".join(lines_out) + "\n"
    ids_text = "".join(f"{doc['source']['meta_id']}\n" for doc in documents)
    jsonl_path = os.path.join(args.out, "b1.jsonl")
    ids_path = os.path.join(args.out, "b1_ids.txt")
    with open(jsonl_path, "w", encoding="utf-8") as fh:
        fh.write(jsonl)
    with open(ids_path, "w", encoding="utf-8") as fh:
        fh.write(ids_text)

    by_class = collections.Counter(doc["items"][0]["class"] for doc in documents)
    categories = collections.defaultdict(set)
    for doc in documents:
        categories[doc["items"][0]["class"]].add(doc["items"][0]["kind"])
    print(json.dumps({
        "meta_files": meta_files,
        "meta_rows": len(rows),
        "usable_rows": len(usable),
        "rows": len(documents),
        "by_class": dict(by_class),
        "drops": {reason: drops[reason] for reason in DROP_REASONS},
        "categories_sampled": {k: len(v) for k, v in sorted(categories.items())},
        "multi_line_items": multi_line,
        "sha256": {
            "b1.jsonl": hashlib.sha256(jsonl.encode("utf-8")).hexdigest(),
            "b1_ids.txt": hashlib.sha256(ids_text.encode("utf-8")).hexdigest(),
        },
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
