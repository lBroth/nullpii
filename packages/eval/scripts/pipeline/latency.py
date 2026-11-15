# SPDX-License-Identifier: Apache-2.0
"""The published latency: timed by hand on a quiet machine, never by the
benchmark workflow (a shared runner is too noisy to time anything).

`published-bench/latency/latency.json` holds it: the machine and the plan
of each table, every other tool's medians as that tool's timing gave
them, and nullpii's runs as the latency harness (`scripts/ab/harness.mjs
latency`) aggregates them: per size, the median and 95th percentile per
call, each round's median and the calls per round, never a text.
`harness_run` turns a harness file into such a run (`bench_pipeline.py
latency-run`).

No step of the pipeline writes the file, and `render` reads it whatever
outputs it renders, so a re-measurement of accuracy leaves the latency
as published; the docs say when, on which build and machine each row was
timed. nullpii's value at a size is the median of every round median of
its runs in that configuration and table."""
from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from pathlib import Path

from pipeline import settings
from pipeline.prose import RenderError

LATENCY = settings.PUBLISHED / "latency" / "latency.json"
SIZES = ("2000", "30000", "100000")
TABLES = ("gpu", "cpu")
# A preset that leaves readable a category the default masks, and masks
# secrets: the engine runs a second model pass for it (`src/secret-pass.ts`).
# Timed to publish that cost; it has no rows of its own.
PARTIAL = "secrets-only"
SECRET = "secret"
CONFIGS = (*settings.PRESETS, PARTIAL)
# What a harness file records of the engine besides the preset.
MODEL_DIR = "modelDir"
BACKEND = "backend"
DISABLED = "disabledCategories"
# The harness's aggregates per size, kept as it writes them.
SIZE_FIELDS = ("p50", "p95", "roundP50s", "callsPerRound")
RUN_FIELDS = ("label", "at", "plan", "node", "model", "config", "bySize")
# A model directory of nullpii's cache ends in <owner>/<repository>/<revision>.
MODEL_DIR_PARTS = 3


class LatencyError(RenderError):
    """The latency file does not hold what the docs read, or a harness
    file is not a latency run."""


def _positive(value: object, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise LatencyError(f"{where}: {value!r} is not a positive time in milliseconds")
    return float(value)


def _sizes(found: object, where: str) -> dict:
    if not isinstance(found, dict) or tuple(found) != SIZES:
        raise LatencyError(f"{where}: the sizes must be {', '.join(SIZES)}, in that order")
    return found


# Harness files --------------------------------------------------------------------

def _model(model_dir: str, where: str) -> str:
    parts = Path(model_dir).parts
    if len(parts) < MODEL_DIR_PARTS:
        raise LatencyError(f"{where}: {MODEL_DIR} does not end in <owner>/<repository>/<revision>")
    owner, repo, revision = parts[-MODEL_DIR_PARTS:]
    return f"{owner}/{repo}@{revision}"


def harness_run(raw: dict, where: str = "the harness file") -> dict:
    """A harness latency file as latency.json keeps a run: its aggregates,
    the engine options without the local model path, the model as
    `<owner>/<repository>@<revision>`. The harness's `dist` (a local path)
    is left out."""
    if raw.get("mode") != "latency":
        raise LatencyError(f"{where}: not a latency run of the harness")
    config = json.loads(raw["config"])
    model = _model(config.pop(MODEL_DIR), where) if MODEL_DIR in config else None
    if model is None:
        raise LatencyError(f"{where}: the engine options name no {MODEL_DIR}")
    by_size = {size: {k: values[k] for k in SIZE_FIELDS} for size, values in _sizes(raw["bySize"], where).items()}
    return {"label": raw["label"], "at": raw["at"], "plan": raw["plan"], "node": raw["node"], "model": model,
            "config": config, "bySize": by_size}


# The published file ---------------------------------------------------------------

def config_of(run: dict) -> str:
    """Which configuration a run timed, from its engine options."""
    options = {k: v for k, v in run["config"].items() if k != BACKEND}
    for preset, preset_options in settings.PRESETS.items():
        if options == preset_options:
            return preset
    disabled = options.get(DISABLED)
    if set(options) == {DISABLED} and isinstance(disabled, list) and disabled and SECRET not in disabled:
        return PARTIAL
    raise LatencyError(f"run {run.get('label')}: its options {options} are no configuration the docs publish")


@dataclass(frozen=True)
class Latency:
    """latency.json, checked: every table has its machine, its plan, the
    other tools' medians and nullpii's runs in each published
    configuration, timed by the table's backend on the table's plan."""

    data: dict

    def table(self, table: str) -> dict:
        return self.data["tables"][table]

    def machine(self, table: str) -> dict:
        return self.data["machines"][self.table(table)["machine"]]

    def plan(self, table: str) -> dict:
        return self.data["plans"][self.table(table)["plan"]]

    @property
    def tools_timing(self) -> dict:
        """When and how every other tool was timed."""
        return self.data["tools"]

    @property
    def nullpii_timing(self) -> dict:
        """When, on which build and how nullpii was timed."""
        return self.data["nullpii"]

    def tools(self, table: str) -> dict[str, dict[str, float]]:
        """Every other tool's medians in `table`, by tool key."""
        return self.data["tools"]["rows"][table]

    def runs(self, table: str, config: str) -> list[dict]:
        backend = self.table(table)[BACKEND]
        return [r for r in self.data["nullpii"]["runs"] if r["config"][BACKEND] == backend and config_of(r) == config]

    def nullpii(self, table: str, config: str) -> dict[str, float]:
        """nullpii's median per call in `table` and `config`, per size: the
        median of every round median of its runs."""
        runs = self.runs(table, config)
        if not runs:
            raise LatencyError(f"latency: no run of nullpii in {config} on {table}")
        return {s: statistics.median(m for r in runs for m in r["bySize"][s]["roundP50s"]) for s in SIZES}


def _check_run(run: dict, plans: dict, backends: dict[str, str]) -> None:
    where = f"latency run {run.get('label')}"
    if tuple(run) != RUN_FIELDS:
        raise LatencyError(f"{where}: its fields must be {', '.join(RUN_FIELDS)}")
    config_of(run)
    table = backends.get(run["config"].get(BACKEND))
    if table is None:
        raise LatencyError(f"{where}: backend {run['config'].get(BACKEND)!r} times no table")
    if run["plan"] != table["plan"]:
        raise LatencyError(f"{where}: plan {run['plan']}, the table's is {table['plan']}")
    plan = plans[run["plan"]]
    for size, values in _sizes(run["bySize"], where).items():
        rounds = values["roundP50s"]
        if values["callsPerRound"] != plan["texts"][size] or len(rounds) != plan["rounds"]:
            raise LatencyError(f"{where}: {size} characters was not timed on plan {run['plan']}")
        for v in (values["p50"], values["p95"], *rounds):
            _positive(v, where)


def check(data: dict) -> Latency:
    """`data` as latency.json must hold it, or LatencyError naming what is wrong."""
    plans, tables, machines = data["plans"], data["tables"], data["machines"]
    if tuple(tables) != TABLES:
        raise LatencyError(f"latency: the tables must be {', '.join(TABLES)}")
    for name, table in tables.items():
        if table["machine"] not in machines or table["plan"] not in plans:
            raise LatencyError(f"latency table {name}: unknown machine or plan")
    for name, plan in plans.items():
        _sizes(plan["texts"], f"latency plan {name}")
    backends = {t[BACKEND]: t for t in tables.values()}
    for run in data["nullpii"]["runs"]:
        _check_run(run, plans, backends)
    lat = Latency(data)
    for table in TABLES:
        if not lat.tools(table):
            raise LatencyError(f"latency table {table}: no other tool")
        for tool, values in lat.tools(table).items():
            for v in _sizes(values, f"latency {table} {tool}").values():
                _positive(v, f"latency {table} {tool}")
        for preset in settings.PRESETS:
            lat.nullpii(table, preset)
    return lat


def load(path: Path | None = None) -> Latency:
    """The published latency (`LATENCY`, or `path`), checked."""
    return check(json.loads((path or LATENCY).read_text(encoding="utf-8")))
