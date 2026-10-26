# SPDX-License-Identifier: Apache-2.0
"""Publish the gold without redistributing the GitHub issue text.

    python gen/real/publish.py [--src data/ab1.jsonl] [--pool cache/real]
                               [--out data/ab1-public.jsonl] [--meta data/ab1-public.meta.json]

Reads the gold `data/ab1.jsonl` and the local issue pool `cache/real/gh_issues_*.jsonl` and writes
`data/ab1-public.jsonl`: the same rows in the same order, except that every document whose carrier
is a GitHub issue (`carrier.dataset == "github-issues"`) loses its `text` and gets instead

  - `segments`: the document text as an ordered list of pieces, each either
    `{"carrier": [start, end]}` — a range of the normalised carrier text `title + "\\n\\n" + body`
    (the builder's own normalisation, `carriers.issue_text`) — or `{"text": "..."}` — characters the
    builder wrote (an injected snippet, an added line break, an encoded copy);
  - `text_sha256`: the sha256 of the document text (UTF-8), so a rebuild can check itself.

`data/ab1-public.meta.json` records the sha256 of both files, the number of GitHub documents and the
total literal / carrier character counts. Joining the segments from the local pool reproduces every
document byte for byte; a mismatch fails loud.

Prints counts, ids, lengths and hashes only — never document or issue text.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from carriers import REAL_LANGS, issue_text, read_jsonl  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_SRC = ROOT / "data" / "ab1.jsonl"
DEFAULT_POOL = ROOT / "cache" / "real"
DEFAULT_OUT = ROOT / "data" / "ab1-public.jsonl"
DEFAULT_META = ROOT / "data" / "ab1-public.meta.json"

GH_DATASET = "github-issues"
GH_DOCUMENTS = 72
# A piece of carrier text shorter than this may stay literal instead of a carrier range: aligning a
# verbatim excerpt never produces one, so anything bigger means the document text is not the excerpt.
MIN_CARRIER_PIECE = 20


class PublishError(RuntimeError):
    pass


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def carpool_texts(pool_dir: Path) -> dict[str, str]:
    """The normalised carrier text of every issue in the local pool, keyed `<owner>/<repo>#<number>`."""
    texts: dict[str, str] = {}
    for lang in REAL_LANGS:
        path = pool_dir / f"gh_issues_{lang}.jsonl"
        if not path.exists():
            raise PublishError(f"missing issue pool {path}")
        for row in read_jsonl(path):
            key = f"{row['full_name']}#{row['number']}"
            texts[key] = issue_text(row.get("title", ""), row.get("body", ""))
    return texts


def segments_for(doc_text: str, ctext: str, start: int, end: int) -> list[dict]:
    """Align the document text with the carrier excerpt text[start:end]; return its segments."""
    excerpt = ctext[start:end]
    sm = difflib.SequenceMatcher(None, excerpt, doc_text, autojunk=False)
    raw: list[tuple[str, int, int, int, int]] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            raw.append(("carrier", j1, j2, start + i1, start + i2))
        elif tag == "insert":
            raw.append(("text", j1, j2, -1, -1))
        else:  # replace / delete: characters the excerpt has and the document does not (or not there)
            if i2 - i1 >= MIN_CARRIER_PIECE:
                raise PublishError(
                    f"carrier text of {i2 - i1} chars is not verbatim in the document "
                    f"(off {start + i1}..{start + i2})")
            raw.append(("text", j1, j2, -1, -1))
    merged: list[dict] = []
    for kind, ds, de, cs, ce in raw:
        if ds >= de:
            continue
        if (merged and merged[-1]["_k"] == kind and merged[-1]["_de"] == ds
                and (kind == "text" or merged[-1]["_ce"] == cs)):
            merged[-1]["_de"] = de
            if kind == "carrier":
                merged[-1]["_ce"] = ce
            continue
        merged.append({"_k": kind, "_ds": ds, "_de": de, "_cs": cs, "_ce": ce})
    out: list[dict] = []
    for p in merged:
        if p["_k"] == "carrier":
            out.append({"carrier": [p["_cs"], p["_ce"]]})
        else:
            out.append({"text": doc_text[p["_ds"]:p["_de"]]})
    return out


def join_segments(segments: list[dict], ctext: str) -> str:
    parts = []
    for seg in segments:
        if "carrier" in seg:
            a, b = seg["carrier"]
            parts.append(ctext[a:b])
        else:
            parts.append(seg["text"])
    return "".join(parts)


def publish(src: Path, pool_dir: Path, out: Path, meta_path: Path) -> dict:
    rows = read_jsonl(src)
    texts = carpool_texts(pool_dir)
    public: list[dict] = []
    literal_chars = 0
    carrier_chars = 0
    n_gh = 0
    for row in rows:
        carrier = row.get("carrier")
        if not carrier or carrier.get("dataset") != GH_DATASET:
            public.append(row)
            continue
        n_gh += 1
        key = carrier["row"]
        if key not in texts:
            raise PublishError(f"{row['id']}: carrier row {key} is not in the local issue pool")
        ctext = texts[key]
        start, end = carrier["start"], carrier["end"]
        if not 0 <= start < end <= len(ctext):
            raise PublishError(f"{row['id']}: carrier offsets outside the pool text "
                               f"({start}..{end} of {len(ctext)})")
        doc_text = row["text"]
        segments = segments_for(doc_text, ctext, start, end)
        rebuilt = join_segments(segments, ctext)
        if rebuilt != doc_text:
            raise PublishError(f"{row['id']}: segments do not reproduce the document text "
                               f"({len(rebuilt)} vs {len(doc_text)} chars)")
        for seg in segments:
            if "carrier" in seg:
                a, b = seg["carrier"]
                carrier_chars += b - a
            else:
                literal_chars += len(seg["text"])
        new = dict(row)
        del new["text"]
        new["segments"] = segments
        new["text_sha256"] = sha256_text(doc_text)
        public.append(new)
    if n_gh != GH_DOCUMENTS:
        raise PublishError(f"{n_gh} GitHub documents, expected {GH_DOCUMENTS}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for row in public:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    meta = {"source_sha256": sha256_file(src), "public_sha256": sha256_file(out),
            "github_documents": n_gh, "literal_chars": literal_chars, "carrier_chars": carrier_chars}
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{len(public)} rows; {n_gh} GitHub documents; "
          f"carrier chars {carrier_chars}, literal chars {literal_chars}; "
          f"source {meta['source_sha256'][:16]}; public {meta['public_sha256'][:16]}", flush=True)
    return meta


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=str(DEFAULT_SRC))
    ap.add_argument("--pool", default=str(DEFAULT_POOL))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--meta", default=str(DEFAULT_META))
    args = ap.parse_args(argv)
    publish(Path(args.src), Path(args.pool), Path(args.out), Path(args.meta))


if __name__ == "__main__":
    main()
