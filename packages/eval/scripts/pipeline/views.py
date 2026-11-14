# SPDX-License-Identifier: Apache-2.0
"""What the rendered docs read from a set of outputs (a run's `out`, the
published ones as `reference` lays them out, or `published-bench/`): the
rows each table shows, under which label, and nullpii's place among them.

It reads the outputs through `compare`, so a rendered rank, interval sign
or S2 claim is the one `compare` judges, from the same rows. nullpii is
shown in the configurations measured now (`settings.PRESETS`); a row of
the published core regime is never shown, and an interval against it is
never read as one against a configuration measured now."""
from __future__ import annotations

import json
from dataclasses import dataclass, replace
from functools import cached_property
from pathlib import Path

from pipeline import compare, settings

ROOT = settings.EVAL.parents[1]
PACKAGE_JSON = ROOT / "package.json"
# A `reference` directory, or a `published-bench/` written from one, holds
# the published run's row names.
REFERENCE_MARKER = "REFERENCE.json"
OUTPUTS_MARKER = "OUTPUTS.json"
PUBLISHED_NAMES, RUN_NAMES = "published", "run"

# How the docs name each configuration.
PRESET_LABELS = {"default": "agent default", "everything": "every category masked"}
CHART_SUFFIXES = {"default": "", "everything": ", every category"}

# The tools as the R3 tables name them (AB-1's names, but NVIDIA's two
# pipelines named after the model), and as the README's matrix names them.
R3_NAMES_OVERRIDE = {
    "nemotron-pii-raw": "nvidia/gliner-PII (library)",
    "nemotron-pii-nemo": "nvidia/gliner-PII (NVIDIA server)",
}
MATRIX_NAMES_OVERRIDE = {
    "nemotron-pii-raw": "nemotron-pii (`nvidia/gliner-PII`, library)",
    "nemotron-pii-nemo": "nemotron-pii (NVIDIA server pipeline)",
}
MASK_ALL_NAME = "mask everything"
# The README's matrix and the ranks it states count NVIDIA's two nemotron
# pipelines as one tool, at the better of the two.
TOOL_GROUPS = {"nemotron-pii-nemo": "nemotron-pii-raw"}
DEFAULT_SUFFIX = compare.DEFAULT_ROW_SUFFIX
DEFAULT_MARK = " (default)"

R3_MAIN, R3_EN, R3_REPORTED, R3_BONFERRONI = "char-r3", "char-r3-en", "char-r3-reported", "char-r3-bonferroni"


class ViewError(Exception):
    """The outputs do not hold what a rendered doc reads."""


# The version the published run measured; a run measures the build of the
# tree it runs in, whose version `render` records in published-bench's
# OUTPUTS.json, so a later version bump does not relabel its rows.
PUBLISHED_VERSION = "0.5"
VERSION_KEY = "version"


def package_version() -> str:
    """The tree's nullpii version as the docs print it (major.minor)."""
    major, minor = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))["version"].split(".")[:2]
    return f"{major}.{minor}"


def measured_version(source: Path, names: str) -> str:
    """The nullpii version the outputs in `source` measured."""
    marker = source / OUTPUTS_MARKER
    if marker.is_file():
        recorded = json.loads(marker.read_text(encoding="utf-8")).get(VERSION_KEY)
        if recorded is not None:
            return recorded
    return PUBLISHED_VERSION if names == PUBLISHED_NAMES else package_version()


def preset_of(name: str) -> str:
    preset = name.removeprefix(f"{settings.NULLPII_PREFIX}-")
    if preset not in settings.PRESETS or preset not in PRESET_LABELS:
        raise ViewError(f"{name} is not a configuration measured now")
    return preset


def nullpii_label(name: str, version: str) -> str:
    """A nullpii row's label in the tables and the prose."""
    return f"nullpii {version} ({PRESET_LABELS[preset_of(name)]})"


def chart_label(name: str, version: str) -> str:
    return f"nullpii {version}{CHART_SUFFIXES[preset_of(name)]}"


def tool_of(row: str) -> str:
    return row.removesuffix(DEFAULT_SUFFIX)


def names_of(layout_names: str) -> compare.Layout:
    """The layout of a set of outputs, for rendering: the published one
    without the core regime's own reports (rendering never reads them,
    and `published-bench/` does not keep them)."""
    if layout_names == PUBLISHED_NAMES:
        return replace(compare.PUBLISHED, dropped_files=())
    return compare.RUN


def layout_names(source: Path) -> str:
    if (source / REFERENCE_MARKER).is_file():
        return PUBLISHED_NAMES
    marker = source / OUTPUTS_MARKER
    if marker.is_file():
        names = json.loads(marker.read_text(encoding="utf-8"))["names"]
        if names not in (PUBLISHED_NAMES, RUN_NAMES):
            raise ViewError(f"{marker}: names {names!r}, not {PUBLISHED_NAMES} or {RUN_NAMES}")
        return names
    return RUN_NAMES


@dataclass(frozen=True)
class Row:
    """One row of an R3 table: its key in the report, its label, its macro
    values and its per-set values."""

    key: str
    label: str
    macro: dict
    sets: dict[str, dict]
    nullpii: str | None = None  # its current name, for a nullpii row

    @property
    def f2(self) -> float:
        return self.macro["f2"]

    def mean(self, field: str) -> float:
        values = [s[field] for s in self.sets.values()]
        return sum(values) / len(values)

    def value(self, field: str) -> float:
        """A macro value as the matrix prints it: recall and precision are
        the means of the per-set values, the F-scores the report's own."""
        return self.mean(field) if field in compare.R3_MACRO_MEANS else self.macro[field]


@dataclass(frozen=True)
class Bench:
    """A set of outputs, read for rendering."""

    o: compare.Outputs
    names: str
    version: str

    def label(self, name: str) -> str:
        return nullpii_label(name, self.version)

    def chart_label(self, name: str) -> str:
        return chart_label(name, self.version)

    def file(self, rel: str) -> dict | str:
        return self.o.files[rel]

    # AB-1 -----------------------------------------------------------------

    def ab1(self, key: str) -> dict:
        return self.o.files[compare.ab1_file("scores", key)]

    def ab1_coverage(self, key: str) -> dict:
        return self.o.files[compare.ab1_file("coverage", key)]

    def ab1_nullpii(self, key: str) -> dict[str, str]:
        """Each nullpii row of an AB-1 set: its key and its current name."""
        return {k: self.o.renamed(k) for k in self.ab1(key) if self.o.renamed(k) in self.o.names}

    def ab1_baseline(self, key: str) -> str:
        """The key of the row AB-1's intervals are against."""
        rows = [k for k, row in self.ab1(key).items() if not compare._has_ab1_ci(row)]
        if len(rows) != 1 or self.o.renamed(rows[0]) not in self.o.names:
            raise ViewError(f"AB-1 {key}: the intervals are not against one configuration measured now")
        return rows[0]

    def ab1_others(self, key: str) -> dict[str, dict]:
        """Each other tool's README row (tuned, `+agent`), by key."""
        return compare._ab1_ranked_rows(self.ab1(key))

    # R3 -------------------------------------------------------------------

    def r3(self, report: str) -> dict:
        return self.o.files[compare.r3_file(report)]

    def r3_sets(self, report: str) -> dict[str, dict]:
        return compare._sets(self.r3(report))

    def _row(self, report: str, key: str, label: str, nullpii: str | None = None) -> Row:
        sets = {d: rows[key] for d, rows in self.r3_sets(report).items() if key in rows}
        return Row(key, label, self.r3(report)[compare.MACRO][key], sets, nullpii)

    def r3_nullpii(self, report: str) -> list[Row]:
        """nullpii's rows in a report, in the order of settings.PRESETS."""
        macro = self.r3(report)[compare.MACRO]
        found = {self.o.renamed(k): k for k in macro if self.o.renamed(k) in self.o.names}
        return [self._row(report, found[n], self.label(n), n)
                for n in (settings.tool_name(p) for p in settings.PRESETS) if n in found]

    def r3_competitors(self, report: str, names: dict[str, str], grouped: bool) -> list[Row]:
        """Each other tool at its best-F2 row (`grouped`: NVIDIA's two
        pipelines as one tool), labelled from `names`, `(default)` where
        that row is its default."""
        macro = self.r3(report)[compare.MACRO]
        best: dict[str, str] = {}
        for tool, key in compare._f2_rows(macro).items():
            group = TOOL_GROUPS.get(tool, tool) if grouped else tool
            if group not in best or macro[key]["f2"] > macro[best[group]]["f2"]:
                best[group] = key
        return [self._row(report, key, r3_label(key, names)) for key in best.values()]

    def r3_mask_all(self, report: str) -> Row:
        return self._row(report, compare.MASK_ALL_ROW, MASK_ALL_NAME)

    def r3_baseline(self, report: str) -> str | None:
        """The current name of the row the report's intervals are against,
        or None when it is no configuration measured now (the published
        run's are against its core regime)."""
        return compare._baseline(self.o, self.r3(report)[compare.MACRO], compare._has_r3_ci, compare.r3_file(report))

    @cached_property
    def headline(self) -> str:
        """The nullpii row R3's prose is about: the default, else the first
        configuration the outputs have."""
        rows = self.r3_nullpii(R3_MAIN)
        if not rows:
            raise ViewError("R3 has no nullpii row measured now")
        return rows[0].nullpii

    # PIIMB ----------------------------------------------------------------

    def piimb(self) -> dict[str, dict]:
        """Each configuration's PIIMB report, by its current name."""
        reports = {}
        for preset in settings.PRESETS:
            report = self.o.files.get(compare.piimb_file(preset))
            if report is not None:
                reports[settings.tool_name(preset)] = report
        return reports


def r3_label(key: str, names: dict[str, str]) -> str:
    tool = tool_of(key)
    if tool not in names:
        raise ViewError(f"no display name for {tool}")
    return names[tool] + (DEFAULT_MARK if key.endswith(DEFAULT_SUFFIX) else "")


def load(source: Path) -> Bench:
    """The outputs in `source`, in the layout their markers say."""
    names = layout_names(source)
    try:
        return Bench(compare.load(source, names_of(names)), names, measured_version(source, names))
    except compare.CompareError as e:
        raise ViewError(str(e)) from e


def rank(value: float, others: list[float]) -> int:
    """1 + how many of `others` are strictly higher, as compare ranks."""
    return 1 + sum(1 for v in others if v > value)
