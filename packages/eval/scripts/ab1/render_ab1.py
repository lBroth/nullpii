# SPDX-License-Identifier: Apache-2.0
"""Write AB-1's tables into README.md and METHOD.md from `agent_metrics.py` reports.

Which rows go where was fixed before any score was read (LOG, 25 Oct):
- README (component A only): one row per tool, its tuned `+agent` row (its
  operating point tuned on the tuning set, with the agent-policy post-filter),
  and nullpii's agent default.
- METHOD (A, B1, B2): every competitor row, tuned and default, each raw and
  `+agent`, and nullpii's agent default (its `+agent` row is left out: with
  the readable categories off it emits none of them); then, for A, the
  secondary metrics and the leak rate per category on the README's rows.
Rows are sorted by leak rate, then by keep rate (higher first); there is no
combined score. Intervals are paired bootstrap 95% CIs of nullpii minus the
tool, in percentage points: a negative leak or a positive keep difference
favours nullpii. Aggregates only; the reports hold no text.

  python render_ab1.py --a scores-ab1-a.json --b1 scores-ab1-b1.json \\
      --b2 scores-ab1-b2.json --readme README.md --method METHOD.md \\
      [--cov-a coverage-ab1-a.json --cov-b1 ... --cov-b2 ...]

The benchmark pipeline (`bench_pipeline.py render`) calls the table
functions with the nullpii rows of a run (`nullpii`: each row's key and
label, `baseline`: the row the intervals are against); the defaults are
the published run's one row.
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
# The nullpii rows a report holds, each with its label, as the functions
# below take them; the published run has one.
Nullpii = dict[str, str]
PUBLISHED_NULLPII: Nullpii = {BASELINE: NAMES[BASELINE]}
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


def is_nullpii(key: str) -> bool:
    return key.startswith("nullpii")


def label(key: str, nullpii: Nullpii = PUBLISHED_NULLPII) -> str:
    tool, tuned, agent = split(key)
    if tool in nullpii:
        return f"**{nullpii[tool]}**"
    if tool not in NAMES:
        raise SystemExit(f"no display name for {tool}")
    return f"{NAMES[tool]} ({'tuned' if tuned else 'default'}{', +agent' if agent else ''})"


def wanted(report: dict, readme: bool, nullpii: Nullpii = PUBLISHED_NULLPII) -> list[str]:
    """The rows a table shows: nullpii's (not their `+agent` variant, which
    with the readable categories off emits none of them) and every other
    tool's, all of them in METHOD and the tuned `+agent` ones in the README.
    A nullpii row not in `nullpii` (an earlier one) is left out."""
    keys = []
    for k in report:
        tool, tuned, agent = split(k)
        if is_nullpii(tool):
            if tool in nullpii and not agent:
                keys.append(k)
        elif not readme or (tuned and agent):
            keys.append(k)
    return sorted(keys, key=lambda k: (report[k]["leak_rate"], -report[k]["keep_rate"], k))


# The main table's value columns and which end is best. Bold marks the best
# printed value of each column among the rows shown (every row that prints
# it, on a tie), as in the README's other tables.
MAIN_COLUMNS = (("leak_rate", min), ("keep_rate", max), ("docs_with_leak", min))


def best_cells(report: dict, keys: list[str]) -> dict[str, str]:
    """Per main column, the best value among `keys`, as printed."""
    return {field: pct(pick(report[k][field] for k in keys)) for field, pick in MAIN_COLUMNS}


def row(report: dict, k: str, best: dict[str, str], nullpii: Nullpii = PUBLISHED_NULLPII) -> str:
    ci = report[k].get("ci", {})
    cells = []
    for field, _ in MAIN_COLUMNS:
        text = pct(report[k][field])
        cells.append(f"**{text}**" if text == best[field] else text)
    return (f"| {label(k, nullpii)} | {' | '.join(cells)} | "
            f"{pp(ci.get('baseline_minus_tool_leak'))} | {pp(ci.get('baseline_minus_tool_keep'))} |")


def caption(report: dict, baseline: str = BASELINE) -> str:
    b = report[baseline]
    return (f"{b['docs']:,} documents, {b['items']['must_mask']:,} items that must be masked and "
            f"{b['items']['must_keep']:,} that must stay readable.")


def main_table(report: dict, readme: bool, nullpii: Nullpii = PUBLISHED_NULLPII, baseline: str = BASELINE) -> str:
    keys = wanted(report, readme, nullpii)
    best = best_cells(report, keys)
    return "\n".join([caption(report, baseline), "", HEAD] + [row(report, k, best, nullpii) for k in keys])


def secondary(report: dict, nullpii: Nullpii = PUBLISHED_NULLPII, baseline: str = BASELINE) -> str:
    keys = wanted(report, readme=True, nullpii=nullpii)
    out = ["| Tool | Clean docs with anything masked | Masked outside items, per 1,000 chars | Encoded leak rate "
           "| JSON still parses | Diff hunks consistent |", "|---|---:|---:|---:|---:|---:|"]
    for k in keys:
        r = report[k]
        out.append(f"| {label(k, nullpii)} | {pct(r['clean_docs_masked'])} | {r['outside_per_1k']:.2f} | "
                   f"{pct(r['encoded_leak_rate'])} | {pct(r['json_parse_rate'])} | {pct(r['diff_consistent_rate'])} |")
    cats = sorted({c for k in keys for c in report[k]["leak_by_category"]})
    counts = report[baseline]["leak_by_category"]
    out += ["", "Leak rate per category (items in brackets):", "",
            "| Tool | " + " | ".join(f"{c} ({counts[c][1]:,})" if c in counts else c for c in cats) + " |",
            "|---|" + "---:|" * len(cats)]
    for k in keys:
        by = report[k]["leak_by_category"]
        out.append(f"| {label(k, nullpii)} | " + " | ".join(pct(by[c][0]) if c in by else "—" for c in cats) + " |")
    return "\n".join(out)


def coverage(reports: dict, cov: dict, nullpii: Nullpii = PUBLISHED_NULLPII) -> str:
    """Secrets' leak rate on items the recognizer pack covers and on the rest
    (`secret_coverage.py`), on the README's rows of each set."""
    sets = [k for k in ("a", "b1", "b2") if k in cov]
    head = " | ".join(f"{k.upper()} covered ({cov[k]['covered']:,}) | {k.upper()} not covered ({cov[k]['uncovered']:,})" for k in sets)
    out = [f"| Tool | {head} |", "|---|" + "---:|---:|" * len(sets)]
    for key in wanted(reports["a"], readme=True, nullpii=nullpii):
        cells = []
        for k in sets:
            t = cov[k]["tools"].get(key)
            cells += [pct(t["leak_covered"]), pct(t["leak_uncovered"])] if t else ["—", "—"]
        out.append(f"| {label(key, nullpii)} | " + " | ".join(cells) + " |")
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
    for k in ("a", "b1", "b2"):
        ap.add_argument(f"--cov-{k}", type=Path, help="secret_coverage.py report")
    args = ap.parse_args()
    reports = {k: json.loads(getattr(args, k).read_text(encoding="utf-8")) for k in ("a", "b1", "b2")}
    for k, r in reports.items():
        if BASELINE not in r:
            raise SystemExit(f"{k}: no {BASELINE} row")
    put(args.readme, "ab1-a", main_table(reports["a"], readme=True))
    put(args.method, "ab1-a", main_table(reports["a"], readme=False) + "\n\n" + secondary(reports["a"]))
    put(args.method, "ab1-b1", main_table(reports["b1"], readme=False))
    put(args.method, "ab1-b2", main_table(reports["b2"], readme=False))
    cov = {k: json.loads(p.read_text(encoding="utf-8")) for k in ("a", "b1", "b2") if (p := getattr(args, f"cov_{k}"))}
    if cov:
        put(args.method, "ab1-coverage", coverage(reports, cov))


if __name__ == "__main__":
    main()
