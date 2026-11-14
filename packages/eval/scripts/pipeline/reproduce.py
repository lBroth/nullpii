# SPDX-License-Identifier: Apache-2.0
"""Score the published run again from its frozen predictions and check
that every output that can be scored from them is the published one:

- AB-1: the 3 score files and the kind split of B1's secrets, against
  the published run's own (the frozen copy's `published-0.5/ab1/`);
- R3: the 14 reports and 6 verdicts of the published run, against the
  run's own outputs (the recipe's 11 and 5, plus the 3 reports and the
  verdict on every category masked scored on core labels);
- PIIMB: nullpii's published spans (every category masked), against
  the published report (the frozen copy's `published-0.5/piimb/`).

It shows the scorers, the frozen inputs and the recipe still give the
published numbers, so a change in a new run comes from nullpii.

Not checked, because they come from running nullpii itself and no frozen
prediction holds them: AB-1's recognizer coverage (it needs the
recognizer pack's own spans) and the mask-restore round trip."""
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


def _compare_verdicts(texts: dict[str, str], published: Path) -> list[str]:
    return [
        f"{name}: the verdict text differs"
        for name, text in texts.items()
        if text.strip() != (published / f"{name}.log").read_text(encoding="utf-8").strip()
    ]


def ab1(frozen: Frozen, work: Path) -> list[str]:
    out, published = work / "ab1", frozen.published_outputs
    recipe.score_ab1(frozen.ab1_checkpoints, settings.PUBLISHED_AB1_BASELINE, frozen.dataset("ab1"), out)
    recipe.score_ab1_kind_split(frozen.ab1_checkpoints, frozen.dataset("ab1"), out)
    files = [f"scores-{key}.json" for key in settings.AB1_GOLD] + [f"kind-split-{k}.json" for k in settings.AB1_KIND_SPLITS]
    return [d for name in files for d in _compare_json(out / name, published / "ab1" / name)]


def _core_label_others() -> tuple[str, ...]:
    """The other nullpii rows of the core-label reports, in the published
    run's order: the headline row first, then the earlier ones."""
    rest = (n for n in settings.PUBLISHED_R3_OTHER_NULLPII if n != settings.PUBLISHED_R3_CORE_LABELS_BASELINE)
    return (settings.PUBLISHED_R3_BASELINE, *rest)


def declared_outputs() -> tuple[set[str], set[str]]:
    """The R3 reports and verdicts the recipe declares: those `score` writes
    and those of the core regime, which only `reproduce` writes."""
    reports = {r.name for r in (*recipe.R3_RUNS, *recipe.CORE_LABEL_RUNS)}
    verdicts = {v.name for v in (*recipe.VERDICTS, *recipe.CORE_LABEL_VERDICTS)}
    return reports, verdicts


def undeclared(published: Path) -> list[str]:
    """How the published run's R3 outputs differ from the declared set:
    each report is a `<name>.json` (with its `<name>.log`), each verdict a
    `<name>.log` alone. A published output the recipe does not declare, or
    one it declares that is not there, is a difference."""
    reports, verdicts = declared_outputs()
    jsons = {p.stem for p in published.glob("*.json")}
    logs = {p.stem for p in published.glob("*.log")} - jsons
    problems = [f"published report not in the recipe: {n}" for n in sorted(jsons - reports)]
    problems += [f"report of the recipe not published: {n}" for n in sorted(reports - jsons)]
    problems += [f"published verdict not in the recipe: {n}" for n in sorted(logs - verdicts)]
    problems += [f"verdict of the recipe not published: {n}" for n in sorted(verdicts - logs)]
    return problems


def r3(frozen: Frozen, work: Path) -> list[str]:
    missing = undeclared(frozen.r3_published)
    if missing:
        return missing
    out = work / "r3"
    groups = (
        (settings.PUBLISHED_R3_BASELINE, settings.PUBLISHED_R3_OTHER_NULLPII, recipe.R3_RUNS, recipe.VERDICTS),
        (settings.PUBLISHED_R3_CORE_LABELS_BASELINE, _core_label_others(),
         recipe.CORE_LABEL_RUNS, recipe.CORE_LABEL_VERDICTS),
    )
    diffs: list[str] = []
    for baseline, others, runs, verdicts in groups:
        recipe.score_r3(frozen.r3_run, baseline, frozen.openmed_no_output, out, runs)
        diffs += [d for run in runs for d in _compare_json(
            out / f"{run.name}.json", frozen.r3_published / f"{run.name}.json")]
        diffs += _compare_verdicts(recipe.verdicts(out, baseline, others, verdicts), frozen.r3_published)
    return diffs


def piimb(frozen: Frozen, work: Path) -> list[str]:
    published = frozen.published_outputs
    name = f"piimb-{settings.PIIMB_PUBLISHED_PRESET}.json"
    produced = work / "piimb" / name
    recipe.score_piimb(
        frozen.piimb_sentences, frozen.piimb_published_spans,
        frozen.piimb_leaderboard, settings.tool_name(settings.PIIMB_PUBLISHED_PRESET), produced,
    )
    return _compare_json(produced, published / "piimb" / name)


def check(frozen: Frozen, work: Path) -> None:
    """Raise listing every difference; return quietly when there is none."""
    diffs = ab1(frozen, work) + r3(frozen, work) + piimb(frozen, work)
    if diffs:
        raise AssertionError("the published run does not reproduce:\n  " + "\n  ".join(diffs))
