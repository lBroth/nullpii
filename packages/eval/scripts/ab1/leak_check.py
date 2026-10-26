#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Leak check between the ab1 benchmark and a GLiNER-style training corpus.

Usage:
  python -I leak_check.py --gold ../input/ab1.jsonl --names ../input/names \
      --train T1.jsonl [T2.jsonl ...] --out out/

stdlib + numpy only.

Outputs (in --out): flagged.jsonl, one row per flagged benchmark document.
Also prints one JSON summary.

A document is flagged when any near-duplicate ratio reaches 0.8, or when at least
one of its injected MUST_MASK values occurs in the training corpus.  Reasons are
near_dup_jaccard, near_dup_contain_train_in_doc, near_dup_contain_doc_in_train and
value_hit.  train_src lists the distinct `src` labels of the training rows that
produced the flags (deduplicated: `src` names a corpus source, and a hundred
thousand matching rows would otherwise be repeated verbatim).

Privacy: benchmark text and injected values are never printed or written.
Only ids, counts, ratios and src labels leave this script.
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time

import numpy as np

TOKEN_RE = re.compile(r"\w+(?:[-_]\w+)*|\S")
SHINGLE_N = 13
SEP = "\x1f"
THRESHOLD = 0.8
TOKENIZER_CHECK_ROWS = 1000
FLUSH_ROWS = 2000

REASON_J = "near_dup_jaccard"
REASON_RD = "near_dup_contain_train_in_doc"
REASON_DR = "near_dup_contain_doc_in_train"
REASON_V = "value_hit"
REASON_ORDER = (REASON_J, REASON_RD, REASON_DR, REASON_V)


def tokenize(text):
    """GLiNER word splitter, lowercased."""
    return [t.lower() for t in TOKEN_RE.findall(text)]


def shingle_hashes(tokens):
    """Sorted unique uint64 hashes of the 13-token windows of `tokens`."""
    n = len(tokens)
    if n < SHINGLE_N:
        return np.empty(0, dtype=np.uint64)
    buf = bytearray()
    for i in range(n - SHINGLE_N + 1):
        window = SEP.join(tokens[i:i + SHINGLE_N]).encode("utf-8")
        buf += hashlib.blake2b(window, digest_size=8).digest()
    arr = np.frombuffer(bytes(buf), dtype="<u8").astype(np.uint64)
    return np.unique(arr)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def iter_train_rows(paths):
    """Yield (file_index, byte_offset, raw_line_bytes) for every non-blank row."""
    for fi, path in enumerate(paths):
        with open(path, "rb") as fh:
            while True:
                off = fh.tell()
                line = fh.readline()
                if not line:
                    break
                if not line.strip():
                    continue
                yield fi, off, line


def load_gold(path):
    docs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            row = json.loads(line)
            tokens = tokenize(row["text"])
            docs.append({
                "id": row["id"],
                "split": row["split"],
                "tokens": tokens,
                "shingles": shingle_hashes(tokens),
                "values": [
                    (it["start"], it["end"], tokenize(row["text"][it["start"]:it["end"]]))
                    for it in row["items"] if it["class"] == "MUST_MASK"
                ],
            })
    if not docs:
        raise SystemExit("no benchmark documents in %s" % path)
    return docs


def load_name_set(names_dir):
    names = set()
    for lang in sorted(os.listdir(names_dir)):
        d = os.path.join(names_dir, lang)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(".txt"):
                continue
            with open(os.path.join(d, fn), encoding="utf-8") as fh:
                for line in fh:
                    name = line.strip()
                    if name:
                        names.add(name.lower())
    if not names:
        raise SystemExit("no names found under %s" % names_dir)
    return names


class TrainFile:
    """Multi-pass reader over the training files with row-id -> byte-offset lookup."""

    def __init__(self, paths):
        self.paths = list(paths)
        self.row_file = []
        self.row_off = []
        self.row_src = []
        self.n_rows = 0
        self._handles = {}

    def scan(self, gold_hashes, watched, tokenizer_check_rows):
        """Pass 1: shingle index (restricted to gold hashes), token->document frequencies.

        Returns (shingle_hashes, shingle_row_ids, df, tokenizer_ok, tokenizer_checked).
        """
        want_shingles = gold_hashes.size > 0
        h_chunks, r_chunks = [], []
        pend_h, pend_r = [], []
        df = {}
        checked = 0
        ok = 0

        for fi, off, raw in iter_train_rows(self.paths):
            row = json.loads(raw.decode("utf-8"))
            tokens = [t.lower() for t in row["tokenized_text"]]
            src = row["src"]
            rid = self.n_rows
            self.row_file.append(fi)
            self.row_off.append(off)
            self.row_src.append(src)
            self.n_rows += 1

            if checked < tokenizer_check_rows:
                checked += 1
                if tokenize(" ".join(tokens)) == tokens:
                    ok += 1

            if want_shingles:
                sh = shingle_hashes(tokens)
                if sh.size:
                    pos = np.searchsorted(gold_hashes, sh)
                    np.clip(pos, 0, gold_hashes.size - 1, out=pos)
                    sel = sh[gold_hashes[pos] == sh]
                    if sel.size:
                        pend_h.append(sel)
                        pend_r.append(np.full(sel.size, rid, dtype=np.int64))

            if watched:
                for t in watched.intersection(tokens):
                    df[t] = df.get(t, 0) + 1

            if pend_h and (rid % FLUSH_ROWS == FLUSH_ROWS - 1):
                h_chunks.append(np.concatenate(pend_h))
                r_chunks.append(np.concatenate(pend_r))
                pend_h, pend_r = [], []

        if pend_h:
            h_chunks.append(np.concatenate(pend_h))
            r_chunks.append(np.concatenate(pend_r))

        if h_chunks:
            h = np.concatenate(h_chunks)
            r = np.concatenate(r_chunks)
            order = np.argsort(h, kind="stable")
            h = h[order]
            r = r[order]
        else:
            h = np.empty(0, dtype=np.uint64)
            r = np.empty(0, dtype=np.int64)

        if self.n_rows == 0:
            raise SystemExit("no training rows found in %s" % (self.paths,))
        return h, r, df, ok, checked

    def probe_postings(self, probe_set, tid):
        """Pass 2: (watched-token id, row id) pairs for the probe tokens only."""
        t_chunks, r_chunks = [], []
        pend_t, pend_r = [], []
        rid = 0
        for fi, off, raw in iter_train_rows(self.paths):
            row = json.loads(raw.decode("utf-8"))
            tokens = [t.lower() for t in row["tokenized_text"]]
            hit = probe_set.intersection(tokens)
            if hit:
                for t in hit:
                    pend_t.append(tid[t])
                    pend_r.append(rid)
            rid += 1
            if pend_t and (rid % FLUSH_ROWS == 0):
                t_chunks.append(np.array(pend_t, dtype=np.uint32))
                r_chunks.append(np.array(pend_r, dtype=np.uint32))
                pend_t, pend_r = [], []
        if pend_t:
            t_chunks.append(np.array(pend_t, dtype=np.uint32))
            r_chunks.append(np.array(pend_r, dtype=np.uint32))
        if rid != self.n_rows:
            raise SystemExit("training row count changed between passes")
        if not t_chunks:
            return (np.empty(0, dtype=np.uint32), np.empty(0, dtype=np.uint32))
        t = np.concatenate(t_chunks)
        r = np.concatenate(r_chunks)
        order = np.argsort(t, kind="stable")
        return t[order], r[order]

    def fetch(self, row_ids):
        """Read the given rows back; returns {row_id: (lowercased tokens, src)}."""
        want = sorted({int(x) for x in row_ids},
                      key=lambda x: (self.row_file[x], self.row_off[x]))
        out = {}
        for rid in want:
            fi = self.row_file[rid]
            fh = self._handles.get(fi)
            if fh is None:
                fh = open(self.paths[fi], "rb")
                self._handles[fi] = fh
            fh.seek(self.row_off[rid])
            row = json.loads(fh.readline().decode("utf-8"))
            out[rid] = ([t.lower() for t in row["tokenized_text"]], row["src"])
        return out

    def close(self):
        for fh in self._handles.values():
            fh.close()
        self._handles = {}


def shingle_candidates(h, r, doc_hashes):
    """Row ids of training rows sharing >= 1 shingle with the document."""
    if h.size == 0 or doc_hashes.size == 0:
        return np.empty(0, dtype=np.int64)
    lo = np.searchsorted(h, doc_hashes, side="left")
    hi = np.searchsorted(h, doc_hashes, side="right")
    counts = hi - lo
    total = int(counts.sum())
    if total == 0:
        return np.empty(0, dtype=np.int64)
    starts = np.repeat(lo, counts)
    offs = np.arange(total, dtype=np.int64) - np.repeat(np.cumsum(counts) - counts, counts)
    return np.unique(r[starts + offs])


def contains_subsequence(tokens, needle):
    k = len(needle)
    first = needle[0]
    n = len(tokens)
    for i in range(n - k + 1):
        if tokens[i] == first and tokens[i:i + k] == needle:
            return True
    return False


def main(argv):
    t0 = time.time()
    ap = argparse.ArgumentParser(description="benchmark <-> training corpus leak check")
    ap.add_argument("--gold", required=True)
    ap.add_argument("--names", required=True)
    ap.add_argument("--train", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    docs = load_gold(args.gold)
    names = load_name_set(args.names)

    # ---- injected values -------------------------------------------------
    values = []          # (doc_index, value_index, tokens, exempt)
    for di, doc in enumerate(docs):
        for vi, (start, end, vt) in enumerate(doc["values"]):
            if not vt:
                raise SystemExit("empty tokenization for a MUST_MASK value in %s" % doc["id"])
            exempt = len(vt) == 1 and vt[0] in names
            values.append((di, vi, vt, exempt))

    exempt_count = sum(1 for v in values if v[3])
    probed = [v for v in values if not v[3]]
    watched = {t for _, _, vt, _ in probed for t in vt}

    gold_hashes = np.unique(np.concatenate([d["shingles"] for d in docs if d["shingles"].size])
                            ) if any(d["shingles"].size for d in docs) else np.empty(0, dtype=np.uint64)

    # ---- pass 1 ----------------------------------------------------------
    train = TrainFile(args.train)
    h, r, df, tok_ok, tok_checked = train.scan(gold_hashes, watched, TOKENIZER_CHECK_ROWS)

    # ---- near-duplicates -------------------------------------------------
    reader_rows = 0
    per_doc = []
    for di, doc in enumerate(docs):
        rec = {"reasons": [], "j": 0.0, "rd": 0.0, "dr": 0.0, "val_hits": 0, "srcs": set()}
        per_doc.append(rec)
        cand = shingle_candidates(h, r, doc["shingles"])
        if cand.size == 0:
            continue
        rows = train.fetch(cand)
        reader_rows += len(rows)
        dsh = doc["shingles"]
        for rid in cand:
            toks, src = rows[rid]
            rsh = shingle_hashes(toks)
            if rsh.size == 0:
                continue
            inter = int(np.intersect1d(dsh, rsh, assume_unique=True).size)
            if inter == 0:
                continue
            j = inter / (dsh.size + rsh.size - inter)
            rd = inter / rsh.size
            dr = inter / dsh.size
            if j > rec["j"]:
                rec["j"] = j
            if rd > rec["rd"]:
                rec["rd"] = rd
            if dr > rec["dr"]:
                rec["dr"] = dr
            if max(j, rd, dr) >= THRESHOLD:
                rec["srcs"].add(src)
        for key, val in ((REASON_J, rec["j"]), (REASON_RD, rec["rd"]), (REASON_DR, rec["dr"])):
            if val >= THRESHOLD:
                rec["reasons"].append(key)

    # ---- injected values -------------------------------------------------
    if probed:
        tid = {t: i for i, t in enumerate(sorted(watched))}
        best = {}
        for di, vi, vt, _ in probed:
            best[(di, vi)] = min(set(vt), key=lambda t: (df.get(t, 0), t))
        probe_set = set(best.values())
        pt, pr = train.probe_postings(probe_set, tid)
        by_probe = {}
        for di, vi, vt, _ in probed:
            by_probe.setdefault(best[(di, vi)], []).append((di, vi, vt))
        for probe, items in by_probe.items():
            pid = tid[probe]
            lo = int(np.searchsorted(pt, pid, side="left"))
            hi = int(np.searchsorted(pt, pid, side="right"))
            cand = np.unique(pr[lo:hi])
            if cand.size == 0:
                continue
            if all(len(vt) == 1 for _, _, vt in items):
                rows = {int(rid): (None, train.row_src[int(rid)]) for rid in cand}
            else:
                rows = train.fetch(cand)
                reader_rows += len(rows)
            for di, vi, vt in items:
                hit_rows = []
                if len(vt) == 1:
                    tok = vt[0]
                    for rid, (_toks, src) in rows.items():
                        hit_rows.append((rid, src))
                else:
                    for rid, (toks, src) in rows.items():
                        if contains_subsequence(toks, vt):
                            hit_rows.append((rid, src))
                if hit_rows:
                    rec = per_doc[di]
                    rec["val_hits"] += 1
                    rec["reasons"].append(REASON_V)
                    for _rid, src in hit_rows:
                        rec["srcs"].add(src)

    # ---- outputs ---------------------------------------------------------
    os.makedirs(args.out, exist_ok=True)
    reasons_order = {k: i for i, k in enumerate(REASON_ORDER)}
    flagged_path = os.path.join(args.out, "flagged.jsonl")
    n_flagged = 0
    with open(flagged_path, "w", encoding="utf-8") as out:
        for di, doc in enumerate(docs):
            rec = per_doc[di]
            reasons = sorted(set(rec["reasons"]), key=lambda k: reasons_order[k])
            if not reasons:
                continue
            n_flagged += 1
            out.write(json.dumps({
                "id": doc["id"],
                "split": doc["split"],
                "reasons": reasons,
                "max_jaccard": round(rec["j"], 6),
                "max_contain_train_in_doc": round(rec["rd"], 6),
                "max_contain_doc_in_train": round(rec["dr"], 6),
                "value_hits": rec["val_hits"],
                "train_src": sorted(rec["srcs"]),
            }, sort_keys=True) + "\n")

    docs_checked = {}
    flagged_by = {}
    values_checked = {}
    value_hits = {}
    for di, doc in enumerate(docs):
        sp = doc["split"]
        docs_checked[sp] = docs_checked.get(sp, 0) + 1
        values_checked[sp] = values_checked.get(sp, 0) + len(doc["values"])
        rec = per_doc[di]
        value_hits[sp] = value_hits.get(sp, 0) + rec["val_hits"]
        if rec["reasons"]:
            slot = flagged_by.setdefault(sp, {"total": 0})
            slot["total"] += 1
            for reason in set(rec["reasons"]):
                slot[reason] = slot.get(reason, 0) + 1
    for sp in sorted(docs_checked):
        slot = flagged_by.setdefault(sp, {"total": 0})
        for reason in REASON_ORDER:
            slot.setdefault(reason, 0)

    summary = {
        "gold": args.gold,
        "train_files": list(args.train),
        "train_sha256": {p: sha256_file(p) for p in args.train},
        "train_rows": train.n_rows,
        "train_shingle_index_entries": int(h.size),
        "shingle_tokens": SHINGLE_N,
        "flag_threshold": THRESHOLD,
        "documents_checked": docs_checked,
        "documents_checked_total": sum(docs_checked.values()),
        "documents_flagged": flagged_by,
        "documents_flagged_total": n_flagged,
        "values_checked": values_checked,
        "values_checked_total": sum(values_checked.values()),
        "single_token_name_exemptions": exempt_count,
        "values_probed": len(probed),
        "value_hits": value_hits,
        "value_hits_total": sum(value_hits.values()),
        "tokenizer_check": {
            "rows_checked": tok_checked,
            "share_resplit_identical": round(tok_ok / tok_checked, 6) if tok_checked else None,
        },
        "rows_fetched": reader_rows,
        "elapsed_seconds": round(time.time() - t0, 3),
    }
    train.close()
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
