# SPDX-License-Identifier: Apache-2.0
"""The claims the review found could read false: each is worded from the
data, compared as printed, or refused. Ties, edges and the order of an
interval are pinned here."""
import pytest

from pipeline import blocks_ab1, blocks_r3, compare, settings, views
from pipeline.prose import RenderError
from pipeline.tests import render_outputs as ro
from pipeline.tests.outputs import DEFAULT

import readme_figures

A, B1, B2, R3, R3_EN = ro.A, ro.B1, ro.B2, ro.R3, ro.R3_EN
SPLIT = compare.ab1_file(compare.KIND_SPLIT, "ab1-b1")
LODO = compare.r3_file("char-r3-lodo-r3-piilo")
SENS = compare.r3_file("sens-cluster-rows")


def _bench(tmp_path, edit=None, measured=None):
    return views.load(ro.write_run(tmp_path / "run", edit, measured=measured))


# AB-1: compared as printed ------------------------------------------------------------

def test_a_leak_rate_tied_with_nullpiis_as_printed_is_refused(tmp_path):
    # 9.44% and 9.45% both print 9.4%: "only rizzo-pii lets fewer through (9.4%)" would sit next to nullpii's 9.4%.
    with pytest.raises(RenderError, match="tied with nullpii's as printed"):
        blocks_ab1.readme_bullets(_bench(tmp_path, lambda f: f[A][ro.RIZZO].update(leak_rate=0.0944)))


def test_a_gap_under_half_a_point_is_given_to_a_tenth(tmp_path):
    def close(f):
        f[A][DEFAULT].update(leak_rate=0.05)
        f[A][ro.RIZZO].update(leak_rate=0.053)
    text = blocks_ab1.lead_bullet(blocks_ab1.standing(_bench(tmp_path, close), "ab1-a"))
    assert "Every other tool lets 0.3 to 35.6 points more through." in text
    assert " 0 points" not in text and "0 to " not in text


def test_whole_points_when_no_gap_rounds_to_zero(tmp_path):
    text = blocks_ab1.lead_bullet(blocks_ab1.standing(_bench(tmp_path, lambda f: f[A][DEFAULT].update(leak_rate=0.05)),
                                                      "ab1-a"))
    assert "Every other tool lets 3 to 36 points more through." in text


def _b1(tmp_path, keep):
    def edit(f):
        f[B1][DEFAULT].update(leak_rate=0.5, keep_rate=0.85)
        f[B1][ro.RIZZO].update(keep_rate=keep)
    return blocks_ab1._b1_clause(blocks_ab1.standing(_bench(tmp_path, edit), "ab1-b1"))


def test_a_credata_tool_that_keeps_more_readable_is_named_and_one_that_keeps_less_is_not(tmp_path):
    assert "; rizzo-pii lets 8.1% through and keeps more readable (90.0% against 85.0%)." in _b1(tmp_path / "a", 0.9)
    assert _b1(tmp_path / "b", 0.7).endswith("; none of them keeps as much readable.")


def test_a_credata_keep_rate_tied_as_printed_is_refused(tmp_path):
    with pytest.raises(RenderError, match="CredData keep rate tied"):
        _b1(tmp_path, 0.8504)


def _split(tmp_path, leaked, leaked_other):
    def edit(f):
        f[SPLIT]["tools"][DEFAULT].update(leaked=leaked, leaked_other=leaked_other)
    return blocks_ab1.uuid_split(_bench(tmp_path, edit))


def test_exactly_half_of_the_leaks_is_not_more_than_half(tmp_path):
    assert _split(tmp_path / "a", 100, 100).startswith("100 of nullpii's 200 leaks there are UUIDs")
    assert _split(tmp_path / "b", 101, 100).startswith("More than half of nullpii's leaks there (101 of 201) are UUIDs")


def test_no_uuid_leak_is_said_so_and_no_leak_at_all_is_refused(tmp_path):
    assert _split(tmp_path / "a", 0, 50).startswith("None of nullpii's 50 leaks there is a UUID")
    assert "none of it UUIDs" in blocks_ab1.uuid_aside(_bench(tmp_path / "b", lambda f: f[SPLIT]["tools"][DEFAULT]
                                                               .update(leaked=0, leaked_other=50)))
    with pytest.raises(RenderError, match="nothing to split"):
        _split(tmp_path / "c", 0, 0)


def test_the_weakest_categories_refuse_a_tie_and_fewer_than_two(tmp_path):
    def tie(f):
        f[A][DEFAULT]["leak_by_category"]["email"] = [0.235, 536]
    with pytest.raises(RenderError, match="a tie for the last place named"):
        blocks_ab1.weakest(_bench(tmp_path / "a", tie))

    def one(f):
        f[A][DEFAULT]["leak_by_category"] = {"person": [0.2, 969]}
    with pytest.raises(RenderError, match="fewer than 2 categories"):
        blocks_ab1.weakest_bullet(_bench(tmp_path / "b", one))


def test_the_cards_weak_spots_say_when_credata_alone_is_why_nullpii_does_not_lead(tmp_path):
    def edit(f):
        f[B1][DEFAULT].update(leak_rate=0.5)
        f[B2][DEFAULT].update(leak_rate=0.01)
    text = blocks_ab1.card_weak_bullet(_bench(tmp_path, edit))
    assert "nullpii does not lead: no other tool lets fewer GitHub-issue secrets through (1.0%)" in text
    assert "and 2 of the 2 other tools let fewer through there." in text


# R3 ---------------------------------------------------------------------------------------

def test_a_tie_with_nullpii_as_printed_on_a_leave_one_out_report_is_refused(tmp_path):
    with pytest.raises(RenderError, match="tied with nullpii as printed"):
        blocks_r3.lodo_table(_bench(tmp_path, lambda f: f[LODO]["_macro"]["rizzo-pii@default"].update(f2=0.7584)))


def test_a_tool_just_below_nullpii_is_the_closest_behind_with_its_interval_in_order(tmp_path):
    def edit(f):
        row = f[LODO]["_macro"]["rizzo-pii@default"]
        row.update(f2=0.75, baseline_minus_tool_f2_ci=[0.002, 0.03])
    table = blocks_r3.lodo_table(_bench(tmp_path, edit))
    piilo = next(line for line in table.splitlines() if line.startswith("| PIILO |"))
    # nullpii minus the tool is [+0.002, +0.030]; the table gives the tool minus nullpii, low end first.
    assert piilo == "| PIILO | 0.758 | none | rizzo-pii at its default −0.008 [−0.030, −0.002] |"


def test_a_tool_ahead_on_a_leave_one_out_report_has_its_interval_in_order(tmp_path):
    table = blocks_r3.lodo_table(_bench(tmp_path))
    piilo = next(line for line in table.splitlines() if line.startswith("| PIILO |"))
    assert "rizzo-pii at its default +0.012 [+0.003, +0.020]" in piilo


def test_a_sensitivity_check_that_flips_a_sign_names_the_tool(tmp_path):
    def flip(f):
        f[SENS]["_macro"]["rizzo-pii@default"]["baseline_minus_tool_f2_ci"] = [-0.01, 0.02]
    assert "conclusions unchanged" in blocks_r3.sensitivity(_bench(tmp_path / "a"))
    text = blocks_r3.sensitivity(_bench(tmp_path / "b", flip))
    assert "every set resampled by its recorded clusters: the interval's sign changes against rizzo-pii at its default." in text


def test_a_sign_flip_in_the_gated_table_alone_is_a_change_too(tmp_path):
    # The check is compared with the gated table, never with itself.
    def flip(f):
        f[R3]["_macro"]["rizzo-pii@default"]["baseline_minus_tool_f2_ci"] = [-0.01, 0.02]
    text = blocks_r3.sensitivity(_bench(tmp_path, flip))
    assert text.count("the interval's sign changes against rizzo-pii at its default") == 2


def test_a_sensitivity_check_of_other_tools_is_refused(tmp_path):
    def other(f):
        for rows in f[SENS].values():
            rows["presidio"] = dict(rows["rizzo-pii"])
    with pytest.raises(RenderError, match="other tools than the gated table"):
        blocks_r3.sensitivity(_bench(tmp_path, other))


def test_equal_recall_and_precision_ranks_favour_neither(tmp_path):
    def same(f):
        for d, rows in f[R3].items():
            if d != "_macro":
                rows[DEFAULT].update(recall=0.95, precision=0.59)
    text = blocks_r3.recall_bullet(_bench(tmp_path, same))
    assert text.startswith("- **Recall and precision.**")
    assert blocks_r3.recall_bullet(_bench(tmp_path / "b")).startswith("- **It favours recall.**")


def test_a_chart_row_with_no_english_row_is_refused(tmp_path):
    def drop(f):
        for rows in f[R3_EN].values():
            rows.pop("rizzo-pii@default", None)
            rows.pop("rizzo-pii", None)
    with pytest.raises(RenderError, match="no row in the English report"):
        blocks_r3.chart_rows(_bench(tmp_path, drop))


def test_the_training_overlap_is_stated_only_for_the_weights_it_was_measured_on(tmp_path):
    assert blocks_r3.TRAINING_OVERLAP in blocks_r3.detail(_bench(tmp_path / "a"))
    other = {**ro.RUN_MEASURED, "model": "lBroth/nullpii@" + "9" * 40}
    with pytest.raises(RenderError, match="measure it for this model"):
        blocks_r3.piimb_method(_bench(tmp_path / "b", measured=other))


def test_the_card_names_the_first_tool_without_nested_brackets(tmp_path):
    text = blocks_r3.card_documents(_bench(tmp_path))
    assert "; the first is rizzo-pii at its default, 0.770)" in text and "(0.770))" not in text


# The R3 chart's axis ---------------------------------------------------------------------------

@pytest.mark.parametrize("values, axis", [
    ([0.45, 0.79], (0.40, 0.80, 8)),
    ([0.40, 0.80], (0.40, 0.80, 8)),
    ([0.31, 0.83], (0.30, 0.85, 11)),
    ([0.5, 0.95], (0.40, 0.95, 11)),
])
def test_the_r3_axis_widens_by_whole_steps_only_when_a_value_falls_outside(values, axis):
    lo, hi, steps = readme_figures.r3_axis(values)
    assert (round(lo, 2), round(hi, 2), steps) == axis


def test_a_score_above_the_published_axis_draws(tmp_path):
    svg = readme_figures.r3_chart([("a", 0.83, 0.81, True), ("b", 0.5, 0.45, False)], 0.26)
    assert ">0.85</text>" in svg and ">0.80</text>" in svg


def test_the_published_chart_keeps_its_axis():
    from pipeline import docs, render
    b = views.load(settings.PUBLISHED)
    assert render.figures(b)["r3-documents.svg"] == (views.ROOT / docs.FIGURES / "r3-documents.svg").read_text()


def test_up_to_three_tools_of_a_sign_are_named_and_more_are_counted():
    def row(name):
        return views.Row(key=name, label=name, macro={}, sets={})
    three = {compare.AHEAD: [row("a"), row("b"), row("c")], compare.CLOSE: [], compare.BEHIND: [row(str(i)) for i in range(4)]}
    text = blocks_r3._sign_counts(three)
    assert text == "significantly ahead of 3 (a, b and c), too close to call with 0 and significantly behind 4"
