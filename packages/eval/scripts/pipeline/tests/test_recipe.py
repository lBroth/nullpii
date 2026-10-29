# SPDX-License-Identifier: Apache-2.0
"""The recipe is the published run's: the same reports with the same
flags (checked against its outputs by `reproduce`; pinned here)."""
from pipeline import recipe, settings

PUBLISHED_REPORTS = {
    "char-r3", "char-r3-en", "char-r3-reported", "char-r3-bonferroni",
    "char-r3-lodo-r3-redact", "char-r3-lodo-r3-tonic-human", "char-r3-lodo-r3-piilo",
    "char-r3-lodo-r3-eu-clinical", "char-r3-lodo-r3-traces-v3",
    "sens-cluster-rows", "sens-openmed-excluded",
}


def test_the_reports_are_the_published_ones():
    names = [r.name for r in recipe.R3_RUNS]
    assert len(names) == len(set(names))
    assert set(names) == PUBLISHED_REPORTS


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
