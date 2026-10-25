# SPDX-License-Identifier: Apache-2.0
"""Write AB-1's tables into README.md and METHOD.md from `agent_metrics.py` reports.

Which rows go where was fixed before any score was read (LOG, 25 Oct):
- README (component A only): one row per tool, its tuned `+agent` row (its
  operating point tuned on the tuning set, with the agent-policy post-filter),
  and nullpii's agent default.
- METHOD (A, B1, B2): every row, tuned and default, each raw and `+agent`;
  then, for A, the secondary metrics and the leak rate per category on the
  README's rows.
Rows are sorted by leak rate, then by keep rate (higher first); there is no
combined score. Intervals are paired bootstrap 95% CIs of nullpii minus the
tool, in percentage points: a negative leak or a positive keep difference
favours nullpii. Aggregates only; the reports hold no text.

  python render_ab1.py --a scores-ab1-a.json --b1 scores-ab1-b1.json \\
      --b2 scores-ab1-b2.json --readme README.md --method METHOD.md
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

BASELINE = "nullpii-H3b-cuda-agent"
AGENT = "+agent"
DEFAULT = "@default"
NAMES = {
    BASELINE: "nullpii 0.5 (agent default)",
    "deberta": "deberta PII",
    "piiranha": "piiranha",
    "ettin-68m": "ettin-68m",
    "rizzo-pii": "rizzo-pii",
    "pii-identifier": "pii-identifier",
    "openai-privacy-filter": "openai privacy-filter",
    "openmed-pf-multi-v2": "OpenMed privacy-filter-multilingual-v2",
    "gliner-pii-large-v1": "gliner-pii-large",
    "gliner-stream-pii": "gliner-stream-pii",
    "nemotron-pii-raw": "nemotron-pii, library",
    "nemotron-pii-nemo": "nemotron-pii, NVIDIA's server",
    "gliner-onnx-pii-fp32": "gliner_multi_pii (ONNX)",
    "openmed-small": "OpenMed PII Small",
    "openmed-large": "OpenMed PII Large",
    "presidio": "Presidio",
}
HEAD = ("| Tool | Leak rate | Keep rate | Docs with a leak | nullpii − tool, leak | nullpii − tool, keep |\n"
        "|---|---:|---:|---:|---|---|")


def pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.1f}%"


def pp(ci: list[float] | None) -> str:
    if ci is None:
        return "—"
    return "[" + ", ".join(f"{100 * v:+.1f}".replace("-", "−") for v in ci) + "]"


def split(key: str) -> tuple[str, bool, bool]:
    """(tool, tuned, agent) of a report key."""
    agent = key.endswith(AGENT)
    base = key[: -len(AGENT)] if agent else key
    default = base.endswith(DEFAULT)
    return (base[: -len(DEFAULT)] if default else base), not default, agent


def label(key: str) -> str:
    tool, tuned, agent = split(key)
    if tool not in NAMES:
        raise SystemExit(f"no display name for {tool}")
    if tool == BASELINE:
        return f"**{NAMES[tool]}**"
    return f"{NAMES[tool]} ({'tuned' if tuned else 'default'}{', +agent' if agent else ''})"


def wanted(report: dict, readme: bool) -> list[str]:
    keys = []
    for k in report:
        tool, tuned, agent = split(k)
        if tool == BASELINE:
            if not agent:
                keys.append(k)
        elif not readme or (tuned and agent):
            keys.append(k)
    return sorted(keys, key=lambda k: (report[k]["leak_rate"], -report[k]["keep_rate"], k))


def row(report: dict, k: str) -> str:
    r, ci = report[k], report[k].get("ci", {})
    return (f"| {label(k)} | {pct(r['leak_rate'])} | {pct(r['keep_rate'])} | {pct(r['docs_with_leak'])} | "
            f"{pp(ci.get('baseline_minus_tool_leak'))} | {pp(ci.get('baseline_minus_tool_keep'))} |")


def caption(report: dict) -> str:
    b = report[BASELINE]
    return (f"{b['docs']:,} documents, {b['items']['must_mask']:,} items that must be masked and "
            f"{b['items']['must_keep']:,} that must stay readable.")


def main_table(report: dict, readme: bool) -> str:
    return "\n".join([caption(report), "", HEAD] + [row(report, k) for k in wanted(report, readme)])


def secondary(report: dict) -> str:
    keys = wanted(report, readme=True)
    out = ["| Tool | Clean docs with anything masked | Masked outside items, per 1,000 chars | Encoded leak rate "
           "| JSON still parses | Diff hunks consistent |", "|---|---:|---:|---:|---:|---:|"]
    for k in keys:
        r = report[k]
        out.append(f"| {label(k)} | {pct(r['clean_docs_masked'])} | {r['outside_per_1k']:.2f} | "
                   f"{pct(r['encoded_leak_rate'])} | {pct(r['json_parse_rate'])} | {pct(r['diff_consistent_rate'])} |")
    cats = sorted({c for k in keys for c in report[k]["leak_by_category"]})
    counts = report[BASELINE]["leak_by_category"]
    out += ["", "Leak rate per category (items in brackets):", "",
            "| Tool | " + " | ".join(f"{c} ({counts[c][1]:,})" if c in counts else c for c in cats) + " |",
            "|---|" + "---:|" * len(cats)]
    for k in keys:
        by = report[k]["leak_by_category"]
        out.append(f"| {label(k)} | " + " | ".join(pct(by[c][0]) if c in by else "—" for c in cats) + " |")
    return "\n".join(out)


def put(path: Path, marker: str, body: str) -> None:
    text = path.read_text(encoding="utf-8")
    pat = re.compile(rf"(<!-- {marker}:begin -->\n).*?(<!-- {marker}:end -->)", re.S)
    if len(pat.findall(text)) != 1:
        raise SystemExit(f"{path}: expected one {marker} block")
    path.write_text(pat.sub(lambda m: m.group(1) + body + "\n" + m.group(2), text), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    for k in ("a", "b1", "b2", "readme", "method"):
        ap.add_argument(f"--{k}", type=Path, required=True)
    args = ap.parse_args()
    reports = {k: json.loads(getattr(args, k).read_text(encoding="utf-8")) for k in ("a", "b1", "b2")}
    for k, r in reports.items():
        if BASELINE not in r:
            raise SystemExit(f"{k}: no {BASELINE} row")
    put(args.readme, "ab1-a", main_table(reports["a"], readme=True))
    put(args.method, "ab1-a", main_table(reports["a"], readme=False) + "\n\n" + secondary(reports["a"]))
    put(args.method, "ab1-b1", main_table(reports["b1"], readme=False))
    put(args.method, "ab1-b2", main_table(reports["b2"], readme=False))


if __name__ == "__main__":
    main()
