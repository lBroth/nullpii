# SPDX-License-Identifier: Apache-2.0
# Independent check of b1.jsonl against CredData meta + files. Prints counts only.
import collections
import csv
import glob
import json
import os
import sys

root, out = sys.argv[1], sys.argv[2]
CTX = 5
N = 2000

meta = {}
by_gt = collections.defaultdict(list)
for f in sorted(glob.glob(os.path.join(root, "meta", "*.csv"))):
    for r in csv.DictReader(open(f, encoding="utf-8")):
        meta[(r["Id"], r["FilePath"])] = r
        if r["GroundTruth"] in ("T", "F"):
            by_gt[r["GroundTruth"]].append(r)


def num(v):
    return int(v) if v not in ("", None) else -1


def lines_of(path):
    with open(os.path.join(root, path), "rb") as fh:
        return fh.read().decode().replace("\r\n", "\n").replace("\r", "\n").split("\n")


def value_and_doc(r):
    lines = lines_of(r["FilePath"])
    ls, le = int(r["LineStart"]), int(r["LineEnd"])
    vs, ve = num(r["ValueStart"]), num(r["ValueEnd"])
    seg = "\n".join(lines[ls - 1:le])
    off = len(seg) - len(lines[le - 1])
    if vs >= 0 and ve >= 0:
        val = seg[vs:ve + off]
    elif vs >= 0:
        val = seg[vs:]
    else:
        val = seg
    lo, hi = max(0, ls - 1 - CTX), min(len(lines), le + CTX)
    return val, "\n".join(lines[lo:hi])


rows = [json.loads(x) for x in open(os.path.join(out, "b1.jsonl"), encoding="utf-8")]
stats = collections.Counter()
cats = {"T": collections.Counter(), "F": collections.Counter()}
for row in rows:
    src = row["source"]
    r = meta[(str(src["meta_id"]), src["file"])]
    (item,) = row["items"]
    gt = "T" if item["class"] == "MUST_MASK" else "F"
    stats["class_ok"] += gt == r["GroundTruth"]
    stats["kind_ok"] += item["kind"] == r["Category"]
    cats[gt][r["Category"]] += 1
    val, doc = value_and_doc(r)
    stats["text_ok"] += row["text"] == doc
    stats["span_ok"] += row["text"][item["start"]:item["end"]] == val
    stats["span_in_doc"] += val in doc

# Largest-remainder allocation per class, recomputed here.
alloc_ok = {}
for gt in ("T", "F"):
    size = collections.Counter(r["Category"] for r in by_gt[gt])
    total = sum(size.values())
    quota = {c: N * n / total for c, n in size.items()}
    base = {c: int(q) for c, q in quota.items()}
    rest = N - sum(base.values())
    for c in sorted(quota, key=lambda c: (-(quota[c] - base[c]), c))[:rest]:
        base[c] += 1
    want = {c: n for c, n in base.items() if n}
    alloc_ok[gt] = {"match": want == dict(cats[gt]), "categories": len(want),
                    "diff_cats": sum(1 for c in set(want) | set(cats[gt]) if want.get(c, 0) != cats[gt].get(c, 0))}
print(json.dumps({"rows": len(rows), **stats, "alloc": alloc_ok}))
