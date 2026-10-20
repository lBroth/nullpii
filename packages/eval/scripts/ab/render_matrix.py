# SPDX-License-Identifier: Apache-2.0
"""Render a `char_metrics.py` JSON as the Markdown tables the README and
the release notes publish, so no number is ever copied by hand.

  python render_matrix.py char-report.json --baseline nullpii-T4d [--name nullpii] [--exclude nullpii-T3]

Prints two tables:
- char-F2 per dataset and tool, tools ordered by macro F2, best in bold;
- per tool: macro F2, recall and precision, and the paired-bootstrap CI
  of the baseline minus the tool, from the JSON.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Datasets that overlap a tool's training data, so its cell is a best case.
# Kept here, next to the table, so the flag cannot drift from the numbers.
IN_DISTRIBUTION: dict[str, set[str]] = {
    "rizzo-pii": {"isotonic-it-report"},
    # Trained on ai4privacy/pii-masking-200k, which holds the text of the
    # Isotonic sets and of argilla-pii verbatim (found 2026-10-18).
    "openmed-pf-multi-v2": {"isotonic-en-report", "isotonic-de-report", "isotonic-fr-report", "isotonic-it-report", "argilla-pii"},
}


def macro(per_dataset: dict, tool: str, key: str) -> float:
    vals = [v[tool][key] for v in per_dataset.values() if tool in v]
    return sum(vals) / len(vals)


def cell(value: float, best: bool, flagged: bool) -> str:
    text = f"{value:.3f}"
    if best:
        text = f"**{text}**"
    return f"{text} ‡" if flagged else text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("metrics", type=Path)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--name", help="display name for the baseline column")
    ap.add_argument("--exclude", default="", help="comma list of tools to leave out, such as earlier nullpii versions")
    args = ap.parse_args()
    excluded = {t for t in args.exclude.split(",") if t}
    if args.baseline in excluded:
        raise SystemExit("the baseline cannot be excluded")
    data = json.loads(args.metrics.read_text(encoding="utf-8"))
    per_dataset = {k: v for k, v in data.items() if not k.startswith("_")}
    present = {t for v in per_dataset.values() for t in v}
    if excluded - present:
        raise SystemExit(f"not in the metrics: {sorted(excluded - present)}")
    tools = sorted(present - excluded, key=lambda t: -macro(per_dataset, t, "f2"))
    label = {t: (args.name if t == args.baseline and args.name else t) for t in tools}

    print("| Dataset | " + " | ".join(f"`{label[t]}`" for t in tools) + " |")
    print("|---|" + "---:|" * len(tools))
    for ds, row in per_dataset.items():
        best = max(row[t]["f2"] for t in tools if t in row)
        cells = [cell(row[t]["f2"], row[t]["f2"] == best, ds in IN_DISTRIBUTION.get(t, set())) if t in row else "–" for t in tools]
        print(f"| `{ds}` | " + " | ".join(cells) + " |")
    macros = [macro(per_dataset, t, "f2") for t in tools]
    print("| **macro** | " + " | ".join(cell(m, m == max(macros), False) for m in macros) + " |")

    print()
    print(f"| Tool | Macro char-F2 | Recall | Precision | CI of {label[args.baseline]} − tool |")
    print("|---|---:|---:|---:|---|")
    ci = data.get("_macro", {})
    for t in tools:
        interval = ci.get(t, {}).get("baseline_minus_tool_f2_ci")
        shown = "—" if interval is None else f"[{interval[0]:+.3f}, {interval[1]:+.3f}]"
        print(f"| `{label[t]}` | {macro(per_dataset, t, 'f2'):.3f} | {macro(per_dataset, t, 'recall'):.3f} | {macro(per_dataset, t, 'precision'):.3f} | {shown} |")


if __name__ == "__main__":
    main()
