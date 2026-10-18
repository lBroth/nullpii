# SPDX-License-Identifier: Apache-2.0
"""Where a model's masked characters fall on TAB's dev split.

TAB (Pilán et al., 2022, CC BY 4.0) annotates every identifier in ECHR
judgments. The bench's `tab-echr` loader keeps only PERSON, DATETIME and
LOC as gold, so masking a CODE, ORG, DEM, MISC or QUANTITY mention counts
as a false positive there. This splits a model's masked characters into
mapped gold, the TAB types the bench skips, and text outside any TAB
mention. The dev split is not part of the report set (which uses the test
split), and documents sharing a 200-character prefix with a test document
are left out.

  python tab_dev.py prep echr_dev.json tab-echr-test.jsonl texts.jsonl gold.jsonl
  python tab_dev.py fp gold.jsonl texts.jsonl spans-a.jsonl [spans-b.jsonl ...]

`echr_dev.json` comes from github.com/NorskRegnesentral/text-anonymization-benchmark.
`spans-*.jsonl` are `score_capture.mjs --out` files. Prints counts only.
"""
import collections
import json
import sys

MAPPED = {"PERSON", "DATETIME", "LOC"}
PREFIX_CHARS = 200


def prep(src: str, test_path: str, texts_out: str, gold_out: str) -> None:
    docs = json.load(open(src, encoding="utf-8"))
    test_prefixes = {json.loads(line)["text"][:PREFIX_CHARS] for line in open(test_path, encoding="utf-8") if line.strip()}
    kept = 0
    with open(texts_out, "w", encoding="utf-8") as ft, open(gold_out, "w", encoding="utf-8") as fg:
        for i, d in enumerate(docs):
            if d["text"][:PREFIX_CHARS] in test_prefixes:
                continue
            annotator = next(iter(d["annotations"].values()))
            mentions = [(m["entity_type"], m["start_offset"], m["end_offset"]) for m in annotator["entity_mentions"]]
            ft.write(json.dumps({"dataset": "tab-echr-dev", "idx": i, "text": d["text"]}) + "\n")
            fg.write(json.dumps({"idx": i, "mentions": mentions}) + "\n")
            kept += 1
    print(f"kept {kept} of {len(docs)} dev documents")


def char_types(mentions: list, n: int) -> list:
    types = [None] * n
    for t, a, b in mentions:
        for k in range(max(a, 0), min(b, n)):
            if types[k] is None or t in MAPPED:
                types[k] = t
    return types


def fp(gold_path: str, texts_path: str, preds: list[str]) -> None:
    gold = {json.loads(line)["idx"]: json.loads(line)["mentions"] for line in open(gold_path, encoding="utf-8")}
    lens = {json.loads(line)["idx"]: len(json.loads(line)["text"]) for line in open(texts_path, encoding="utf-8")}
    for path in preds:
        mapped_total = hit = masked = 0
        misses = collections.Counter()
        for line in open(path, encoding="utf-8"):
            row = json.loads(line)
            n = lens[row["idx"]]
            types = char_types(gold[row["idx"]], n)
            pred = bytearray(n)
            for s in row["spans"]:
                pred[s[0]:s[1]] = b"\1" * (s[1] - s[0])
            for k in range(n):
                in_mapped = types[k] in MAPPED
                mapped_total += in_mapped
                if not pred[k]:
                    continue
                masked += 1
                if in_mapped:
                    hit += 1
                else:
                    misses[types[k] or "none"] += 1
        fp_total = sum(misses.values())
        in_tab = fp_total - misses["none"]
        print(f"{path}: recall(mapped) {hit / mapped_total:.3f}  precision(mapped) {hit / masked:.3f}  "
              f"precision(any TAB type) {(hit + in_tab) / masked:.3f}  FP chars {fp_total}")
        for t, c in misses.most_common():
            print(f"    FP in {t:9s} {c:7d}  ({c / fp_total:.1%})")


def main() -> None:
    if sys.argv[1] == "prep":
        prep(*sys.argv[2:6])
    else:
        fp(sys.argv[2], sys.argv[3], sys.argv[4:])


if __name__ == "__main__":
    main()
