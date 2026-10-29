# SPDX-License-Identifier: Apache-2.0
"""A change is judged at the printed precision, in the metric's own
direction, and so is every derived claim; only like is compared with like
(the published core regime is dropped, never better or worse); outputs
that lack something, or hold an undeclared nullpii row, are an error,
never "nothing moved"."""
import re

import pytest

from pipeline import compare, settings
from pipeline.tests import outputs
from pipeline.tests.outputs import DEFAULT, EVERYTHING, against, run

A = "ab1/scores-ab1-a.json"
R3 = "r3/char-r3.json"


def _verdicts(changes):
    return {c.where: c.verdict for c in changes if c.verdict != compare.SAME}


def test_a_run_compared_with_itself_moved_nothing(tmp_path):
    a = run(tmp_path, "a")
    changes = compare.compare(a, a)
    assert _verdicts(changes) == {}
    assert compare.exit_code(changes) == compare.EXIT_UNCHANGED


def test_the_report_counts_every_number_and_claim_both_sides_have(tmp_path):
    a = run(tmp_path, "a")
    changes = compare.compare(a, a)
    numbers = sum(1 for c in changes if c.kind == compare.NUMBER)
    claims = sum(1 for c in changes if c.kind == compare.CLAIM)
    verdicts = sum(1 for c in changes if c.kind == compare.VERDICT)
    assert claims > 0 and verdicts == len(compare.recipe.VERDICTS)
    text = compare.report(changes)
    assert text.splitlines()[0] == (f"**nothing moved** (of {numbers} numbers, {claims} claims and {verdicts} verdicts"
                                    " both sides have, like for like).")
    # What is not compared is said, with why.
    assert all(f"- {what}: {why}." in text for what, why in compare.NOT_COMPARED)


def test_a_new_entry_is_not_counted_as_compared(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f[A].__setitem__("gliner", against()))
    head = compare.report(compare.compare(after, before)).splitlines()[0]
    same = compare.report(compare.compare(before, before)).splitlines()[0]
    # Its two claims and their four bounds.
    assert head.startswith("**6 new**")
    assert re.search(r"\(of .*\)", head).group() == re.search(r"\(of .*\)", same).group()


def test_a_change_below_the_printed_digit_is_no_change(tmp_path):
    # Both print as 9.5%.
    before = run(tmp_path, "before", lambda f: f[A][DEFAULT].update(leak_rate=0.09451))
    after = run(tmp_path, "after", lambda f: f[A][DEFAULT].update(leak_rate=0.09459))
    assert _verdicts(compare.compare(after, before)) == {}
    # Across the printed digit it is a change, however small.
    across = run(tmp_path, "across", lambda f: f[A][DEFAULT].update(leak_rate=0.09449))
    assert _verdicts(compare.compare(across, before)) == {f"AB-1 ab1-a · {DEFAULT} · leak_rate": compare.BETTER}


def test_a_lower_leak_is_better_and_a_lower_keep_is_worse(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f[A][DEFAULT].update(leak_rate=0.085, keep_rate=0.84))
    changes = compare.compare(after, before)
    verdicts = _verdicts(changes)
    assert verdicts[f"AB-1 ab1-a · {DEFAULT} · leak_rate"] == compare.BETTER
    assert verdicts[f"AB-1 ab1-a · {DEFAULT} · keep_rate"] == compare.WORSE
    assert compare.exit_code(changes) == compare.EXIT_WORSE


def test_a_rate_a_set_has_no_item_for_is_not_compared(tmp_path):
    o = compare.load(run(tmp_path, "a"), compare.RUN)
    assert not any("encoded_leak_rate" in k for k in compare.ab1_metrics(o))


def test_the_recognizer_coverage_counts_and_every_tools_cells_are_compared(tmp_path):
    def covers_ten_more(f):
        cov = f["ab1/coverage-ab1-b2.json"]
        cov["covered"], cov["uncovered"] = cov["covered"] + 10, cov["uncovered"] - 10
        cov["tools"]["presidio"]["leak_covered"] = 0.2
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", covers_ten_more)
    changes = compare.compare(after, before)
    assert _verdicts(changes) == {
        "AB-1 ab1-b2 · secrets covered by nullpii's recognizer pack": compare.MOVED,
        "AB-1 ab1-b2 · secrets uncovered by nullpii's recognizer pack": compare.MOVED,
        "AB-1 ab1-b2 · presidio · leak_covered": compare.MOVED,
    }
    assert compare.exit_code(changes) == compare.EXIT_CHANGED


def test_one_more_masked_document_in_the_round_trip_is_a_move(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f[compare.ROUNDTRIP_FILE].update(masked=13705))
    assert _verdicts(compare.compare(after, before)) == {"AB-1 · round trip · masked": compare.MOVED}
    failing = run(tmp_path, "failing", lambda f: f[compare.ROUNDTRIP_FILE].update(roundtrip_failures=1))
    assert _verdicts(compare.compare(failing, before)) == {"AB-1 · round trip · roundtrip_failures": compare.WORSE}


def test_a_macro_recall_that_crosses_its_digit_is_seen_though_no_set_recall_does(tmp_path):
    # Each per-set recall keeps its three decimals; their mean goes from
    # 0.9577 (0.958) to 0.9573 (0.957).
    lower = (0.97456, 0.98659, 0.96446, 0.96056, 0.90053)

    def drop(f):
        for dataset, recall in zip(settings.R3_GATED, lower):
            f[R3][dataset][DEFAULT]["recall"] = recall
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", drop)
    assert _verdicts(compare.compare(after, before)) == {f"R3 char-r3 · _macro · {DEFAULT} · recall": compare.WORSE}


def test_the_leave_one_out_range_and_reports_and_ranks_are_compared(tmp_path):
    lodo = "r3/char-r3-lodo-r3-eu-clinical.json"

    def change(f):
        f[R3]["_macro"][DEFAULT]["f2_lodo"] = [0.724, 0.845]
        f[lodo]["_macro"][DEFAULT]["f2"] = 0.79
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", change)
    assert _verdicts(compare.compare(after, before)) == {
        f"R3 char-r3 · _macro · {DEFAULT} · leave-one-out low": compare.WORSE,
        f"R3 char-r3-lodo-r3-eu-clinical · _macro · {DEFAULT} · f2": compare.BETTER,
        f"R3 char-r3-lodo-r3-eu-clinical · {DEFAULT} · rank by f2 of 2": compare.BETTER,
    }


def test_the_piimb_place_is_compared(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f["piimb/piimb-everything.json"]["leaderboard"].update(rank=2))
    assert _verdicts(compare.compare(after, before)) == {f"PIIMB · {EVERYTHING} · rank of 36": compare.WORSE}


def _published(tmp_path, edit=None):
    return outputs.write(tmp_path / "published", outputs.published(), edit)


def test_published_rows_are_compared_like_for_like_only(tmp_path):
    changes = compare.compare(run(tmp_path, "after"), _published(tmp_path), compare.PUBLISHED)
    by = {c.where: c for c in changes}
    # AB-1: the 0.5 agent default is `default`, so its numbers and its
    # intervals are compared; `everything` was never published there.
    assert by[f"AB-1 ab1-a · {DEFAULT} · leak_rate"].verdict == compare.SAME
    assert by[f"AB-1 ab1-a · {DEFAULT} against presidio (leak)"].verdict == compare.SAME
    assert by[f"AB-1 ab1-a · {EVERYTHING} · leak_rate"].verdict == compare.NEW
    # R3: every category masked is `everything`, compared like for like.
    assert by[f"R3 char-r3 · _macro · {EVERYTHING} · f2"].verdict == compare.SAME
    assert by[f"R3 char-r3 · r3-piilo · {EVERYTHING} · f2"].verdict == compare.SAME
    # The core regime is dropped: its rows, the intervals and verdicts
    # against it, and its own reports; never compared with `default`.
    core = settings.PUBLISHED_R3_BASELINE
    assert by[f"R3 char-r3 · _macro · {core} · f2"].verdict == compare.DROPPED
    assert by[f"R3 char-r3 · {core} against rizzo-pii (F2)"].verdict == compare.DROPPED
    assert by[f"R3 char-r3 · {core} against rizzo-pii (F2) interval low"].verdict == compare.DROPPED
    assert by[f"R3 verdict · verdict against {core}"].verdict == compare.DROPPED
    for rel in compare.published_dropped_files():
        assert by[rel].verdict == compare.DROPPED and by[rel].kind == compare.REPORT
    # The run's `default` on R3, its intervals and verdicts, are new.
    assert by[f"R3 char-r3 · _macro · {DEFAULT} · f2"].verdict == compare.NEW
    assert by[f"R3 char-r3 · {DEFAULT} against rizzo-pii (F2)"].verdict == compare.NEW
    assert by[f"R3 verdict · verdict against {DEFAULT}"].verdict == compare.NEW
    # Nothing of the core regime is judged against anything measured now,
    # and no row the docs never print shows up at all.
    judged = [c for c in changes if c.verdict in (compare.SAME, compare.BETTER, compare.WORSE, compare.MOVED)]
    assert not any(core in c.where or settings.PUBLISHED_R3_CORE_LABELS_BASELINE in c.where for c in judged)
    assert not any(n in c.where for c in changes for n in settings.PUBLISHED_UNPRINTED)
    assert {c.verdict for c in changes if core in c.where} == {compare.DROPPED}
    # A declared drop was the owner's decision: it needs no approval.
    assert compare.exit_code(changes) == compare.EXIT_CHANGED


def test_a_published_number_of_everything_that_dropped_is_worse(tmp_path):
    after = run(tmp_path, "after", lambda f: f[R3]["r3-piilo"][EVERYTHING].update(f2=0.6))
    changes = compare.compare(after, _published(tmp_path), compare.PUBLISHED)
    assert next(c for c in changes if c.where == f"R3 char-r3 · r3-piilo · {EVERYTHING} · f2").verdict == compare.WORSE
    assert compare.exit_code(changes) == compare.EXIT_WORSE


def test_the_published_piimb_report_is_judged(tmp_path):
    # PIIMB was published with every category masked: a drop is worse.
    after = run(tmp_path, "after", lambda f: f["piimb/piimb-everything.json"]["without"].update(avg_f2=0.82))
    changes = compare.compare(after, _published(tmp_path), compare.PUBLISHED)
    verdicts = {c.where: c.verdict for c in changes}
    assert verdicts[f"PIIMB · {EVERYTHING} · without nemotron-pii · average F2"] == compare.WORSE
    assert verdicts[f"PIIMB · {DEFAULT} · average F2"] == compare.NEW


def test_the_published_layout_may_lack_only_the_default_piimb_report(tmp_path):
    after = run(tmp_path, "after")
    published = _published(tmp_path)
    with pytest.raises(compare.CompareError, match="piimb/piimb-default.json"):
        compare.compare(after, published)
    for rel in (compare.ROUNDTRIP_FILE, "piimb/piimb-everything.json", "r3/verdict-en.txt",
                *compare.published_dropped_files()):
        lacking = outputs.write(tmp_path / f"lacks-{rel.replace('/', '-')}", outputs.published(), lambda f: f.pop(rel))
        with pytest.raises(compare.CompareError, match=re.escape(rel)):
            compare.compare(after, lacking, compare.PUBLISHED)


def test_a_core_regime_row_is_refused_where_it_is_not_declared_dropped(tmp_path):
    # The same files with the aliases but nothing declared dropped.
    layout = compare.Layout(aliases=dict(settings.PUBLISHED_ALIASES), unprinted=settings.PUBLISHED_UNPRINTED,
                            may_lack=settings.PUBLISHED_ABSENT, every_preset=False)
    with pytest.raises(compare.CompareError, match=f"neither measured now nor declared: {settings.PUBLISHED_R3_BASELINE}"):
        compare.compare(run(tmp_path, "after"), _published(tmp_path), layout)


@pytest.mark.parametrize("rel", [A, "ab1/coverage-ab1-b1.json", R3, "r3/sens-openmed-excluded.json",
                                 "piimb/piimb-everything.json"])
def test_a_run_without_one_of_its_outputs_is_refused(tmp_path, rel):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f.pop(rel))
    with pytest.raises(compare.CompareError, match=re.escape(rel)):
        compare.compare(after, before)


def test_folders_that_do_not_exist_are_refused(tmp_path):
    with pytest.raises(compare.CompareError, match="is not a directory"):
        compare.compare(tmp_path / "nothing", tmp_path / "nothing")
    with pytest.raises(compare.CompareError, match="is not a directory"):
        compare.compare(tmp_path / "nothing", run(tmp_path, "a"))
    (tmp_path / "empty").mkdir()
    with pytest.raises(compare.CompareError, match="missing"):
        compare.compare(tmp_path / "empty", run(tmp_path, "b"))


def test_a_table_without_a_presets_row_is_refused(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f[R3]["r3-piilo"].pop(EVERYTHING))
    with pytest.raises(compare.CompareError, match=f"r3/char-r3.json r3-piilo: no row {EVERYTHING}"):
        compare.compare(after, before)


def test_an_undeclared_nullpii_row_is_refused(tmp_path):
    reference = outputs.write(tmp_path / "ref", outputs.files(), lambda f: f[A].__setitem__("nullpii-old", against()))
    with pytest.raises(compare.CompareError, match="ab1/scores-ab1-a.json: nullpii rows neither .* nullpii-old"):
        compare.compare(run(tmp_path, "after"), reference)


def test_a_reference_with_no_nullpii_row_under_a_current_name_is_refused(tmp_path):
    def only_dropped(f):
        f[A]["nullpii-core"] = f[A].pop(DEFAULT)
        f[A].pop(EVERYTHING)
    reference = outputs.write(tmp_path / "ref", outputs.files(), only_dropped)
    layout = compare.Layout(dropped=frozenset({"nullpii-core"}), every_preset=False)
    with pytest.raises(compare.CompareError, match="ab1/scores-ab1-a.json: no nullpii row under a current name"):
        compare.compare(run(tmp_path, "after"), reference, layout)


def test_a_lead_that_becomes_too_close_to_call_is_worse(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f[A]["presidio"]["ci"].update(baseline_minus_tool_leak=[-0.05, 0.01]))
    where = f"AB-1 ab1-a · {DEFAULT} against presidio (leak)"
    # The bounds as printed, in points: −30.0 → −5.0, −20.0 → +1.0.
    assert _verdicts(compare.compare(after, before)) == {
        where: compare.WORSE, f"{where} interval low": compare.WORSE, f"{where} interval high": compare.WORSE}


def test_a_gap_that_closes_on_r3_is_better(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after",
                lambda f: f[R3]["_macro"]["rizzo-pii@default"].update(baseline_minus_tool_f2_ci=[-0.01, 0.004]))
    where = f"R3 char-r3 · {DEFAULT} against rizzo-pii@default (F2)"
    assert _verdicts(compare.compare(after, before)) == {
        where: compare.BETTER, f"{where} interval low": compare.BETTER, f"{where} interval high": compare.BETTER}


def test_the_rank_counts_each_tool_once_at_its_better_row(tmp_path):
    out = run(tmp_path, "a")
    ranks = compare.r3_ranks(compare.load(out, compare.RUN))
    # rizzo-pii's better row (0.77) is ahead; mask-all is not a tool.
    assert ranks[f"R3 char-r3 · {DEFAULT} · rank by f2 of 2"].shown == 2
    after = run(tmp_path, "b", lambda f: f[R3]["_macro"][DEFAULT].update(f2=0.78))
    verdicts = _verdicts(compare.compare(after, out))
    assert verdicts[f"R3 char-r3 · {DEFAULT} · rank by f2 of 2"] == compare.BETTER


def _ab1_tools(leak: float):
    """AB-1 A with two other tools' README rows (tuned, `+agent`), and rows
    of theirs that are not in the README, which never count."""
    def edit(f):
        scores = f[A]
        scores[DEFAULT].update(leak_rate=leak)
        scores["rizzo-pii+agent"] = against(leak=0.095, keep=0.445)
        scores["rizzo-pii"] = against(leak=0.01, keep=0.99)
        scores["rizzo-pii@default+agent"] = against(leak=0.01, keep=0.99)
        scores["openai-privacy-filter+agent"] = against(leak=0.145, keep=0.9)
        scores["openai-privacy-filter+agent"]["leak_by_category"] = {}
    return edit


def test_the_ab1_rank_is_among_each_tools_readme_row(tmp_path):
    ranks = compare.ab1_ranks(compare.load(run(tmp_path, "a", _ab1_tools(0.0951)), compare.RUN))
    assert ranks[f"AB-1 ab1-a · {DEFAULT} · rank by leak_rate of 3"].shown == 2
    assert ranks[f"AB-1 ab1-a · {DEFAULT} · rank by keep_rate of 3"].shown == 2
    # openai's row has no email item, so only rizzo-pii is ranked with it.
    assert ranks[f"AB-1 ab1-a · {DEFAULT} · rank by leak_by_category email of 2"].shown == 1


def test_a_tool_passed_below_the_printed_digit_moves_the_ab1_rank(tmp_path):
    # 9.51% and 9.49% both print 9.5%, but rizzo-pii's 9.50% is now behind.
    before = run(tmp_path, "before", _ab1_tools(0.0951))
    after = run(tmp_path, "after", _ab1_tools(0.0949))
    assert _verdicts(compare.compare(after, before)) == {
        f"AB-1 ab1-a · {DEFAULT} · rank by leak_rate of 3": compare.BETTER}


def test_a_number_the_run_no_longer_gives_needs_approval(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f[A][DEFAULT]["leak_by_category"].pop("email"))
    changes = compare.compare(after, before)
    assert _verdicts(changes) == {
        f"AB-1 ab1-a · {DEFAULT} · leak_by_category email": compare.GONE,
        f"AB-1 ab1-a · {DEFAULT} · rank by leak_by_category email of 1": compare.GONE,
    }
    assert compare.exit_code(changes) == compare.EXIT_WORSE


def test_a_claim_the_run_no_longer_gives_needs_approval(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f[A].pop("presidio"))
    changes = compare.compare(after, before)
    gone = {c.where for c in changes if c.verdict == compare.GONE and c.kind == compare.CLAIM}
    assert gone == {f"AB-1 ab1-a · {DEFAULT} against presidio (leak)", f"AB-1 ab1-a · {DEFAULT} against presidio (keep)"}
    assert compare.exit_code(changes) == compare.EXIT_WORSE


def test_the_report_puts_worse_changes_first(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f[A][DEFAULT].update(leak_rate=0.085, keep_rate=0.84))
    text = compare.report(compare.compare(after, before))
    assert text.startswith("**1 worse, 1 better**")
    rows = [line for line in text.splitlines() if line.startswith("| AB-1")]
    assert rows[0].endswith("| worse |")


def test_what_needs_approval_comes_first_in_the_report(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: (f[A][DEFAULT].update(keep_rate=0.9),
                                              f[A][DEFAULT]["leak_by_category"].pop("email")))
    rows = [line for line in compare.report(compare.compare(after, before)).splitlines() if line.startswith("| AB-1")]
    assert rows[0].endswith(f"| {compare.GONE} |")


def test_a_changed_verdict_text_is_a_move(tmp_path):
    before = run(tmp_path, "before")
    after = run(tmp_path, "after", lambda f: f.__setitem__("r3/verdict-en.txt", "another verdict\n"))
    changes = compare.compare(after, before)
    assert _verdicts(changes) == {f"R3 verdict-en · verdict against {DEFAULT}": compare.MOVED}
    assert compare.exit_code(changes) == compare.EXIT_CHANGED


def test_the_matrix_ranks_take_each_tool_at_its_best_f2_row(tmp_path):
    ranks = compare.r3_ranks(compare.load(run(tmp_path, "a"), compare.RUN))
    # rizzo-pii's best-F2 row is `@default` (F0.5 0.63, ahead of nullpii's
    # 0.53); its tuned row's F0.5 (0.6) is not the matrix's.
    assert ranks[f"R3 char-r3 · {DEFAULT} · rank by f05 at each tool's best-F2 row of 2"].shown == 2
    # Recall: the mean of nullpii's per-set recalls (0.958) against 0.92.
    assert ranks[f"R3 char-r3 · {DEFAULT} · rank by recall at each tool's best-F2 row of 2"].shown == 1
    assert ranks[f"R3 char-r3 · {DEFAULT} · rank by precision at each tool's best-F2 row of 2"].shown == 2
    # Per set: rizzo-pii's better row there (0.81) is ahead of 0.758.
    assert ranks[f"R3 char-r3 · r3-piilo · {DEFAULT} · rank by f2 of 2"].shown == 2


def test_a_tool_that_is_in_no_set_is_refused(tmp_path):
    out = run(tmp_path, "a", lambda f: f[R3]["_macro"].__setitem__("ghost", dict(f[R3]["_macro"]["rizzo-pii"])))
    with pytest.raises(compare.CompareError, match="ghost has a macro row but is in no set"):
        compare.compare(out, out)


def test_a_piimb_report_of_an_older_scorer_is_refused(tmp_path):
    out = run(tmp_path, "a", lambda f: f["piimb/piimb-default.json"].pop("without"))
    with pytest.raises(compare.CompareError, match="piimb-default.json has no without"):
        compare.compare(out, out)


def _set_ci(f, report, dataset, tool, **cis):
    f[f"r3/{report}.json"][dataset][tool] = {**f[f"r3/{report}.json"][dataset][tool], **cis}


def test_a_new_s2_breach_is_worse(tmp_path):
    # nullpii's recall significantly lower, and its precision lead goes
    # from significant (0.0083) to not (−0.0001): the tool now has higher
    # recall at matched precision, on both of its rows.
    def cell(low):
        def edit(f):
            for tool in ("rizzo-pii", "rizzo-pii@default"):
                _set_ci(f, "char-r3", "r3-eu-clinical", tool, baseline_minus_tool_recall_ci=[-0.05, -0.01],
                        baseline_minus_tool_precision_ci=[low, 0.05])
        return edit
    before = run(tmp_path, "before", cell(0.0083))
    after = run(tmp_path, "after", cell(-0.0001))
    changes = compare.compare(after, before)
    for tool in ("rizzo-pii", "rizzo-pii@default"):
        c = next(c for c in changes if c.where == f"R3 char-r3 · r3-eu-clinical · {DEFAULT} against {tool} (S2)")
        assert (c.before, c.after, c.verdict) == (compare.S2_HOLDS, compare.S2_BREACH, compare.WORSE)
    assert compare.exit_code(changes) == compare.EXIT_WORSE
    # And a breach that goes away is better.
    assert _verdicts(compare.compare(before, after))[
        f"R3 char-r3 · r3-eu-clinical · {DEFAULT} against rizzo-pii (S2)"] == compare.BETTER


def test_s2_is_judged_on_every_gated_verdicts_report_only(tmp_path):
    claims = compare.all_claims(compare.load(run(tmp_path, "a"), compare.RUN))
    s2 = {k.split(" · ")[0].removeprefix("R3 ") for k in claims if k.endswith("(S2)")}
    assert s2 == {v.report for v in compare.recipe.VERDICTS if v.mode == compare.recipe.BETTER_ROW}


def test_a_reversal_sign_that_flips_is_judged(tmp_path):
    # The verdict's F1 / F0.5 reversals read these signs: nullpii goes from
    # behind to ahead of rizzo-pii on macro F0.5, and to too close on one
    # set's F1.
    def edit(f):
        f[R3]["_macro"]["rizzo-pii"]["baseline_minus_tool_f05_ci"] = [0.01, 0.02]
        _set_ci(f, "char-r3", "r3-piilo", "rizzo-pii", baseline_minus_tool_f1_ci=[-0.01, 0.01])
    verdicts = _verdicts(compare.compare(run(tmp_path, "after", edit), run(tmp_path, "before")))
    assert verdicts == {f"R3 char-r3 · {DEFAULT} against rizzo-pii (F0.5)": compare.BETTER,
                        f"R3 char-r3 · r3-piilo · {DEFAULT} against rizzo-pii (F1)": compare.WORSE}


def test_the_per_set_rank_takes_each_tool_at_its_macro_better_row(tmp_path):
    # rizzo-pii's macro-better row is `@default` (0.77 against 0.58). On
    # PIILO its tuned row is ahead of nullpii and its `@default` row behind:
    # the tables show the `@default` row, so nullpii is first there.
    def edit(f):
        f[R3]["r3-piilo"]["rizzo-pii"]["f2"] = 0.9
        f[R3]["r3-piilo"]["rizzo-pii@default"]["f2"] = 0.7
    ranks = compare.r3_ranks(compare.load(run(tmp_path, "a", edit), compare.RUN))
    assert ranks[f"R3 char-r3 · r3-piilo · {DEFAULT} · rank by f2 of 2"].shown == 1


@pytest.mark.parametrize("edit, where", [
    (lambda f: f["piimb/piimb-everything.json"]["without"]["leaderboard"].update(rank=2),
     f"PIIMB · {EVERYTHING} · without nemotron-pii · rank of 36"),
    (lambda f: f["piimb/piimb-everything.json"]["task_ranks"]["privy"].update(rank=13),
     f"PIIMB · {EVERYTHING} · privy rank of 36"),
    (lambda f: f["ab1/coverage-ab1-b2.json"]["tools"][DEFAULT].update(leak_covered=0.2),
     f"AB-1 ab1-b2 · {DEFAULT} · leak_covered"),
    (lambda f: f["ab1/coverage-ab1-a.json"]["tools"][EVERYTHING].update(leak_uncovered=0.06),
     f"AB-1 ab1-a · {EVERYTHING} · leak_uncovered"),
])
def test_nullpii_moving_the_wrong_way_is_worse(tmp_path, edit, where):
    changes = compare.compare(run(tmp_path, "after", edit), run(tmp_path, "before"))
    assert _verdicts(changes) == {where: compare.WORSE}
    assert compare.exit_code(changes) == compare.EXIT_WORSE


def test_a_precision_interval_touching_zero_is_matched_precision(tmp_path):
    # r2_verdict.s2: precision CI low <= 0 is not significantly lower.
    def edit(f):
        _set_ci(f, "char-r3", "r3-piilo", "rizzo-pii", baseline_minus_tool_recall_ci=[-0.05, -0.01],
                baseline_minus_tool_precision_ci=[0.0, 0.05])
    claims = compare.all_claims(compare.load(run(tmp_path, "a", edit), compare.RUN))
    assert claims[f"R3 char-r3 · r3-piilo · {DEFAULT} against rizzo-pii (S2)"] == compare.S2_BREACH


def test_the_f05_rank_at_the_matrix_rows_is_not_the_rank_at_each_tools_best_f05(tmp_path):
    # rizzo-pii's tuned row has the better F0.5 (0.7) but the worse F2: the
    # matrix shows its `@default` row (F0.5 0.63), which nullpii's 0.65 beats.
    def edit(f):
        f[R3]["_macro"]["rizzo-pii"]["f05"] = 0.7
        f[R3]["_macro"][DEFAULT]["f05"] = 0.65
    ranks = compare.r3_ranks(compare.load(run(tmp_path, "a", edit), compare.RUN))
    assert ranks[f"R3 char-r3 · {DEFAULT} · rank by f05 at each tool's best-F2 row of 2"].shown == 1
    assert ranks[f"R3 char-r3 · {DEFAULT} · rank by f05 of 2"].shown == 2
