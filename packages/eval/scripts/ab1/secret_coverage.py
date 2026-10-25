# SPDX-License-Identifier: Apache-2.0
"""AB-1 (SPEC.md, "Metrics"): the secrets' leak rate, split by whether
nullpii's recognizer pack covers the item's format. Computed after the
freeze and only reported.

An item is covered when the pack, run alone on the document's raw text
(`recognizer_spans.mjs`), masks every character carrying its value, by the
scorer's own rule (`agent_metrics.value_chars`). Each tool's leak rate is
then given on covered and uncovered secrets apart. Aggregates only.

  python secret_coverage.py --gold G.jsonl --recognizers R.jsonl \\
      --dataset ab1-b1 --checkpoints DIR --out coverage-ab1-b1.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_metrics import AGENT_SUFFIX, READABLE, load_gold, load_spans, masked_set, tools_in, value_chars  # noqa: E402

SECRET = "secret"


def secret_items(doc: dict) -> list[tuple[int, int]]:
    return [(i["start"], i["end"]) for i in doc["items"] if i["class"] == "MUST_MASK" and i["category"] == SECRET]


def masked(doc: dict, spans: list[tuple[int, int, str]], item: tuple[int, int]) -> bool:
    """`agent_metrics.doc_record`'s rule for one MUST_MASK item."""
    s, e = item
    m = masked_set(spans, len(doc["text"]))[s:e]
    sig = value_chars(doc["text"])[s:e]
    return bool(m[sig].all()) if sig.any() else bool(m.all())


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--gold", type=Path, required=True)
    ap.add_argument("--split", default=None)
    ap.add_argument("--recognizers", type=Path, required=True)
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--checkpoints", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    gold = load_gold(args.gold, args.split)
    reco = load_spans(args.recognizers, len(gold))
    covered = [[masked(d, r, it) for it in secret_items(d)] for d, r in zip(gold, reco)]
    n_cov = sum(sum(c) for c in covered)
    n_all = sum(len(c) for c in covered)
    report: dict = {"secrets": n_all, "covered": n_cov, "uncovered": n_all - n_cov, "tools": {}}
    for tool, path in tools_in(args.checkpoints, args.dataset).items():
        spans = load_spans(path, len(gold))
        for name, rows in ((tool, spans), (tool + AGENT_SUFFIX, [[s for s in r if s[2] not in READABLE] for r in spans])):
            leak = {True: 0, False: 0}
            for d, r, cov in zip(gold, rows, covered):
                for it, c in zip(secret_items(d), cov):
                    leak[c] += 0 if masked(d, r, it) else 1
            report["tools"][name] = {
                "leak_covered": leak[True] / n_cov if n_cov else None,
                "leak_uncovered": leak[False] / (n_all - n_cov) if n_all - n_cov else None,
            }
    args.out.write_text(json.dumps(report, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("secrets", "covered", "uncovered")}))


if __name__ == "__main__":
    main()
