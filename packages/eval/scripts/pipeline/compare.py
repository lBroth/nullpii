# SPDX-License-Identifier: Apache-2.0
"""Compare a new run's outputs with a reference (the published ones, or an
earlier run's), at the precision the docs print them, and say which
numbers and which claims moved.

What is compared, each number on the rounded value a reader sees, so a
change below the printed digit is no change:

- AB-1: nullpii's rates and their breakdowns per category and kind, its
  leak rate on secrets the recognizer pack covers and on the others, how
  many secrets the pack covers (which also splits every other tool's
  coverage cells, compared too), and the round trip's counts;
- R3: per set F2, recall and precision; macro F2, F1, F0.5, recall and
  precision (the means of the per-set values, as the README matrix
  prints them) and the leave-one-out range, on the gated, English and
  reported sets; each leave-one-out report's macro F2;
- PIIMB: average F2, F2 per task, the place on the leaderboard, and the
  average and place without the task from nullpii's training family;
- ranks: on R3, nullpii's among each tool's better row: by macro F2 and
  F0.5 (each tool at its best row on that measure), by macro F0.5, recall
  and precision at each tool's best-F2 row (the rows the matrix shows),
  by F2 on each set, and by macro F2 on each leave-one-out report; on
  AB-1, among each tool's tuned `+agent` row (the README's), by leak rate,
  keep rate and leak rate per category, on each set;
- claims: the sign of every paired interval "nullpii minus tool" (ahead,
  too close to call, behind) and its two bounds as printed, on AB-1 (leak
  and keep) and on every R3 report of the recipe (F2), keyed by the
  nullpii row the interval is against; and the text of every R3 verdict.

Like for like only. A reference row is compared with the run's row of the
same configuration and nothing else: a reference in the published run's
names (`PUBLISHED`) reads the 0.5 agent default on AB-1 as `default` and
every category masked on R3 as `everything`. The published core regime
has no configuration measured now: its rows, the intervals and verdicts
against it, and its own reports are listed as "dropped (core regime no
longer published)", never as better or worse; the run's `default` rows
on R3, and its intervals and verdicts, are "new".

A change against nullpii is "worse", and any worse change needs the
owner's approval. So does a number or claim the reference has and the run
no longer gives ("not measured any more") when it is not declared
dropped. A count with no better direction (how many secrets the pack
covers, how many documents had something masked) is "moved".

Outputs that lack a file or a nullpii row they should hold, or hold a
nullpii row that is neither measured now nor declared, are an error,
never "nothing to compare". `NOT_COMPARED` lists what the docs print that
no comparison covers, and why."""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from pipeline import recipe, settings

HIGHER, LOWER, EITHER = "higher", "lower", "either way"
PERCENT, PLAIN = 100.0, 1.0
COUNT_DECIMALS = 0
SAME, BETTER, WORSE, MOVED, NEW, GONE = "same", "better", "worse", "moved", "new", "not measured any more"
DROPPED = "dropped (core regime no longer published)"
NUMBER, CLAIM, VERDICT, REPORT = "number", "claim", "verdict", "report"
EXIT_UNCHANGED, EXIT_CHANGED, EXIT_WORSE = 0, 3, 4
AHEAD, CLOSE, BEHIND = "ahead", "too close to call", "behind"
CLAIM_ORDER = {BEHIND: 0, CLOSE: 1, AHEAD: 2}
MASK_ALL_ROW = "mask-all"
DEFAULT_ROW_SUFFIX = "@default"
AGENT_ROW_SUFFIX = "+agent"
MACRO = "_macro"
VERDICT_SUFFIX = ".txt"
ABSENT = "—"

# What the docs print that `compare` does not judge, and why.
NOT_COMPARED: tuple[tuple[str, str], ...] = (
    ("other tools' own numbers (rates, F2s, PIIMB scores)",
     "frozen: their predictions of the published run are never run again"),
    ("differences and gaps quoted in words (\"5 to 46 points\", \"+0.030\", \"0.039 behind\")",
     "each is a compared nullpii number minus a frozen tool's, so it moves only when that number moves"),
    ("counts of tools ahead or behind (\"8 of the 14\", \"11 of the 15\") and which column is bold",
     "each is a compared rank; a count of significant leads is the compared interval signs"),
    ("the split of CredData's leaks into UUIDs and other secrets (\"268 of 490\", \"13.0%\")",
     "no output holds it: no tracked script computes it"),
    ("F1 and F0.5 paired intervals", "in the reports, never printed in the docs"),
    ("rows the published run scored but the docs never print",
     "earlier nullpii rows (settings.PUBLISHED_UNPRINTED) and nullpii's own `+agent` rows"),
    ("latency", "never measured in CI: timed by hand on quiet machines"),
    ("the CPU/CUDA difference (\"37 of the 14,701\") and the fp32 check",
     "a one-off measurement of the published run, not an output of `score`"),
    ("dataset and gold facts (sizes, overlaps, the Bonferroni level)", "constants of the frozen inputs"),
    ("history: released CHANGELOG entries and dated re-measurements", "never rewritten"),
)


class CompareError(Exception):
    """The outputs cannot be compared: a file or a row is missing, or a
    nullpii row is not declared."""


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
    kind: str = NUMBER


@dataclass(frozen=True)
class Layout:
    """What a set of outputs must hold to be compared, and how its nullpii
    rows are named.

    `aliases` renames rows to the current preset names they are like for
    like with; `dropped` lists rows of a configuration no longer published
    (reported as dropped), `unprinted` rows the docs never print (not
    compared); any other nullpii row is an error. `may_lack` lists output
    files this side has none of (the run's numbers there are new);
    `dropped_files` lists files of a dropped configuration, which must be
    there and are reported as dropped. `verdict_baseline` is the row the
    verdict texts are against. With `every_preset`, every table holds a row
    of each preset, else at least one row under a current name."""

    aliases: dict[str, str] = field(default_factory=dict)
    dropped: frozenset[str] = frozenset()
    unprinted: frozenset[str] = frozenset()
    may_lack: frozenset[str] = frozenset()
    dropped_files: tuple[str, ...] = ()
    verdict_baseline: str = settings.BASELINE
    every_preset: bool = True


def ab1_file(kind: str, key: str) -> str:
    return f"ab1/{kind}-{key}.json"


ROUNDTRIP_FILE = "ab1/roundtrip.json"


def r3_file(report: str) -> str:
    return f"r3/{report}.json"


def verdict_file(name: str) -> str:
    return f"r3/{name}{VERDICT_SUFFIX}"


def piimb_file(preset: str) -> str:
    return f"piimb/piimb-{preset}.json"


def lodo_reports() -> tuple[str, ...]:
    return tuple(run.name for run in recipe.R3_RUNS if run.name.startswith(LODO_PREFIX))


def expected_files() -> tuple[str, ...]:
    """Every output of a run, relative to its out directory: what `score`
    writes, and the round trip `capture --group ab1` writes."""
    ab1 = (ab1_file(kind, key) for key in settings.AB1_GOLD for kind in ("scores", "coverage"))
    r3 = (r3_file(run.name) for run in recipe.R3_RUNS)
    verdicts = (verdict_file(v.name) for v in recipe.VERDICTS)
    return (*ab1, ROUNDTRIP_FILE, *r3, *verdicts, *(piimb_file(p) for p in settings.PRESETS))


def published_dropped_files() -> tuple[str, ...]:
    """The published run's reports and verdict of the core regime alone."""
    return (*(r3_file(r.name) for r in recipe.CORE_LABEL_RUNS),
            *(verdict_file(v.name) for v in recipe.CORE_LABEL_VERDICTS))


# A run of `score`: every output, every preset, no other nullpii row.
RUN = Layout()
# The published outputs as `reference` lays them out (settings.py says why
# each row is read as it is).
PUBLISHED = Layout(
    aliases=dict(settings.PUBLISHED_ALIASES),
    dropped=settings.PUBLISHED_CORE_REGIME,
    unprinted=settings.PUBLISHED_UNPRINTED,
    may_lack=settings.PUBLISHED_ABSENT,
    dropped_files=published_dropped_files(),
    verdict_baseline=settings.PUBLISHED_VERDICT_BASELINE,
    every_preset=False,
)


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
AB1_INTERVALS = {"leak": LOWER, "keep": HIGHER}
AB1_INTERVAL_DECIMALS = 1
COVERAGE_COUNTS = ("covered", "uncovered")
COVERAGE_RATES = ("leak_covered", "leak_uncovered")
ROUNDTRIP_FIELDS = {"roundtrip_failures": LOWER, "masked": EITHER, "docs": EITHER}
R3_SET_FIELDS = ("f2", "recall", "precision")
R3_MACRO_FIELDS = ("f2", "f1", "f05")
R3_MACRO_MEANS = ("recall", "precision")
R3_LODO_RANGE = "f2_lodo"
R3_INTERVAL = "baseline_minus_tool_f2_ci"
R3_DECIMALS = 3
PIIMB_DECIMALS = 3
PIIMB_KEYS = ("avg_f2", "tasks", "leaderboard", "without")
R3_TABLES = ("char-r3", "char-r3-en", "char-r3-reported")
# Ranked with each tool at its best row on the measure itself.
R3_RANKED = {"char-r3": ("f2", "f05"), "char-r3-en": ("f2", "f05")}
# Ranked with each tool at its best-F2 row, the row the matrix shows.
R3_RANKED_AT_F2_ROW = {"char-r3": ("f05", "recall", "precision"), "char-r3-en": ("f05", "recall", "precision")}
LODO_PREFIX = "char-r3-lodo-"
LODO_RANKED = ("f2",)
AB1_RANKED = {"leak_rate": LOWER, "keep_rate": HIGHER}
AB1_RANKED_BREAKDOWN = "leak_by_category"


def _base(name: str) -> tuple[str, str]:
    """A row's name without its `+agent` post-filter suffix, and the suffix."""
    if name.endswith(AGENT_ROW_SUFFIX):
        return name.removesuffix(AGENT_ROW_SUFFIX), AGENT_ROW_SUFFIX
    return name, ""


def _current_names() -> frozenset[str]:
    return frozenset(settings.tool_name(p) for p in settings.PRESETS)


@dataclass(frozen=True)
class Outputs:
    """A run's output files, parsed, how its nullpii rows are named, and
    which of them this view reads: the current presets, or (`dropped`)
    the rows of a configuration no longer published."""

    files: dict[str, dict | str]
    layout: Layout
    names: frozenset[str] = field(default_factory=_current_names)

    def renamed(self, name: str) -> str:
        return self.layout.aliases.get(name, name)

    def rows(self, table: dict) -> dict[str, dict]:
        """The rows of `table` this view reads, under their current names."""
        rows: dict[str, dict] = {}
        for name, row in table.items():
            renamed = self.renamed(name)
            if renamed not in self.names:
                continue
            if renamed in rows:
                raise CompareError(f"two rows are {renamed} once renamed")
            rows[renamed] = row
        return rows

    def dropped(self) -> Outputs:
        """The view of the rows reported as dropped."""
        return replace(self, names=self.layout.dropped)

    @property
    def is_current(self) -> bool:
        return self.names == _current_names()


def _row_tables(rel: str, data: dict | str) -> list[tuple[str, dict]]:
    """The tables of an output file that hold one row per tool."""
    if rel.startswith("ab1/scores-"):
        return [(rel, data)]
    if rel.startswith("ab1/coverage-"):
        return [(rel, data["tools"])]
    if rel.startswith("r3/") and rel.endswith(".json"):
        return [(f"{rel} {dataset}", rows) for dataset, rows in data.items()]
    return []


def _undeclared(o: Outputs, names: list[str]) -> list[str]:
    """The nullpii rows among `names` that are neither a current preset
    (once renamed) nor declared dropped or unprinted; a nullpii `+agent`
    row is never printed, so only its base name must be declared."""
    known = _current_names() | o.layout.dropped | o.layout.unprinted
    nullpii = (n for n in names if n.startswith(settings.NULLPII_PREFIX))
    return sorted(n for n in nullpii if o.renamed(_base(n)[0]) not in known)


def _row_problems(o: Outputs) -> list[str]:
    presets = _current_names()
    problems = []
    for rel, data in o.files.items():
        for where, table in _row_tables(rel, data):
            found = set(o.rows(table))
            if odd := _undeclared(o, list(table)):
                problems.append(f"{where}: nullpii rows neither measured now nor declared: {', '.join(odd)}")
            if o.layout.every_preset and found != presets:
                problems.append(f"{where}: no row {', '.join(sorted(presets - found))}")
            elif not found:
                problems.append(f"{where}: no nullpii row under a current name")
    return problems


def _read(path: Path) -> dict | str:
    text = path.read_text(encoding="utf-8")
    return text if path.suffix == VERDICT_SUFFIX else json.loads(text)


def load(out: Path, layout: Layout) -> Outputs:
    """The outputs in `out`, checked to hold every file and row `layout`
    asks for and no undeclared nullpii row. Raises CompareError naming
    what is wrong."""
    if not out.is_dir():
        raise CompareError(f"{out} is not a directory of outputs")
    wanted = [rel for rel in expected_files() if rel not in layout.may_lack]
    missing = [rel for rel in (*wanted, *layout.dropped_files) if not (out / rel).is_file()]
    if missing:
        raise CompareError(f"{out} is not a complete set of outputs; missing:\n  " + "\n  ".join(missing))
    o = Outputs({rel: _read(out / rel) for rel in wanted}, layout)
    problems = _row_problems(o)
    if problems:
        raise CompareError(f"{out} has not the nullpii rows it should:\n  " + "\n  ".join(problems))
    return o


def _ab1_scores(o: Outputs, key: str) -> dict[str, Metric]:
    metrics: dict[str, Metric] = {}
    for name, row in o.rows(o.files[ab1_file("scores", key)]).items():
        for attr, (better, scale, decimals) in AB1_FIELDS.items():
            # None: the set has no item the rate is about (B1 and B2 hold
            # no encoded value), so there is no number to compare.
            if row[attr] is not None:
                metrics[f"AB-1 {key} · {name} · {attr}"] = Metric(row[attr], better, scale, decimals)
        for breakdown, better in AB1_BREAKDOWNS.items():
            for part, (rate, _n) in row[breakdown].items():
                metrics[f"AB-1 {key} · {name} · {breakdown} {part}"] = Metric(rate, better, PERCENT, 1)
    return metrics


def _ab1_coverage_rows(o: Outputs, key: str) -> dict[str, Metric]:
    """nullpii's leak rates split by its recognizer pack."""
    coverage = o.files[ab1_file("coverage", key)]
    return {
        f"AB-1 {key} · {name} · {rate}": Metric(row[rate], LOWER, PERCENT, 1)
        for name, row in o.rows(coverage["tools"]).items() for rate in COVERAGE_RATES
    }


def _ab1_coverage_run(o: Outputs, key: str) -> dict[str, Metric]:
    """How many secrets the pack covers, and every other tool's rates
    under that split (they move with it)."""
    coverage = o.files[ab1_file("coverage", key)]
    metrics = {
        f"AB-1 {key} · secrets {count} by nullpii's recognizer pack": Metric(coverage[count], EITHER, PLAIN, COUNT_DECIMALS)
        for count in COVERAGE_COUNTS
    }
    for name, row in coverage["tools"].items():
        if _is_competitor(name):
            for rate in COVERAGE_RATES:
                metrics[f"AB-1 {key} · {name} · {rate}"] = Metric(row[rate], EITHER, PERCENT, 1)
    return metrics


def ab1_metrics(o: Outputs) -> dict[str, Metric]:
    """AB-1's numbers of the rows the view reads."""
    metrics: dict[str, Metric] = {}
    for key in settings.AB1_GOLD:
        metrics |= _ab1_scores(o, key) | _ab1_coverage_rows(o, key)
    return metrics


def run_metrics(o: Outputs) -> dict[str, Metric]:
    """The numbers of the run as a whole, not of a nullpii row: the
    recognizer pack's coverage and the round trip on AB-1, and PIIMB (one
    report per preset)."""
    metrics: dict[str, Metric] = {}
    for key in settings.AB1_GOLD:
        metrics |= _ab1_coverage_run(o, key)
    roundtrip = o.files[ROUNDTRIP_FILE]
    for attr, better in ROUNDTRIP_FIELDS.items():
        metrics[f"AB-1 · round trip · {attr}"] = Metric(roundtrip[attr], better, PLAIN, COUNT_DECIMALS)
    return metrics | piimb_metrics(o)


def _mean(values: list[float]) -> float:
    # As render_matrix.macro: the plain mean over the sets the row is in.
    return sum(values) / len(values)


def _sets(table: dict) -> dict[str, dict]:
    return {dataset: rows for dataset, rows in table.items() if dataset != MACRO}


def _macro_mean(table: dict, name: str, f: str) -> float:
    values = [rows[name][f] for rows in _sets(table).values() if name in rows]
    if not values:
        raise CompareError(f"{name} has a macro row but is in no set")
    return _mean(values)


def _r3_table(o: Outputs, table_name: str) -> dict[str, Metric]:
    table = o.files[r3_file(table_name)]
    metrics: dict[str, Metric] = {}
    for dataset, rows in _sets(table).items():
        for name, row in o.rows(rows).items():
            for f in R3_SET_FIELDS:
                metrics[f"R3 {table_name} · {dataset} · {name} · {f}"] = Metric(row[f], HIGHER, PLAIN, R3_DECIMALS)
    for name, row in table[MACRO].items():
        current = o.renamed(name)
        if current not in o.names:
            continue
        where = f"R3 {table_name} · {MACRO} · {current}"
        for f in R3_MACRO_FIELDS:
            metrics[f"{where} · {f}"] = Metric(row[f], HIGHER, PLAIN, R3_DECIMALS)
        for f in R3_MACRO_MEANS:
            metrics[f"{where} · {f}"] = Metric(_macro_mean(table, name, f), HIGHER, PLAIN, R3_DECIMALS)
        low, high = row[R3_LODO_RANGE]
        metrics[f"{where} · leave-one-out low"] = Metric(low, HIGHER, PLAIN, R3_DECIMALS)
        metrics[f"{where} · leave-one-out high"] = Metric(high, HIGHER, PLAIN, R3_DECIMALS)
    return metrics


def r3_metrics(o: Outputs) -> dict[str, Metric]:
    metrics: dict[str, Metric] = {}
    for table_name in R3_TABLES:
        metrics |= _r3_table(o, table_name)
    for report in lodo_reports():
        for name, row in o.rows(o.files[r3_file(report)][MACRO]).items():
            metrics[f"R3 {report} · {MACRO} · {name} · f2"] = Metric(row["f2"], HIGHER, PLAIN, R3_DECIMALS)
    return metrics


def piimb_metrics(o: Outputs) -> dict[str, Metric]:
    metrics: dict[str, Metric] = {}
    for preset in settings.PRESETS:
        report = o.files.get(piimb_file(preset))
        if report is None:  # only where the layout allows it (load checks)
            continue
        if lacking := [k for k in PIIMB_KEYS if k not in report]:
            raise CompareError(f"{piimb_file(preset)} has no {', '.join(lacking)}: scored by an older piimb_score.py")
        name = settings.tool_name(preset)
        metrics[f"PIIMB · {name} · average F2"] = Metric(report["avg_f2"], HIGHER, PLAIN, PIIMB_DECIMALS)
        for task, scores in report["tasks"].items():
            metrics[f"PIIMB · {name} · {task} F2"] = Metric(scores["f2"], HIGHER, PLAIN, PIIMB_DECIMALS)
        place = report["leaderboard"]
        metrics[f"PIIMB · {name} · rank of {place['of']}"] = Metric(place["rank"], LOWER, PLAIN, COUNT_DECIMALS)
        rest = report["without"]
        where = f"PIIMB · {name} · without {rest['task']}"
        metrics[f"{where} · average F2"] = Metric(rest["avg_f2"], HIGHER, PLAIN, PIIMB_DECIMALS)
        metrics[f"{where} · rank of {rest['leaderboard']['of']}"] = Metric(
            rest["leaderboard"]["rank"], LOWER, PLAIN, COUNT_DECIMALS)
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


def _has_r3_ci(row: dict) -> bool:
    return R3_INTERVAL in row


def _has_ab1_ci(row: dict) -> bool:
    return "baseline_minus_tool_leak" in row.get("ci", {})


def _baseline(o: Outputs, rows: dict[str, dict], has_ci: Callable[[dict], bool], where: str) -> str | None:
    """The row the paired intervals of `rows` are against (the one row
    without one), under its current name; None when this view does not
    read it. A baseline neither measured now nor dropped is an error."""
    names = [name for name, row in rows.items() if not has_ci(row)]
    if len(names) != 1:
        raise CompareError(f"{where}: {len(names)} rows without a paired interval, not the one baseline")
    baseline = o.renamed(names[0])
    if baseline not in _current_names() | o.layout.dropped:
        raise CompareError(f"{where}: the intervals are against {names[0]}, neither measured now nor declared dropped")
    return baseline if baseline in o.names else None


def _bounds(where: str, ci: list[float], better: str, scale: float, decimals: int) -> dict[str, Metric]:
    low, high = ci
    return {f"{where} low": Metric(low, better, scale, decimals), f"{where} high": Metric(high, better, scale, decimals)}


def r3_claims(o: Outputs) -> tuple[dict[str, str], dict[str, Metric]]:
    """nullpii's standing against each tool's row, from the paired F2
    intervals of every R3 report of the recipe, and the intervals' bounds,
    for the reports whose baseline this view reads."""
    claims: dict[str, str] = {}
    bounds: dict[str, Metric] = {}
    for run in recipe.R3_RUNS:
        macro = o.files[r3_file(run.name)][MACRO]
        baseline = _baseline(o, macro, _has_r3_ci, r3_file(run.name))
        if baseline is None:
            continue
        for name, row in macro.items():
            if _is_competitor(name):
                where = f"R3 {run.name} · {baseline} against {name} (F2)"
                claims[where] = _claim(row[R3_INTERVAL], True)
                bounds |= _bounds(f"{where} interval", row[R3_INTERVAL], HIGHER, PLAIN, R3_DECIMALS)
    return claims, bounds


def ab1_claims(o: Outputs) -> tuple[dict[str, str], dict[str, Metric]]:
    """nullpii's standing against each tool on AB-1, from the paired
    intervals of leak (lower is better for nullpii) and keep, and their
    bounds in points as the tables print them."""
    claims: dict[str, str] = {}
    bounds: dict[str, Metric] = {}
    for key in settings.AB1_GOLD:
        scores = o.files[ab1_file("scores", key)]
        baseline = _baseline(o, scores, _has_ab1_ci, ab1_file("scores", key))
        if baseline is None:
            continue
        for name, row in scores.items():
            if not _is_competitor(name):
                continue
            for measure, better in AB1_INTERVALS.items():
                ci = row["ci"][f"baseline_minus_tool_{measure}"]
                where = f"AB-1 {key} · {baseline} against {name} ({measure})"
                claims[where] = _claim(ci, better == HIGHER)
                bounds |= _bounds(f"{where} interval", ci, better, PERCENT, AB1_INTERVAL_DECIMALS)
    return claims, bounds


def _best_rows(macro: dict, f: str) -> dict[str, float]:
    """Each tool's better row (tuned or `@default`) on `f`."""
    best: dict[str, float] = {}
    for name, row in macro.items():
        if _is_competitor(name):
            tool = name.removesuffix(DEFAULT_ROW_SUFFIX)
            best[tool] = max(best.get(tool, row[f]), row[f])
    return best


def _f2_rows(macro: dict) -> dict[str, str]:
    """Each tool's best-F2 row name (the row the matrix shows)."""
    best: dict[str, str] = {}
    for name, row in macro.items():
        if _is_competitor(name):
            tool = name.removesuffix(DEFAULT_ROW_SUFFIX)
            if tool not in best or row["f2"] > macro[best[tool]]["f2"]:
                best[tool] = name
    return best


def _macro_value(table: dict, name: str, f: str) -> float:
    return _macro_mean(table, name, f) if f in R3_MACRO_MEANS else table[MACRO][name][f]


def _r3_rank_entry(where: str, value: float, others: list[float]) -> dict[str, Metric]:
    rank = 1 + sum(1 for v in others if v > value)
    return {f"{where} of {len(others) + 1}": Metric(rank, LOWER, PLAIN, 0)}


def r3_ranks(o: Outputs) -> dict[str, Metric]:
    """nullpii's rank in each configuration among the tools' better rows
    (1 is first)."""
    ranked = {**R3_RANKED, **{report: LODO_RANKED for report in lodo_reports()}}
    ranks: dict[str, Metric] = {}
    for table_name, fields in ranked.items():
        macro = o.files[r3_file(table_name)][MACRO]
        for f in fields:
            others = list(_best_rows(macro, f).values())
            for name, row in o.rows(macro).items():
                ranks |= _r3_rank_entry(f"R3 {table_name} · {name} · rank by {f}", row[f], others)
    for table_name, fields in R3_RANKED_AT_F2_ROW.items():
        table = o.files[r3_file(table_name)]
        shown = _f2_rows(table[MACRO]).values()
        for f in fields:
            others = [_macro_value(table, row, f) for row in shown]
            for name in table[MACRO]:
                if o.renamed(name) in o.names:
                    where = f"R3 {table_name} · {o.renamed(name)} · rank by {f} at each tool's best-F2 row"
                    ranks |= _r3_rank_entry(where, _macro_value(table, name, f), others)
    for table_name in R3_TABLES:
        for dataset, rows in _sets(o.files[r3_file(table_name)]).items():
            others = list(_best_rows(rows, "f2").values())
            for name, row in o.rows(rows).items():
                ranks |= _r3_rank_entry(f"R3 {table_name} · {dataset} · {name} · rank by f2", row["f2"], others)
    return ranks


def _rank(value: float, others: list[float], better: str) -> int:
    """1 + how many of `others` are strictly better than `value`."""
    ahead = (v < value if better == LOWER else v > value for v in others)
    return 1 + sum(ahead)


def _ab1_ranked_rows(scores: dict) -> dict[str, dict]:
    """The row each other tool has in the README's AB-1 table: its tuned
    operating point with the agent-policy post-filter (`<tool>+agent`)."""
    return {
        name: row for name, row in scores.items()
        if _is_competitor(name) and name.endswith(AGENT_ROW_SUFFIX)
        and not name.removesuffix(AGENT_ROW_SUFFIX).endswith(DEFAULT_ROW_SUFFIX)
    }


def ab1_ranks(o: Outputs) -> dict[str, Metric]:
    """nullpii's rank among the other tools' README rows on each AB-1 set
    (1 lets the fewest through, or keeps the most): by leak rate, keep
    rate, and leak rate in each category ("on names, 11 of the 15 other
    tools let fewer through" is rank 12). A tool without a category is
    not counted in that category's rank."""
    ranks: dict[str, Metric] = {}
    for key in settings.AB1_GOLD:
        scores = o.files[ab1_file("scores", key)]
        others = _ab1_ranked_rows(scores)
        for name, row in o.rows(scores).items():
            for attr, better in AB1_RANKED.items():
                rank = _rank(row[attr], [r[attr] for r in others.values()], better)
                ranks[f"AB-1 {key} · {name} · rank by {attr} of {len(others) + 1}"] = Metric(rank, LOWER, PLAIN, 0)
            for part, (rate, _n) in row[AB1_RANKED_BREAKDOWN].items():
                rates = [r[AB1_RANKED_BREAKDOWN][part][0] for r in others.values() if part in r[AB1_RANKED_BREAKDOWN]]
                where = f"AB-1 {key} · {name} · rank by {AB1_RANKED_BREAKDOWN} {part} of {len(rates) + 1}"
                ranks[where] = Metric(_rank(rate, rates, LOWER), LOWER, PLAIN, 0)
    return ranks


def all_claims(o: Outputs) -> dict[str, str]:
    return {**ab1_claims(o)[0], **r3_claims(o)[0]}


def all_metrics(o: Outputs) -> dict[str, Metric]:
    """Every number of the view; the run-wide ones in the current view only."""
    metrics = {**ab1_metrics(o), **r3_metrics(o), **r3_ranks(o), **ab1_ranks(o),
               **ab1_claims(o)[1], **r3_claims(o)[1]}
    return {**metrics, **run_metrics(o)} if o.is_current else metrics


def all_verdicts(o: Outputs) -> dict[str, str]:
    """Each R3 verdict's text, keyed by the row it is against, when this
    view reads that row."""
    baseline = o.renamed(o.layout.verdict_baseline)
    if baseline not in _current_names() | o.layout.dropped:
        raise CompareError(f"the verdicts are against {o.layout.verdict_baseline}, neither measured now nor dropped")
    if baseline not in o.names:
        return {}
    return {f"R3 {v.name} · verdict against {baseline}": o.files[verdict_file(v.name)].strip()
            for v in recipe.VERDICTS}


def _verdict(before: Metric, after: Metric) -> str:
    if before.shown == after.shown:
        return SAME
    if after.better == EITHER:
        return MOVED
    went_up = after.shown > before.shown
    return BETTER if went_up == (after.better == HIGHER) else WORSE


def _fmt(m: Metric) -> str:
    return f"{m.shown:.{m.decimals}f}"


def compare_metrics(before: dict[str, Metric], after: dict[str, Metric]) -> list[Change]:
    changes = [Change(k, _fmt(before[k]), _fmt(m), _verdict(before[k], m)) for k, m in after.items() if k in before]
    changes += [Change(k, ABSENT, _fmt(m), NEW) for k, m in after.items() if k not in before]
    changes += [Change(k, _fmt(m), ABSENT, GONE) for k, m in before.items() if k not in after]
    return changes


def compare_claims(before: dict[str, str], after: dict[str, str]) -> list[Change]:
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old is None or new is None:
            changes.append(Change(key, old or ABSENT, new or ABSENT, NEW if old is None else GONE, CLAIM))
        elif old == new:
            changes.append(Change(key, old, new, SAME, CLAIM))
        else:
            changes.append(Change(key, old, new, BETTER if CLAIM_ORDER[new] > CLAIM_ORDER[old] else WORSE, CLAIM))
    return changes


def compare_verdicts(before: dict[str, str], after: dict[str, str]) -> list[Change]:
    """A verdict's text has no direction: its intervals are judged as
    claims, so a changed text is "moved"."""
    changes = []
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if old is None or new is None:
            changes.append(Change(key, ABSENT if old is None else "text", ABSENT if new is None else "text",
                                  NEW if old is None else GONE, VERDICT))
        else:
            changes.append(Change(key, "text", "text" if old == new else "another text",
                                  SAME if old == new else MOVED, VERDICT))
    return changes


def dropped_changes(o: Outputs) -> list[Change]:
    """Every number, claim, verdict and report of the dropped rows, listed
    as dropped: no configuration measured now is like for like with them."""
    view = o.dropped()
    changes = [Change(k, _fmt(m), ABSENT, DROPPED) for k, m in all_metrics(view).items()]
    changes += [Change(k, c, ABSENT, DROPPED, CLAIM) for k, c in all_claims(view).items()]
    changes += [Change(k, "text", ABSENT, DROPPED, VERDICT) for k in all_verdicts(view)]
    return changes + [Change(rel, "published", ABSENT, DROPPED, REPORT) for rel in o.layout.dropped_files]


def compare(new: Path, reference: Path, reference_layout: Layout = RUN) -> list[Change]:
    """Every metric, claim and verdict of the run in `new` against
    `reference`, like for like, and what of the reference is dropped.
    Raises CompareError when either side is incomplete or holds an
    undeclared nullpii row."""
    before, after = load(reference, reference_layout), load(new, RUN)
    changes = compare_metrics(all_metrics(before), all_metrics(after))
    changes += compare_claims(all_claims(before), all_claims(after))
    changes += compare_verdicts(all_verdicts(before), all_verdicts(after))
    return changes + dropped_changes(before)


# What needs the owner's approval: a number or claim that got worse, or
# one the reference has that the run no longer gives, undeclared. A drop
# the code declares (the core regime) was the owner's decision.
NEEDS_APPROVAL = (WORSE, GONE)


def exit_code(changes: list[Change]) -> int:
    if any(c.verdict in NEEDS_APPROVAL for c in changes):
        return EXIT_WORSE
    return EXIT_CHANGED if any(c.verdict != SAME for c in changes) else EXIT_UNCHANGED


ORDER = {WORSE: 0, GONE: 1, BETTER: 2, MOVED: 3, NEW: 4, DROPPED: 5}
KINDS = (NUMBER, CLAIM, VERDICT, REPORT)


def _compared(changes: list[Change], kind: str) -> int:
    """How many entries of `kind` both sides have."""
    return sum(1 for c in changes if c.kind == kind and c.verdict not in (NEW, GONE, DROPPED))


def report(changes: list[Change]) -> str:
    """The changes as a Markdown summary and table, those that need the
    owner's approval first, then what is not compared and why."""
    moved = [c for c in changes if c.verdict != SAME]
    counts = {v: sum(1 for c in moved if c.verdict == v) for v in ORDER}
    head = ", ".join(f"{n} {v}" for v, n in counts.items() if n) or "nothing moved"
    scope = (f"of {_compared(changes, NUMBER)} numbers, {_compared(changes, CLAIM)} claims and"
             f" {_compared(changes, VERDICT)} verdicts both sides have, like for like")
    lines = [f"**{head}** ({scope}).", ""]
    if moved:
        lines += ["| | Before | After | |", "|---|---:|---:|---|"]
        lines += [f"| {c.where} | {c.before} | {c.after} | {c.verdict} |"
                  for c in sorted(moved, key=lambda c: (ORDER[c.verdict], c.where))]
        lines.append("")
    lines += ["Not compared:", ""] + [f"- {what}: {why}." for what, why in NOT_COMPARED]
    return "\n".join(lines) + "\n"
