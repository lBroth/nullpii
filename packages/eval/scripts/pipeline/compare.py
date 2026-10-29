# SPDX-License-Identifier: Apache-2.0
"""Compare a new run's outputs with the published ones, at the precision
the docs print them, and say which numbers and which claims moved.

Every nullpii number is compared on the rounded value a reader sees, so a
change below the printed digit is no change. Derived claims are compared
too: nullpii's rank among the tools, and the sign of every paired interval
"nullpii minus tool" (ahead, too close to call, behind), since a change
there makes a sentence of the docs false. A change against nullpii is
"worse", and any worse change needs the owner's approval."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from pipeline import recipe, settings

HIGHER, LOWER = "higher", "lower"
PERCENT, PLAIN = 100.0, 1.0
SAME, BETTER, WORSE, NEW, GONE = "same", "better", "worse", "new", "not measured any more"
EXIT_UNCHANGED, EXIT_CHANGED, EXIT_WORSE = 0, 3, 4
AHEAD, CLOSE, BEHIND = "ahead", "too close to call", "behind"
CLAIM_ORDER = {BEHIND: 0, CLOSE: 1, AHEAD: 2}
MASK_ALL_ROW = "mask-all"
DEFAULT_ROW_SUFFIX = "@default"


@dataclass(frozen=True)
class Metric:
    """A number as the docs print it: `value * scale` to `decimals`."""

    value: float
    better: str
    scale: float
    decimals: int

    def __post_init__(self) -> None:
        if not isinstance(self.value, (int, float)) or isinstance(self.value, bool):
            raise TypeError(f"a metric needs a number, not {self.value!r}")

    @property
    def shown(self) -> float:
        return round(self.value * self.scale, self.decimals)


@dataclass(frozen=True)
class Change:
    where: str
    before: str
    after: str
    verdict: str


AB1_FIELDS = {
    "leak_rate": (LOWER, PERCENT, 1),
    "keep_rate": (HIGHER, PERCENT, 1),
    "docs_with_leak": (LOWER, PERCENT, 1),
    "clean_docs_masked": (LOWER, PERCENT, 1),
    "outside_per_1k": (LOWER, PLAIN, 2),
    "encoded_leak_rate": (LOWER, PERCENT, 1),
    "json_parse_rate": (HIGHER, PERCENT, 1),
    "diff_consistent_rate": (HIGHER, PERCENT, 1),
}
AB1_BREAKDOWNS = {"leak_by_category": LOWER, "keep_by_kind": HIGHER}
R3_SET_FIELDS = ("f2", "recall", "precision")
R3_MACRO_FIELDS = ("f2", "f1", "f05")
R3_DECIMALS = 3
PIIMB_DECIMALS = 3
R3_TABLES = ("char-r3", "char-r3-en", "char-r3-reported")
R3_RANKED = ("char-r3", "char-r3-en")


def _load(path: Path) -> dict | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def _nullpii_rows(table: dict, aliases: dict[str, str]) -> dict[str, dict]:
    """The rows of nullpii's measured configurations, under their current
    names: a row `aliases` renames, or one named for a preset."""
    current = {settings.tool_name(p) for p in settings.PRESETS}
    rows = {aliases.get(name, name): row for name, row in table.items()}
    return {name: row for name, row in rows.items() if name in current}


def ab1_metrics(out: Path, aliases: dict[str, str]) -> dict[str, Metric]:
    metrics: dict[str, Metric] = {}
    for key in settings.AB1_GOLD:
        scores = _load(out / "ab1" / f"scores-{key}.json")
        for name, row in _nullpii_rows(scores or {}, aliases).items():
            for field, (better, scale, decimals) in AB1_FIELDS.items():
                # None: the set has no item the rate is about (B1 and B2
                # hold no encoded value), so there is no number to compare.
                if row[field] is not None:
                    metrics[f"AB-1 {key} · {name} · {field}"] = Metric(row[field], better, scale, decimals)
            for breakdown, better in AB1_BREAKDOWNS.items():
                for part, (rate, _n) in row[breakdown].items():
                    metrics[f"AB-1 {key} · {name} · {breakdown} {part}"] = Metric(rate, better, PERCENT, 1)
        coverage = _load(out / "ab1" / f"coverage-{key}.json")
        for name, row in _nullpii_rows((coverage or {}).get("tools", {}), aliases).items():
            for field in ("leak_covered", "leak_uncovered"):
                metrics[f"AB-1 {key} · {name} · {field}"] = Metric(row[field], LOWER, PERCENT, 1)
    roundtrip = _load(out / "ab1" / "roundtrip.json")
    if roundtrip is not None:
        metrics["AB-1 · round trip failures"] = Metric(roundtrip["roundtrip_failures"], LOWER, PLAIN, 0)
    return metrics


def r3_metrics(out: Path, aliases: dict[str, str]) -> dict[str, Metric]:
    metrics: dict[str, Metric] = {}
    for table_name in R3_TABLES:
        table = _load(out / "r3" / f"{table_name}.json")
        if table is None:
            continue
        for dataset, rows in table.items():
            fields = R3_MACRO_FIELDS if dataset == "_macro" else R3_SET_FIELDS
            for name, row in _nullpii_rows(rows, aliases).items():
                for field in fields:
                    metrics[f"R3 {table_name} · {dataset} · {name} · {field}"] = Metric(
                        row[field], HIGHER, PLAIN, R3_DECIMALS)
    return metrics


def piimb_metrics(out: Path) -> dict[str, Metric]:
    metrics: dict[str, Metric] = {}
    for preset in settings.PRESETS:
        report = _load(out / "piimb" / f"piimb-{preset}.json")
        if report is None:
            continue
        name = settings.tool_name(preset)
        metrics[f"PIIMB · {name} · average F2"] = Metric(report["avg_f2"], HIGHER, PLAIN, PIIMB_DECIMALS)
        for task, scores in report["tasks"].items():
            metrics[f"PIIMB · {name} · {task} F2"] = Metric(scores["f2"], HIGHER, PLAIN, PIIMB_DECIMALS)
    return metrics


def _claim(ci: list[float], ahead_when_positive: bool) -> str:
    lo, hi = ci
    if lo > 0:
        return AHEAD if ahead_when_positive else BEHIND
    if hi < 0:
        return BEHIND if ahead_when_positive else AHEAD
    return CLOSE


def _is_competitor(name: str) -> bool:
    return not name.startswith(settings.NULLPII_PREFIX) and name != MASK_ALL_ROW


def r3_claims(out: Path) -> dict[str, str]:
    """nullpii's standing against each tool's row, from the paired CIs of
    every R3 report of the recipe."""
    claims: dict[str, str] = {}
    for run in recipe.R3_RUNS:
        macro = (_load(out / "r3" / f"{run.name}.json") or {}).get("_macro", {})
        for name, row in macro.items():
            if _is_competitor(name) and "baseline_minus_tool_f2_ci" in row:
                claims[f"R3 {run.name} · nullpii against {name} (F2)"] = _claim(row["baseline_minus_tool_f2_ci"], True)
    return claims


def ab1_claims(out: Path) -> dict[str, str]:
    """nullpii's standing against each tool on AB-1, from the paired CIs of
    leak (lower is better for nullpii) and keep."""
    claims: dict[str, str] = {}
    for key in settings.AB1_GOLD:
        for name, row in (_load(out / "ab1" / f"scores-{key}.json") or {}).items():
            ci = row.get("ci", {})
            if not _is_competitor(name) or "baseline_minus_tool_leak" not in ci:
                continue
            claims[f"AB-1 {key} · nullpii against {name} (leak)"] = _claim(ci["baseline_minus_tool_leak"], False)
            claims[f"AB-1 {key} · nullpii against {name} (keep)"] = _claim(ci["baseline_minus_tool_keep"], True)
    return claims


def _best_rows(macro: dict, field: str) -> dict[str, float]:
    """Each tool's better row (tuned or `@default`) on `field`."""
    best: dict[str, float] = {}
    for name, row in macro.items():
        if _is_competitor(name):
            tool = name.removesuffix(DEFAULT_ROW_SUFFIX)
            best[tool] = max(best.get(tool, row[field]), row[field])
    return best


def r3_ranks(out: Path, aliases: dict[str, str]) -> dict[str, Metric]:
    """nullpii's rank in each configuration among the tools' better rows,
    by macro F2 and by macro F0.5 (1 is first)."""
    ranks: dict[str, Metric] = {}
    for table_name in R3_RANKED:
        macro = (_load(out / "r3" / f"{table_name}.json") or {}).get("_macro", {})
        for field in ("f2", "f05"):
            others = _best_rows(macro, field)
            for name, row in _nullpii_rows(macro, aliases).items():
                rank = 1 + sum(1 for v in others.values() if v > row[field])
                ranks[f"R3 {table_name} · {name} · rank by {field} of {len(others) + 1}"] = Metric(rank, LOWER, PLAIN, 0)
    return ranks


def all_metrics(out: Path, aliases: dict[str, str]) -> dict[str, Metric]:
    return {**ab1_metrics(out, aliases), **r3_metrics(out, aliases), **piimb_metrics(out), **r3_ranks(out, aliases)}


def _verdict(before: Metric, after: Metric) -> str:
    if before.shown == after.shown:
        return SAME
    went_up = after.shown > before.shown
    return BETTER if went_up == (after.better == HIGHER) else WORSE


def _fmt(m: Metric) -> str:
    return f"{m.shown:.{m.decimals}f}"


def compare_metrics(before: dict[str, Metric], after: dict[str, Metric]) -> list[Change]:
    changes = [Change(k, _fmt(before[k]), _fmt(m), _verdict(before[k], m)) for k, m in after.items() if k in before]
    changes += [Change(k, "—", _fmt(m), NEW) for k, m in after.items() if k not in before]
    changes += [Change(k, _fmt(m), "—", GONE) for k, m in before.items() if k not in after]
    return changes


def compare_claims(before: dict[str, str], after: dict[str, str]) -> list[Change]:
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old is None or new is None:
            changes.append(Change(key, old or "—", new or "—", NEW if old is None else GONE))
        elif old != new:
            changes.append(Change(key, old, new, BETTER if CLAIM_ORDER[new] > CLAIM_ORDER[old] else WORSE))
    return changes


def compare(new: Path, reference: Path, reference_aliases: dict[str, str]) -> list[Change]:
    """Every metric and claim of the run in `new` against `reference`,
    whose nullpii rows `reference_aliases` renames to their current names."""
    metrics = compare_metrics(all_metrics(reference, reference_aliases), all_metrics(new, {}))
    claims = compare_claims({**ab1_claims(reference), **r3_claims(reference)}, {**ab1_claims(new), **r3_claims(new)})
    return metrics + claims


def exit_code(changes: list[Change]) -> int:
    if any(c.verdict == WORSE for c in changes):
        return EXIT_WORSE
    return EXIT_CHANGED if any(c.verdict != SAME for c in changes) else EXIT_UNCHANGED


def report(changes: list[Change]) -> str:
    """The changes as a Markdown summary and table, worse ones first."""
    moved = [c for c in changes if c.verdict != SAME]
    counts = {v: sum(1 for c in moved if c.verdict == v) for v in (WORSE, BETTER, NEW, GONE)}
    head = ", ".join(f"{n} {v}" for v, n in counts.items() if n) or "nothing moved"
    order = {WORSE: 0, BETTER: 1, NEW: 2, GONE: 3}
    lines = [f"**{head}** (of {len(changes)} numbers and claims compared).", ""]
    if moved:
        lines += ["| | Before | After | |", "|---|---:|---:|---|"]
        lines += [f"| {c.where} | {c.before} | {c.after} | {c.verdict} |"
                  for c in sorted(moved, key=lambda c: (order[c.verdict], c.where))]
    return "\n".join(lines) + "\n"
