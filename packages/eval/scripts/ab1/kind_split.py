# SPDX-License-Identifier: Apache-2.0
"""AB-1 (SPEC.md, "Metrics"): the secrets' leak rate split by one gold
kind and the rest, per tool. B1 inherits CredData's categories as kinds,
and CredData counts UUIDs as credentials, which AB-1's specification lists
as text to keep: `--kind UUID` on B1 gives nullpii's leaks on those items
and on every other secret apart. Computed after the scores were read, and
only reported.

An item is masked by the scorer's own rule (`secret_coverage.masked`,
`agent_metrics.doc_record`'s rule for one MUST_MASK item). Counts and
rates only; no text, value or document is written or printed.

  python kind_split.py --gold b1.jsonl --dataset ab1-b1 --kind UUID \\
      --checkpoints DIR --out kind-split-ab1-b1.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_metrics import AGENT_SUFFIX, READABLE, load_gold, load_spans, tools_in  # noqa: E402
from secret_coverage import SECRET, masked  # noqa: E402


def secret_items(doc: dict) -> list[tuple[int, int, str]]:
    return [(i["start"], i["end"], i["kind"]) for i in doc["items"]
            if i["class"] == "MUST_MASK" and i["category"] == SECRET]


def leaks(gold: list[dict], spans: list[list[tuple[int, int, str]]], kind: str) -> tuple[int, int]:
    """How many secrets of `kind`, and of every other kind, are left
    unmasked."""
    of_kind = other = 0
    for doc, rows in zip(gold, spans):
        for s, e, k in secret_items(doc):
            if not masked(doc, rows, (s, e)):
                if k == kind:
                    of_kind += 1
                else:
                    other += 1
    return of_kind, other


def split(gold: list[dict], per_tool: dict[str, list[list[tuple[int, int, str]]]], kind: str) -> dict:
    items = [k for d in gold for _, _, k in secret_items(d)]
    n_kind = sum(1 for k in items if k == kind)
    n_other = len(items) - n_kind
    if not n_kind or not n_other:
        raise SystemExit(f"{kind}: {n_kind} secrets of the kind and {n_other} others; nothing to split")
    tools = {}
    for name, spans in per_tool.items():
        of_kind, other = leaks(gold, spans, kind)
        tools[name] = {"leaked": of_kind, "leaked_other": other, "leak": of_kind / n_kind, "leak_other": other / n_other}
    return {"kind": kind, "items": n_kind, "other_items": n_other, "tools": tools}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--split", default=None)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--kind", required=True, help="the gold kind to split off, such as UUID")
    ap.add_argument("--checkpoints", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    gold = load_gold(args.gold, args.split)
    per_tool = {}
    for tool, path in tools_in(args.checkpoints, args.dataset).items():
        spans = load_spans(path, len(gold))
        per_tool[tool] = spans
        per_tool[tool + AGENT_SUFFIX] = [[s for s in r if s[2] not in READABLE] for r in spans]
    if not per_tool:
        raise SystemExit(f"no checkpoint for {args.dataset} in {args.checkpoints}")
    report = split(gold, per_tool, args.kind)
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("kind", "items", "other_items")}))


if __name__ == "__main__":
    main()
