# SPDX-License-Identifier: Apache-2.0
"""Score the published run again from its frozen predictions and check
that every output is the published one: AB-1 against
`published-bench/ab1/`, R3 and its verdicts against the run's own outputs.

It shows the scorers, the frozen inputs and the recipe still give the
published numbers, so a change in a new run comes from nullpii."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline import jsoneq, recipe, settings
from pipeline.frozen import Frozen

MAX_SHOWN = 5


def _compare_json(produced: Path, published: Path) -> list[str]:
    diffs = jsoneq.differences(
        json.loads(produced.read_text(encoding="utf-8")),
        json.loads(published.read_text(encoding="utf-8")),
    )
    return [f"{produced.name}: {d}" for d in diffs[:MAX_SHOWN]] + (
        [f"{produced.name}: … {len(diffs) - MAX_SHOWN} more"] if len(diffs) > MAX_SHOWN else []
    )


def ab1(frozen: Frozen, work: Path) -> list[str]:
    out = work / "ab1"
    recipe.score_ab1(frozen.ab1_checkpoints, settings.PUBLISHED_AB1_BASELINE, out)
    return [d for key in settings.AB1_GOLD for d in _compare_json(
        out / f"scores-{key}.json", settings.PUBLISHED / "ab1" / f"scores-{key}.json")]


def r3(frozen: Frozen, work: Path) -> list[str]:
    out = work / "r3"
    recipe.score_r3(frozen.r3_run, settings.PUBLISHED_R3_BASELINE, frozen.openmed_no_output, out)
    diffs = [d for run in recipe.R3_RUNS for d in _compare_json(
        out / f"{run.name}.json", frozen.r3_published / f"{run.name}.json")]
    texts = recipe.verdicts(out, settings.PUBLISHED_R3_BASELINE, settings.PUBLISHED_R3_OTHER_NULLPII)
    for name, text in texts.items():
        published = (frozen.r3_published / f"{name}.log").read_text(encoding="utf-8")
        if text.strip() != published.strip():
            diffs.append(f"{name}: the verdict text differs")
    return diffs


def check(frozen: Frozen, work: Path) -> None:
    """Raise listing every difference; return quietly when there is none."""
    diffs = ab1(frozen, work) + r3(frozen, work)
    if diffs:
        raise AssertionError("the published run does not reproduce:\n  " + "\n  ".join(diffs))
