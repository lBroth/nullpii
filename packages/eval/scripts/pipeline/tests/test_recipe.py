# SPDX-License-Identifier: Apache-2.0
"""The recipe is the published run's: its 14 reports and 6 verdicts with
the same flags, `score`'s 11 and 5 plus the 3 reports and the verdict on
every category masked scored on core labels, which only `reproduce`
writes (checked against the run's outputs by `reproduce`; pinned here)."""
from pathlib import Path

from pipeline import capture, recipe, settings

PUBLISHED_REPORTS = {
    "char-r3", "char-r3-en", "char-r3-reported", "char-r3-bonferroni",
    "char-r3-lodo-r3-redact", "char-r3-lodo-r3-tonic-human", "char-r3-lodo-r3-piilo",
    "char-r3-lodo-r3-eu-clinical", "char-r3-lodo-r3-traces-v3",
    "sens-cluster-rows", "sens-openmed-excluded",
}


PUBLISHED_CORE_LABEL_REPORTS = {"char-r3-defcore", "char-r3-bonferroni-defcore", "sens-default-core"}
PUBLISHED_VERDICTS = {
    "verdict", "verdict-en", "verdict-reported", "sens-cluster-rows-verdict", "sens-openmed-excluded-verdict",
}
PUBLISHED_CORE_LABEL_VERDICTS = {"sens-default-core-verdict"}


def test_the_reports_are_the_published_ones():
    names = [r.name for r in recipe.R3_RUNS]
    assert len(names) == len(set(names))
    assert set(names) == PUBLISHED_REPORTS
    assert {r.name for r in recipe.CORE_LABEL_RUNS} == PUBLISHED_CORE_LABEL_REPORTS
    assert len(PUBLISHED_REPORTS | PUBLISHED_CORE_LABEL_REPORTS) == 14


def test_the_verdicts_are_the_published_ones():
    assert {v.name for v in recipe.VERDICTS} == PUBLISHED_VERDICTS
    assert {v.name for v in recipe.CORE_LABEL_VERDICTS} == PUBLISHED_CORE_LABEL_VERDICTS
    assert len(PUBLISHED_VERDICTS | PUBLISHED_CORE_LABEL_VERDICTS) == 6
    core_reports = {r.name for r in recipe.CORE_LABEL_RUNS}
    assert all(v.report in core_reports for v in recipe.CORE_LABEL_VERDICTS)


def test_each_leave_one_out_report_drops_its_set_and_has_no_mask_all_floor():
    lodo = [r for r in recipe.R3_RUNS if r.name.startswith("char-r3-lodo-")]
    assert len(lodo) == len(settings.R3_GATED)
    for r in lodo:
        left_out = r.name.removeprefix("char-r3-lodo-")
        assert set(r.datasets) == set(settings.R3_GATED) - {left_out}
        assert recipe.MASK_ALL not in r.flags


def test_the_bonferroni_level_is_the_published_one():
    assert settings.bonferroni_level() == 99.6667
    bonferroni = next(r for r in recipe.R3_RUNS if r.name == "char-r3-bonferroni")
    assert "99.6667" in bonferroni.flags


def test_only_the_openmed_check_excludes_documents():
    assert [r.name for r in recipe.R3_RUNS if r.excludes_openmed_no_output] == ["sens-openmed-excluded"]


def test_every_verdict_reads_a_report_of_the_recipe():
    names = {r.name for r in recipe.R3_RUNS}
    for v in recipe.VERDICTS:
        assert v.report in names
        assert v.mode in (recipe.BETTER_ROW, recipe.TABLE_ONLY)
    # The English verdict is the table alone, as published.
    assert next(v for v in recipe.VERDICTS if v.name == "verdict-en").mode == recipe.TABLE_ONLY


def _recorded(monkeypatch) -> list[list[str]]:
    calls: list[list[str]] = []

    def record(args, cwd=settings.EVAL):
        calls.append([str(a) for a in args])
        return ""
    monkeypatch.setattr(capture, "run", record)
    return calls


def test_the_verdicts_leave_out_the_other_nullpii_rows(monkeypatch):
    calls = _recorded(monkeypatch)
    recipe.verdicts(Path("reports"), settings.BASELINE, settings.OTHER_NULLPII)
    assert len(calls) == len(recipe.VERDICTS)
    for call in calls:
        assert call[call.index("--baseline") + 1] == settings.BASELINE
        assert call[call.index("--not-competitors") + 1].split(",") == list(settings.OTHER_NULLPII)
    assert settings.OTHER_NULLPII == (settings.tool_name("everything"),)


def test_only_the_openmed_check_is_given_the_texts_to_exclude(monkeypatch):
    calls = _recorded(monkeypatch)
    excluded = Path("openmed-union.json")
    recipe.score_r3(Path("run"), settings.BASELINE, excluded, Path("out"))
    given = {Path(c[c.index("--out") + 1]).stem: c[c.index("--exclude") + 1] if "--exclude" in c else None
             for c in calls}
    assert given == {r.name: (str(excluded) if r.excludes_openmed_no_output else None) for r in recipe.R3_RUNS}
    assert given["sens-openmed-excluded"] == str(excluded)
