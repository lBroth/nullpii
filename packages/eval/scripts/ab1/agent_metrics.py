# SPDX-License-Identifier: Apache-2.0
"""AB-1 scorer (AB-1 SPEC.md, "Metrics"). Label-agnostic: an item is
judged on the characters a tool masks, whatever label it gives them.

A MUST_MASK item is masked when every character carrying its value is
(whitespace and `\\n`-style layout escapes excepted, owner 24 Oct).

Reads the gold JSONL (component A's test split, or B1/B2) and every
`<tool>-<dataset>.jsonl` checkpoint (`score_capture.mjs` / `r2_run.py` rows
`{"idx", "spans": [[start, end, label, score], ...]}`, idx in gold order).
Each tool also gets an `+agent` row: its spans without the categories the
agent policy leaves readable.

  python agent_metrics.py --gold ab1.jsonl --split test --dataset ab1 \\
      --checkpoints DIR --baseline nullpii-H3b-cuda-agent --out ab1.json
"""
from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

import numpy as np

READABLE = frozenset({"private_date", "private_organization", "private_occupation", "private_title",
                      "private_demographic", "private_sensitive"})
AGENT_SUFFIX = "+agent"
RESAMPLES = 1000
SEED = 0
ALPHA = 0.025
PER_K = 1000
MASK = "{{{{MASK_{n}}}}}"
HUNK = re.compile(r"^@@ -\d+(?:,(\d+))? \+\d+(?:,(\d+))? @@")
# Line breaks written as escapes inside JSON or .env strings (a private key's
# `\n`): like whitespace, they carry none of the value (owner, 24 Oct).
LAYOUT_ESCAPE = re.compile(r"\\[nrt]")


def load_gold(path: Path, split: str | None) -> list[dict]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if split is None or r["split"] == split]


def load_spans(path: Path, n: int) -> list[list[tuple[int, int, str]]]:
    spans: list[list[tuple[int, int, str]]] = [[] for _ in range(n)]
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        idx = int(row["idx"])
        if not 0 <= idx < n:
            raise ValueError(f"{path.name}: idx {idx} outside the gold's {n} documents")
        seen.add(idx)
        spans[idx] = [(int(s[0]), int(s[1]), str(s[2]) if len(s) > 2 else "") for s in row["spans"]]
    if len(seen) != n:
        raise ValueError(f"{path.name}: {len(seen)} documents for {n} in the gold")
    return spans


def masked_set(spans: list[tuple[int, int, str]], length: int) -> np.ndarray:
    m = np.zeros(length, dtype=bool)
    for s, e, _ in spans:
        m[max(0, s):min(length, e)] = True
    return m


def value_chars(text: str) -> np.ndarray:
    """Characters that carry a MUST_MASK value: all but whitespace and
    layout escapes. A value is masked when all of these are (a tool that
    masks a key line by line, leaving the line breaks, has masked it)."""
    sig = np.fromiter((not c.isspace() for c in text), dtype=bool, count=len(text))
    for m in LAYOUT_ESCAPE.finditer(text):
        sig[m.start():m.end()] = False
    return sig


def masked_text(text: str, spans: list[tuple[int, int, str]]) -> str:
    merged: list[list[int]] = []
    for s, e, _ in sorted(spans):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    out, at = [], 0
    for n, (s, e) in enumerate(merged):
        out.append(text[at:s])
        out.append(MASK.format(n=n))
        at = e
    out.append(text[at:])
    return "".join(out)


def is_json(text: str) -> bool:
    try:
        json.loads(text)
    except ValueError:
        return False
    return True


def hunks_consistent(text: str) -> bool:
    """Every hunk's declared old/new line counts match its body."""
    lines = text.split("\n")
    i = 0
    found = False
    while i < len(lines):
        m = HUNK.match(lines[i])
        if not m:
            i += 1
            continue
        found = True
        old = int(m.group(1)) if m.group(1) is not None else 1
        new = int(m.group(2)) if m.group(2) is not None else 1
        i += 1
        while i < len(lines) and (old > 0 or new > 0):
            line = lines[i]
            if line.startswith("\\"):
                i += 1
                continue
            tag = line[:1]
            if tag == " " or line == "":
                old, new = old - 1, new - 1
            elif tag == "-":
                old -= 1
            elif tag == "+":
                new -= 1
            else:
                return False
            i += 1
        if old != 0 or new != 0:
            return False
    return found


def is_diff(text: str) -> bool:
    return any(HUNK.match(line) for line in text.split("\n"))


def doc_record(doc: dict, spans: list[tuple[int, int, str]]) -> dict:
    """Per-document counts the metrics and the bootstrap are built from."""
    text = doc["text"]
    m = masked_set(spans, len(text))
    sig = value_chars(text)
    covered = np.zeros(len(text), dtype=bool)
    rec: dict = {"mask": collections.Counter(), "mask_n": collections.Counter(), "keep": collections.Counter(),
                 "keep_n": collections.Counter(), "enc": [0, 0], "has_mask_item": False, "leaked_doc": False}
    for item in doc["items"]:
        s, e = item["start"], item["end"]
        covered[s:e] = True
        hit = bool(m[s:e].any())
        need = sig[s:e] if sig[s:e].any() else np.ones(e - s, dtype=bool)
        full = bool(m[s:e][need].all())
        if item["class"] == "MUST_MASK":
            rec["has_mask_item"] = True
            cat = item["category"]
            rec["mask_n"][cat] += 1
            if not full:
                rec["mask"][cat] += 1
                rec["leaked_doc"] = True
            if item.get("encoded_of") is not None:
                rec["enc"][1] += 1
                rec["enc"][0] += 0 if full else 1
        elif item["class"] == "MUST_KEEP":
            kind = item["kind"]
            rec["keep_n"][kind] += 1
            rec["keep"][kind] += 0 if hit else 1
    rec["chars"] = len(text)
    rec["outside"] = int((m & ~covered).sum())
    rec["any_mask"] = bool(m.any())
    if is_json(text):
        rec["json"] = is_json(masked_text(text, spans))
    if is_diff(text) and hunks_consistent(text):
        rec["diff"] = hunks_consistent(masked_text(text, spans))
    return rec


def summarize(recs: list[dict]) -> dict:
    mask, mask_n, keep, keep_n = (collections.Counter() for _ in range(4))
    for r in recs:
        mask.update(r["mask"])
        mask_n.update(r["mask_n"])
        keep.update(r["keep"])
        keep_n.update(r["keep_n"])
    with_items = [r for r in recs if r["has_mask_item"]]
    clean = [r for r in recs if not r["has_mask_item"]]
    enc = [sum(r["enc"][0] for r in recs), sum(r["enc"][1] for r in recs)]
    chars = sum(r["chars"] for r in recs)
    jsons = [r["json"] for r in recs if "json" in r]
    diffs = [r["diff"] for r in recs if "diff" in r]
    out = {
        "leak_rate": sum(mask.values()) / max(1, sum(mask_n.values())),
        "keep_rate": sum(keep.values()) / max(1, sum(keep_n.values())),
        "leak_by_category": {c: [mask[c] / mask_n[c], mask_n[c]] for c in sorted(mask_n)},
        "keep_by_kind": {k: [keep[k] / keep_n[k], keep_n[k]] for k in sorted(keep_n)},
        "docs_with_leak": sum(r["leaked_doc"] for r in with_items) / max(1, len(with_items)),
        "clean_docs_masked": sum(r["any_mask"] for r in clean) / len(clean) if clean else None,
        "outside_per_1k": PER_K * sum(r["outside"] for r in recs) / max(1, chars),
        "encoded_leak_rate": enc[0] / enc[1] if enc[1] else None,
        "json_parse_rate": sum(jsons) / len(jsons) if jsons else None,
        "diff_consistent_rate": sum(diffs) / len(diffs) if diffs else None,
        "items": {"must_mask": sum(mask_n.values()), "must_keep": sum(keep_n.values())},
        "docs": len(recs),
    }
    return out


def bootstrap(per_tool: dict[str, list[dict]], baseline: str | None) -> dict:
    """Paired bootstrap over documents: 95% intervals of leak and keep rate
    per tool, and of baseline minus tool (ratio of resampled sums)."""
    n = len(next(iter(per_tool.values())))
    idx = np.random.default_rng(SEED).integers(0, n, size=(RESAMPLES, n))

    def rates(recs: list[dict]) -> tuple[np.ndarray, np.ndarray]:
        cols = [np.array([sum(r[k].values()) for r in recs], dtype=float) for k in ("mask", "mask_n", "keep", "keep_n")]
        leak, mask_n, keep, keep_n = (c[idx].sum(axis=1) for c in cols)
        return leak / np.maximum(mask_n, 1), keep / np.maximum(keep_n, 1)

    rates_by_tool = {t: rates(r) for t, r in per_tool.items()}
    out: dict[str, dict[str, list[float]]] = {}
    for tool, (leak, keep) in rates_by_tool.items():
        ci = {"leak": leak, "keep": keep}
        if baseline in rates_by_tool and tool != baseline:
            base_leak, base_keep = rates_by_tool[baseline]
            ci["baseline_minus_tool_leak"] = base_leak - leak
            ci["baseline_minus_tool_keep"] = base_keep - keep
        out[tool] = {k: [float(np.quantile(v, ALPHA)), float(np.quantile(v, 1 - ALPHA))] for k, v in ci.items()}
    return out


def tools_in(checkpoints: Path, dataset: str) -> dict[str, Path]:
    suffix = f"-{dataset}.jsonl"
    return {p.name[: -len(suffix)]: p for p in sorted(checkpoints.glob(f"*{suffix}"))}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--split", default=None)
    ap.add_argument("--dataset", required=True, help="checkpoint dataset key")
    ap.add_argument("--checkpoints", type=Path, required=True)
    ap.add_argument("--baseline", default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    gold = load_gold(args.gold, args.split)
    per_tool: dict[str, list[dict]] = {}
    for tool, path in tools_in(args.checkpoints, args.dataset).items():
        spans = load_spans(path, len(gold))
        per_tool[tool] = [doc_record(d, s) for d, s in zip(gold, spans)]
        agent = [[sp for sp in s if sp[2] not in READABLE] for s in spans]
        per_tool[tool + AGENT_SUFFIX] = [doc_record(d, s) for d, s in zip(gold, agent)]
    if not per_tool:
        raise SystemExit(f"no checkpoint for {args.dataset} in {args.checkpoints}")
    report = {t: summarize(r) for t, r in per_tool.items()}
    for t, ci in bootstrap(per_tool, args.baseline).items():
        report[t]["ci"] = ci
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    for t in sorted(report, key=lambda t: (report[t]["leak_rate"], -report[t]["keep_rate"])):
        r = report[t]
        print(f"{t:44s} leak {r['leak_rate']:.4f}  keep {r['keep_rate']:.4f}  outside/1k {r['outside_per_1k']:.2f}")


if __name__ == "__main__":
    main()
