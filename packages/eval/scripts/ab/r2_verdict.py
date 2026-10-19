# SPDX-License-Identifier: Apache-2.0
"""S1 and S2 on the gated report set R2 (PROTOCOL rule change 9), from one
`char_metrics.py --mask-all` report whose baseline is nullpii's core regime.
Written before R2 is scored, so the analysis cannot follow the numbers.

- S1: nullpii's macro char-F2 is above every competitor at the competitor's
  tuned operating point, with the CI of the difference entirely above 0.
- S2: no R2 dataset where a competitor's char-recall is significantly
  higher (CI of nullpii minus tool entirely below 0) while its precision is
  not significantly lower (that CI not entirely above 0).
- Reported, not gating: every cell where F1 or F0.5 orders a competitor and
  nullpii the other way round from F2; the mask-all floor; each tool's
  default operating point (`<tool>@default`); nullpii's default config; the
  leave-one-dataset-out range of each macro.

Rule change 10 (R3) with `--better-row`: S1 is tested against each
competitor's better row, the tuned or the `@default` one with the higher
macro char-F2; S2 and the F1 / F0.5 reversals are tested against both rows.
`--table-only` prints the table of a reported, non-gated report.

  python r2_verdict.py --report char-r2.json --baseline nullpii-core \\
      --not-competitors nullpii-default
  python r2_verdict.py --report char-r3-gated.json --baseline nullpii-core \\
      --not-competitors nullpii-default,nullpii-default@core --better-row
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

MASK_ALL = "mask-all"
DEFAULT_SUFFIX = "@default"
VARIANTS = ("f1", "f05")


def competitors(tools: list[str], baseline: str, excluded: set[str]) -> list[str]:
    """Tuned competitors: every tool except nullpii's rows, the floor and the
    `@default` rows, which are reported but not tested."""
    return [t for t in tools if t != baseline and t != MASK_ALL and t not in excluded and not t.endswith(DEFAULT_SUFFIX)]


def better_rows(macro: dict, rivals: list[str]) -> list[str]:
    """Each competitor's row with the higher macro char-F2: tuned, or its
    `@default` row (rule change 10). A tie keeps the tuned row."""
    out = []
    for t in rivals:
        default = t + DEFAULT_SUFFIX
        out.append(default if default in macro and macro[default]["f2"] > macro[t]["f2"] else t)
    return out


def both_rows(rivals: list[str], tools: list[str]) -> list[str]:
    """Each competitor's tuned row and, where it was run, its `@default` row."""
    return [r for t in rivals for r in (t, t + DEFAULT_SUFFIX) if r in tools]


def s1(macro: dict, rivals: list[str]) -> tuple[bool, list[str]]:
    lines, ok = [], True
    for t in rivals:
        ci = macro[t]["baseline_minus_tool_f2_ci"]
        held = ci[0] > 0
        ok &= held
        lines.append(f"  {t}: macro F2 {macro[t]['f2']:.4f}, CI of nullpii - tool [{ci[0]:+.4f}, {ci[1]:+.4f}] {'' if held else 'FAILS'}")
    return ok, lines


def s2(report: dict, datasets: list[str], rivals: list[str]) -> tuple[bool, list[str]]:
    breaches = []
    for ds in datasets:
        for t in rivals:
            e = report[ds][t]
            recall_ci, precision_ci = e["baseline_minus_tool_recall_ci"], e["baseline_minus_tool_precision_ci"]
            if recall_ci[1] < 0 and precision_ci[0] <= 0:
                breaches.append(f"  {ds}/{t}: recall CI of nullpii - tool {recall_ci}, precision CI {precision_ci}")
    return not breaches, breaches


def reversals(report: dict, scopes: list[str], rivals: list[str]) -> list[str]:
    """Cells where F1 or F0.5 orders nullpii and a competitor unlike F2."""
    out = []
    for scope in scopes:
        for t in rivals:
            e = report[scope][t]
            f2_sign = e["baseline_minus_tool_f2_ci"][0] > 0, e["baseline_minus_tool_f2_ci"][1] < 0
            for key in VARIANTS:
                ci = e[f"baseline_minus_tool_{key}_ci"]
                sign = ci[0] > 0, ci[1] < 0
                if sign != f2_sign and (any(sign) or any(f2_sign)):
                    out.append(f"  {scope}/{t}: F2 CI {e['baseline_minus_tool_f2_ci']}, {key} CI {ci}")
    return out


def table(report: dict, datasets: list[str], tools: list[str]) -> list[str]:
    head = "| Tool | " + " | ".join(datasets) + " | Macro F2 | LODO | Macro F1 | Macro F0.5 |"
    lines = [head, "|---|" + "---:|" * (len(datasets) + 4)]
    macro = report["_macro"]
    for t in sorted(tools, key=lambda x: -macro[x]["f2"]):
        cells = " | ".join(f"{report[ds][t]['f2']:.4f}" for ds in datasets)
        lodo = macro[t].get("f2_lodo", [float("nan")] * 2)
        lines.append(f"| {t} | {cells} | {macro[t]['f2']:.4f} | {lodo[0]:.4f}–{lodo[1]:.4f} | {macro[t]['f1']:.4f} | {macro[t]['f05']:.4f} |")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", type=Path, required=True)
    ap.add_argument("--baseline", required=True, help="nullpii's core regime")
    ap.add_argument("--not-competitors", default="", help="comma list of other nullpii rows")
    ap.add_argument("--better-row", action="store_true",
                    help="rule change 10: S1 against each competitor's better row, S2 and reversals against both")
    ap.add_argument("--table-only", action="store_true", help="a reported set: the table, no S1 or S2")
    args = ap.parse_args()

    report = json.loads(args.report.read_text(encoding="utf-8"))
    datasets = [d for d in report if not d.startswith("_")]
    tools = list(report["_macro"])
    rivals = competitors(tools, args.baseline, set(filter(None, args.not_competitors.split(","))))
    if MASK_ALL not in tools:
        raise ValueError("the report has no mask-all row: run char_metrics.py with --mask-all")

    print("\n".join(table(report, datasets, tools)))
    if args.table_only:
        return
    s1_rows = better_rows(report["_macro"], rivals) if args.better_row else rivals
    tested = both_rows(rivals, tools) if args.better_row else rivals
    s1_ok, s1_lines = s1(report["_macro"], s1_rows)
    row_kind = "better row (tuned or default)" if args.better_row else "tuned operating point"
    print(f"\nS1 {'holds' if s1_ok else 'FAILS'} ({len(rivals)} competitors at their {row_kind}):")
    print("\n".join(s1_lines))
    s2_ok, s2_lines = s2(report, datasets, tested)
    print(f"\nS2 {'holds' if s2_ok else 'FAILS'}" + (":" if s2_lines else ": no dataset where a competitor has significantly higher recall at matched precision"))
    print("\n".join(s2_lines))
    rev = reversals(report, [*datasets, "_macro"], tested)
    print(f"\nF1 / F0.5 reversals against F2 ({len(rev)}):")
    print("\n".join(rev) if rev else "  none")


if __name__ == "__main__":
    main()
