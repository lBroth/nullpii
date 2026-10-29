# SPDX-License-Identifier: Apache-2.0
"""The analyses the published numbers come from, and how each scorer is
called for them. `reproduce` checks this recipe against the published
run's own outputs; `score` applies it to a new run."""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from pipeline import capture, settings


@dataclass(frozen=True)
class R3Run:
    """One `char_metrics.py` report: its file name, its sets, its flags."""

    name: str
    datasets: tuple[str, ...]
    flags: tuple[str, ...] = ()
    excludes_openmed_no_output: bool = False


MASK_ALL = "--mask-all"


def _lodo_runs() -> tuple[R3Run, ...]:
    # The leave-one-dataset-out runs have no mask-all floor, as published.
    return tuple(
        R3Run(f"char-r3-lodo-{left_out}", tuple(s for s in settings.R3_GATED if s != left_out))
        for left_out in settings.R3_GATED
    )


R3_RUNS: tuple[R3Run, ...] = (
    R3Run("char-r3", settings.R3_GATED, (MASK_ALL,)),
    R3Run("char-r3-en", settings.R3_GATED, ("--language", "en", MASK_ALL)),
    R3Run("char-r3-reported", settings.R3_REPORTED, (MASK_ALL,)),
    R3Run("char-r3-bonferroni", settings.R3_GATED, (MASK_ALL, "--macro-ci-level", str(settings.bonferroni_level()))),
    *_lodo_runs(),
    R3Run("sens-cluster-rows", settings.R3_GATED, (MASK_ALL, "--cluster-rows")),
    R3Run("sens-openmed-excluded", settings.R3_GATED, (MASK_ALL,), excludes_openmed_no_output=True),
)


@dataclass(frozen=True)
class Verdict:
    """One `r2_verdict.py` report, from the R3 run it reads."""

    name: str
    report: str
    mode: str


BETTER_ROW = "--better-row"
TABLE_ONLY = "--table-only"
VERDICTS: tuple[Verdict, ...] = (
    Verdict("verdict", "char-r3", BETTER_ROW),
    Verdict("verdict-en", "char-r3-en", TABLE_ONLY),
    Verdict("verdict-reported", "char-r3-reported", TABLE_ONLY),
    Verdict("sens-cluster-rows-verdict", "sens-cluster-rows", BETTER_ROW),
    Verdict("sens-openmed-excluded-verdict", "sens-openmed-excluded", BETTER_ROW),
)


def _python(script: Path, *args: str) -> str:
    return capture.run([sys.executable, "-I", str(script), *args])


def score_ab1(checkpoints: Path, baseline: str, out_dir: Path) -> None:
    """The AB-1 scores of every tool with checkpoints, against `baseline`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, gold in settings.AB1_GOLD.items():
        _python(
            settings.AGENT_METRICS, "--gold", str(settings.RESULTS / "ab1" / gold), "--dataset", key,
            "--checkpoints", str(checkpoints), "--baseline", baseline, "--out", str(out_dir / f"scores-{key}.json"),
        )


def score_ab1_coverage(checkpoints: Path, recognizers: Path, out_dir: Path) -> None:
    """Each tool's leak rate on AB-1's secrets, split by whether nullpii's
    recognizer pack covers the item's format (`recognizers/<key>.jsonl`)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for key, gold in settings.AB1_GOLD.items():
        _python(
            settings.SECRET_COVERAGE, "--gold", str(settings.RESULTS / "ab1" / gold), "--dataset", key,
            "--recognizers", str(recognizers / f"{key}.jsonl"), "--checkpoints", str(checkpoints),
            "--out", str(out_dir / f"coverage-{key}.json"),
        )


def score_r3(results: Path, baseline: str, openmed_no_output: Path, out_dir: Path) -> None:
    """Every R3 report of the recipe, for the run whose `checkpoints/` is in
    `results`, against `baseline`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for r3 in R3_RUNS:
        args = ["--results", str(results), "--datasets", ",".join(r3.datasets), "--baseline", baseline, *r3.flags]
        if r3.excludes_openmed_no_output:
            args += ["--exclude", str(openmed_no_output)]
        _python(settings.CHAR_METRICS, *args, "--out", str(out_dir / f"{r3.name}.json"))


def verdicts(reports: Path, baseline: str, other_nullpii: tuple[str, ...]) -> dict[str, str]:
    """The text of every verdict of the recipe, read from `reports`."""
    out = {}
    for v in VERDICTS:
        out[v.name] = _python(
            settings.R2_VERDICT, "--report", str(reports / f"{v.report}.json"), "--baseline", baseline,
            "--not-competitors", ",".join(other_nullpii), v.mode,
        )
    return out


def score_piimb(sentences: Path, spans: Path, leaderboard: Path, name: str, out: Path) -> None:
    """PIIMB, scored with the leaderboard's method, against its rows."""
    out.parent.mkdir(parents=True, exist_ok=True)
    _python(
        settings.PIIMB_SCORE, "score", "--data", str(sentences), "--pred", str(spans),
        "--name", name, "--leaderboard", str(leaderboard), "--out", str(out),
    )
