# SPDX-License-Identifier: Apache-2.0
"""Apply the T3 acceptance rule (METHOD.md, rule 3) to a candidate, from the
outputs the protocol already produces, and print a verdict block.

  python verdict.py --metrics char-tuning-X.json --baseline nullpii-T4d \\
      --candidate nullpii-X-core --fp-base fp-T4d.json --fp-cand fp-X-core.json \\
      --dev-texts dev-texts.jsonl

Checks:
- macro char-F2 improves, with the CI of the difference entirely above 0;
- no gold label's char-recall drops by more than 0.005 on any dataset, or
  significantly (the paired-bootstrap CI of baseline minus candidate lies
  entirely above 0);
- U1: pooled masked-character share on the four developer corpora
  rises by at most 0.5 percentage points.

Also reported, not gating: per-dataset F2 with CIs, the traces precision
change, and the largest per-label gains. Prints numbers only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

RECALL_DROP_GUARD = 0.005
U1_CAP_PP = 0.5
DEV_KINDS = ("code", "python", "markdown", "json")
TRACES = "claude-code-traces-tuning"


def u1(fingerprint: Path, lengths: dict[str, int]) -> float:
    total = masked = 0
    for doc in json.loads(fingerprint.read_text(encoding="utf-8"))["docs"]:
        if doc["id"] not in lengths:
            continue
        covered: set[int] = set()
        for _, start, end in doc["spans"]:
            covered.update(range(start, end))
        total += lengths[doc["id"]]
        masked += len(covered)
    return 100 * masked / total


def dev_lengths(path: Path) -> dict[str, int]:
    lengths = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            kind = row["dataset"].removeprefix("dev-")
            if kind in DEV_KINDS:
                lengths[f"shaped:{kind}"] = len(row["text"])
    return lengths


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metrics", required=True, type=Path)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--candidate", required=True)
    ap.add_argument("--fp-base", type=Path)
    ap.add_argument("--fp-cand", type=Path)
    ap.add_argument("--dev-texts", type=Path)
    args = ap.parse_args()
    data = json.loads(args.metrics.read_text(encoding="utf-8"))
    base, cand = args.baseline, args.candidate
    failures: list[str] = []

    macro = data["_macro"][cand]
    ci = macro["baseline_minus_tool_f2_ci"]
    gain = [-ci[1], -ci[0]]
    print(f"macro char-F2 {data['_macro'][base]['f2']:.4f} -> {macro['f2']:.4f}, CI of the gain [{gain[0]:+.4f}, {gain[1]:+.4f}]")
    if gain[0] <= 0:
        failures.append("macro gain CI not entirely above 0")

    drops: list[tuple[float, str, str]] = []
    gains: list[tuple[float, str, str]] = []
    for ds, row in data.items():
        if ds.startswith("_"):
            continue
        b, c = row[base], row[cand]
        d_ci = c.get("baseline_minus_tool_f2_ci", [0, 0])
        print(f"  {ds:28s} F2 {b['f2']:.4f} -> {c['f2']:.4f}  CI [{-d_ci[1]:+.4f}, {-d_ci[0]:+.4f}]  R {b['recall']:.3f}->{c['recall']:.3f}  P {b['precision']:.3f}->{c['precision']:.3f}")
        for label, entry in b["per_label_recall"].items():
            cand_label = c["per_label_recall"].get(label)
            if cand_label is None or "baseline_minus_tool_recall_ci" not in cand_label:
                raise SystemExit(
                    f"{ds}/{label}: no per-label recall CI for the candidate; regenerate the metrics with char_metrics.py"
                )
            delta = cand_label["recall"] - entry["recall"]
            significant = cand_label["baseline_minus_tool_recall_ci"][0] > 0
            if delta < -RECALL_DROP_GUARD or significant:
                drops.append((delta, ds, label + (" (significant)" if significant else "")))
            elif delta > RECALL_DROP_GUARD:
                gains.append((delta, ds, label))
    if drops:
        failures.append(f"{len(drops)} per-label recall drops beyond {RECALL_DROP_GUARD} or significant")
        print(f"per-label recall drops (gating: beyond {RECALL_DROP_GUARD}, or significant):")
        for delta, ds, label in sorted(drops):
            print(f"  {label:24s} {ds:28s} {delta:+.3f}")
    print("largest per-label gains:")
    for delta, ds, label in sorted(gains, reverse=True)[:8]:
        print(f"  {label:24s} {ds:28s} {delta:+.3f}")

    if TRACES in data:
        b, c = data[TRACES][base], data[TRACES][cand]
        p_ci = c.get("baseline_minus_tool_precision_ci", [0, 0])
        print(f"traces precision {b['precision']:.3f} -> {c['precision']:.3f}, CI of the change [{-p_ci[1]:+.3f}, {-p_ci[0]:+.3f}] (reported, not gating)")

    if args.fp_base and args.fp_cand and args.dev_texts:
        lengths = dev_lengths(args.dev_texts)
        before, after = u1(args.fp_base, lengths), u1(args.fp_cand, lengths)
        print(f"U1 {before:.3f}% -> {after:.3f}% ({after - before:+.3f} pp, cap +{U1_CAP_PP})")
        if after - before > U1_CAP_PP:
            failures.append("U1 over the cap")
    else:
        failures.append("U1 not measured (needs --fp-base, --fp-cand and --dev-texts)")

    print("VERDICT:", "ACCEPT" if not failures else "REJECT (" + "; ".join(failures) + ")")


if __name__ == "__main__":
    main()
