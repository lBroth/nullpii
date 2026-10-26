#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build a fake training corpus in work/fixtures/ with known right answers.

Planted rows use the *dev* split of ../input/ab1.jsonl only:

  copy:<doc>      full doc tokens                    -> flagged, all three near-dup reasons
  slice:<doc>     first 20% of a long doc's tokens   -> flagged, contain_train_in_doc
  superset:<doc>  doc tokens + 2x noise tokens       -> flagged, contain_doc_in_train
  value:<doc>     noise + one injected value + noise -> flagged, value_hit
  name:<doc>      a bare first name (name-list token)-> exempt, nothing
  noise           unrelated synthetic rows           -> nothing

A candidate document is only accepted if the rows built from it touch no other
benchmark document (dev or test): no near-duplicate ratios >= 0.8 and no foreign
injected value inside the row.  The builder then brute-forces, independently of
leak_check.py, what the fixture implies for *every* document, and refuses to
write anything unless that is exactly the planted set.  So `expected.json` is
contamination-free and "nothing else" is a real assertion, not a hope.

Dev text is written to work/fixtures/; nothing here prints benchmark text or values.
"""

import hashlib
import json
import math
import os
import re
import sys

TOKEN_RE = re.compile(r"\w+(?:[-_]\w+)*|\S")
SHINGLE_N = 13
SEP = "\x1f"
THRESHOLD = 0.8
HERE = os.path.dirname(os.path.abspath(__file__))
GOLD = os.path.join(HERE, os.pardir, "input", "ab1.jsonl")
NAMES = os.path.join(HERE, os.pardir, "input", "names")
OUTDIR = os.path.join(HERE, "fixtures")


def tokenize(text):
    return [t.lower() for t in TOKEN_RE.findall(text)]


def shingles(tokens):
    if len(tokens) < SHINGLE_N:
        return set()
    return {hashlib.blake2b(SEP.join(tokens[i:i + SHINGLE_N]).encode("utf-8"),
                            digest_size=8).digest()
            for i in range(len(tokens) - SHINGLE_N + 1)}


def noise_tokens(start, n):
    """Deterministic synthetic tokens that appear nowhere in the benchmark."""
    out = []
    i = start
    while len(out) < n:
        out.append("zq" + hashlib.blake2b(str(i).encode(), digest_size=8).hexdigest())
        i += 1
    return out


def load_names():
    names = set()
    for lang in sorted(os.listdir(NAMES)):
        d = os.path.join(NAMES, lang)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.endswith(".txt"):
                with open(os.path.join(d, fn), encoding="utf-8") as fh:
                    for line in fh:
                        if line.strip():
                            names.add(line.strip().lower())
    return names


def main():
    docs = []
    with open(GOLD, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                row = json.loads(line)
                toks = tokenize(row["text"])
                docs.append({
                    "id": row["id"],
                    "split": row["split"],
                    "tokens": toks,
                    "sh": shingles(toks),
                    "values": [tuple(tokenize(row["text"][i["start"]:i["end"]]))
                               for i in row["items"] if i["class"] == "MUST_MASK"],
                })
    dev = [d for d in docs if d["split"] == "dev"]
    names = load_names()

    all_values = [v for d in docs for v in d["values"]]
    value_counts = {v: all_values.count(v) for v in set(all_values)}
    # (value, token set) for every non-exempt injected value, for contamination checks
    live_values = [(v, frozenset(v)) for d in docs for v in d["values"]
                   if not (len(v) == 1 and v[0] in names)]

    def touched(doc, row_tokens, row_sh):
        """Other documents that this training row would leak."""
        hits = set()
        rset = frozenset(row_tokens)
        for o in docs:
            if o["id"] == doc["id"]:
                continue
            if row_sh and o["sh"]:
                inter = len(o["sh"] & row_sh)
                if inter:
                    j = inter / len(o["sh"] | row_sh)
                    if max(j, inter / len(row_sh), inter / len(o["sh"])) >= THRESHOLD:
                        hits.add(o["id"])
                        continue
            for v in o["values"]:
                if len(v) == 1 and v[0] in names:
                    continue
                if len(v) > len(row_tokens) or not set(v) <= rset:
                    continue
                k = len(v)
                for i in range(len(row_tokens) - k + 1):
                    if tuple(row_tokens[i:i + k]) == v:
                        hits.add(o["id"])
                        break
        return hits

    used = set()
    rows_a, rows_b, designed = [], [], {}

    def plant(doc, reasons, src, value_hits=0):
        rec = designed.setdefault(doc["id"], {"reasons": set(), "value_hits": 0, "srcs": set()})
        rec["reasons"].update(reasons)
        rec["value_hits"] += value_hits
        if src is not None:
            rec["srcs"].add(src)
        return rec

    def pick(build, pred, n, why):
        """build(doc) -> [(row, target)]; accept only contamination-free candidates."""
        picked = []
        for d in dev:
            if d["id"] in used or not pred(d):
                continue
            built = build(d)
            if built is None:
                continue
            bad = False
            for row, _t in built:
                if touched(d, row["tokenized_text"], shingles(row["tokenized_text"])):
                    bad = True
                    break
            if bad:
                continue
            used.add(d["id"])
            picked.append((d, built))
            if len(picked) == n:
                return picked
        raise SystemExit("not enough clean dev docs for %s (got %d of %d)" % (why, len(picked), n))

    # 1. full copies -> all three reasons
    def build_copy(d):
        src = "fixture:copy:?"
        row = {"tokenized_text": list(d["tokens"]), "src": src}
        return [(row, "near_dup")]

    for n, (d, built) in enumerate(pick(build_copy,
                                        lambda d: len(d["tokens"]) >= 20, 5, "copy")):
        src = "fixture:copy:%d" % n
        rows_a.append({"tokenized_text": list(d["tokens"]), "src": src})
        plant(d, ["near_dup_jaccard", "near_dup_contain_train_in_doc",
                  "near_dup_contain_doc_in_train"], src)

    # 2. 20% slices -> containment of the training row in the document
    def build_slice(d):
        k = max(SHINGLE_N + 1, int(0.2 * len(d["tokens"])))
        return [({"tokenized_text": list(d["tokens"][:k]), "src": "?"}, "near_dup")]

    for n, (d, built) in enumerate(pick(build_slice,
                                        lambda d: len(d["tokens"]) >= 80, 5, "slice")):
        src = "fixture:slice:%d" % n
        rows_a.append({"tokenized_text": built[0][0]["tokenized_text"], "src": src})
        plant(d, ["near_dup_contain_train_in_doc"], src)

    # 3. supersets -> containment of the document in the training row
    def build_superset(d):
        toks = list(d["tokens"]) + noise_tokens(0, 2 * len(d["tokens"]))
        return [({"tokenized_text": toks, "src": "?"}, "near_dup")]

    for n, (d, built) in enumerate(pick(build_superset,
                                        lambda d: len(d["tokens"]) >= 30, 5, "superset")):
        src = "fixture:superset:%d" % n
        rows_a.append({"tokenized_text": built[0][0]["tokenized_text"], "src": src})
        plant(d, ["near_dup_contain_doc_in_train"], src)

    # 3b. the 0.8 threshold itself: keep the head of a document and pad with noise,
    #     so that containment of the row in the document (and vice versa) lands just
    #     above (flagged) or just below (not flagged) the threshold.  Jaccard stays
    #     around 0.65 in both cases.
    def build_boundary(d, above):
        n = len(d["tokens"])
        shared = math.ceil(0.8 * (n - SHINGLE_N))   # kept head -> shared shingles
        m = SHINGLE_N + shared - (0 if above else 1)
        toks = list(d["tokens"][:m]) + noise_tokens(20_000 + (0 if above else 500), n - m)
        return [({"tokenized_text": toks, "src": "?"}, "near_dup")]

    def build_above(d):
        return build_boundary(d, True)

    def build_below(d):
        return build_boundary(d, False)

    for n, (d, built) in enumerate(pick(build_above, lambda d: len(d["tokens"]) >= 40,
                                        2, "boundary-above")):
        src = "fixture:boundary-above:%d" % n
        rows_a.append({"tokenized_text": built[0][0]["tokenized_text"], "src": src})
        plant(d, ["near_dup_contain_train_in_doc", "near_dup_contain_doc_in_train"], src)

    for n, (d, built) in enumerate(pick(build_below, lambda d: len(d["tokens"]) >= 40,
                                        2, "boundary-below")):
        rows_a.append({"tokenized_text": built[0][0]["tokenized_text"],
                       "src": "fixture:boundary-below:%d" % n})
        plant(d, [], None)  # one shingle short of 0.8: must not be flagged

    # 4. an injected value inside unrelated tokens -> value_hit
    #    middle / row start / row end / middle, exercising contiguity boundaries
    edges = ((20, 20), (0, 20), (20, 0), (20, 20), (20, 20))

    def make_value_build(i, val):
        def build(d):
            pre, post = edges[i % len(edges)]
            toks = noise_tokens(50_000 + i * 100, pre) + list(val) + noise_tokens(60_000 + i * 100, post)
            return [({"tokenized_text": toks, "src": "?"}, "value")]
        return build

    def pick_valued(kind, n, why):
        picked = []
        i = 0
        for d in dev:
            if d["id"] in used:
                continue
            val = None
            for v in d["values"]:
                if value_counts[v] != 1:
                    continue
                if kind == "multi" and 2 <= len(v) <= 12:
                    val = v
                    break
                if kind == "single" and len(v) == 1 and v[0] not in names:
                    val = v
                    break
                if kind == "name" and len(v) == 1 and v[0] in names:
                    val = v
                    break
            if val is None:
                continue
            idx = len(picked)
            built = make_value_build(idx, val)(d)
            if touched(d, built[0][0]["tokenized_text"], shingles(built[0][0]["tokenized_text"])):
                continue
            used.add(d["id"])
            picked.append((d, val, built))
            i += 1
            if len(picked) == n:
                return picked
        raise SystemExit("not enough clean dev docs for %s (got %d of %d)" % (why, len(picked), n))

    for n, (d, val, built) in enumerate(pick_valued("multi", 3, "value-multi")):
        src = "fixture:value:%d" % n
        rows_b.append({"tokenized_text": built[0][0]["tokenized_text"], "src": src})
        plant(d, ["value_hit"], src, value_hits=1)

    for n, (d, val, built) in enumerate(pick_valued("single", 2, "value-single")):
        src = "fixture:value:%d" % (n + 3)
        rows_b.append({"tokenized_text": built[0][0]["tokenized_text"], "src": src})
        plant(d, ["value_hit"], src, value_hits=1)

    # 5. a bare first name -> exempt (counted separately, no flag)
    for n, (d, tok, _built) in enumerate(pick_valued("name", 3, "name")):
        rows_b.append({"tokenized_text": list(tok), "src": "fixture:name-lone:%d" % n})
        rows_b.append({"tokenized_text": noise_tokens(70_000 + n * 100, 10) + list(tok),
                       "src": "fixture:name-embedded:%d" % n})
        plant(d, [], None)  # nothing expected: the bare name is exempt

    # 6. unrelated rows -> nothing
    for n in range(10):
        rows_b.append({"tokenized_text": noise_tokens(90_000 + n * 100, 30 + 7 * n),
                       "src": "fixture:noise:%d" % n})

    # ---------------- independent brute force, every document --------------
    all_rows = [(r["tokenized_text"], r["src"]) for r in rows_a + rows_b]
    got = {}
    maxima = {}
    for d in docs:
        rec = {"reasons": set(), "value_hits": 0, "srcs": set()}
        got[d["id"]] = rec
        best = [0.0, 0.0, 0.0]
        for toks, src in all_rows:
            rsh = shingles(toks)
            if rsh and d["sh"]:
                inter = len(d["sh"] & rsh)
                if inter:
                    j = inter / len(d["sh"] | rsh)
                    rd = inter / len(rsh)
                    dr = inter / len(d["sh"])
                    best = [max(best[0], j), max(best[1], rd), max(best[2], dr)]
                    if max(j, rd, dr) >= THRESHOLD:
                        for reason, val in (("near_dup_jaccard", j),
                                            ("near_dup_contain_train_in_doc", rd),
                                            ("near_dup_contain_doc_in_train", dr)):
                            if val >= THRESHOLD:
                                rec["reasons"].add(reason)
                        rec["srcs"].add(src)
            for v in d["values"]:
                if len(v) == 1 and v[0] in names:
                    continue
                k = len(v)
                for i in range(len(toks) - k + 1):
                    if tuple(toks[i:i + k]) == v:
                        rec["value_hits"] += 1
                        rec["reasons"].add("value_hit")
                        rec["srcs"].add(src)
                        break
        maxima[d["id"]] = best

    # ---------------- design assertions ------------------------------------
    planted_flagged = set()
    for d in docs:
        want = designed.get(d["id"], {"reasons": set(), "value_hits": 0, "srcs": set()})
        g = got[d["id"]]
        if not want["reasons"] <= g["reasons"]:
            raise SystemExit("planted document %s: designed %s, got %s"
                             % (d["id"], sorted(want["reasons"]), sorted(g["reasons"])))
        if want["srcs"] and not want["srcs"] <= g["srcs"]:
            raise SystemExit("planted document %s: designed srcs %s, got %s"
                             % (d["id"], sorted(want["srcs"]), sorted(g["srcs"])))
        if g["value_hits"] < want["value_hits"]:
            raise SystemExit("planted document %s: designed %d value hits, got %d"
                             % (d["id"], want["value_hits"], g["value_hits"]))
        if want["reasons"]:
            planted_flagged.add(d["id"])
        elif g["reasons"] or g["value_hits"]:
            raise SystemExit("exempt plant %s unexpectedly flagged with %s / %d hits"
                             % (d["id"], sorted(g["reasons"]), g["value_hits"]))

    for d in docs:
        if d["id"] in planted_flagged or d["id"] in designed:
            continue
        if got[d["id"]]["reasons"]:
            raise SystemExit("unplanted document %s was touched: %s"
                             % (d["id"], sorted(got[d["id"]]["reasons"])))

    expected = {did: {"reasons": sorted(got[did]["reasons"]),
                      "value_hits": got[did]["value_hits"],
                      "train_src": sorted(got[did]["srcs"])}
                for did in planted_flagged}
    if set(expected) != planted_flagged:
        raise SystemExit("flagged set %s != planted set %s"
                         % (sorted(expected), sorted(planted_flagged)))

    os.makedirs(OUTDIR, exist_ok=True)
    for name, rows in (("train_a.jsonl", rows_a), ("train_b.jsonl", rows_b)):
        with open(os.path.join(OUTDIR, name), "w", encoding="utf-8") as fh:
            for r in rows:
                fh.write(json.dumps({"tokenized_text": r["tokenized_text"], "ner": [],
                                     "label_space": "ab1-fixture", "src": r["src"]}) + "\n")
    with open(os.path.join(OUTDIR, "expected.json"), "w", encoding="utf-8") as fh:
        json.dump({"rows_a": len(rows_a), "rows_b": len(rows_b),
                   "dev_docs": len(dev), "docs_total": len(docs),
                   "expect_flagged": expected,
                   "max_ratios": {k: [round(x, 6) for x in v] for k, v in maxima.items()}},
                  fh, indent=1, sort_keys=True)

    kinds = {}
    for rec in expected.values():
        for reason in rec["reasons"]:
            kinds[reason] = kinds.get(reason, 0) + 1
    print(json.dumps({
        "fixture_rows": len(rows_a) + len(rows_b),
        "planted_docs": len(used),
        "expect_flagged_docs": len(expected),
        "expect_flagged_by_reason": kinds,
        "expect_value_hits": sum(r["value_hits"] for r in expected.values()),
        "name_exempt_docs": 3,
        "no_contamination": True,
    }, sort_keys=True))


if __name__ == "__main__":
    sys.exit(main())
