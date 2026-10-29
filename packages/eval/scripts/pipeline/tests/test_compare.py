# SPDX-License-Identifier: Apache-2.0
"""A change is judged at the printed precision, in the metric's own
direction, and so is every derived claim."""
import json
from pathlib import Path

from pipeline import compare


def _ab1_row(leak=0.0945, keep=0.8545, **extra):
    row = {
        "leak_rate": leak, "keep_rate": keep, "docs_with_leak": 0.27, "clean_docs_masked": 0.611,
        "outside_per_1k": 10.87, "encoded_leak_rate": None, "json_parse_rate": 0.912,
        "diff_consistent_rate": 1.0, "leak_by_category": {"email": [0.0, 536]}, "keep_by_kind": {"date": [0.9, 727]},
        "ci": {"leak": [0.08, 0.1], "keep": [0.84, 0.87]},
    }
    row.update(extra)
    return row


def _competitor(leak_ci, keep_ci):
    return {**_ab1_row(), "ci": {"baseline_minus_tool_leak": leak_ci, "baseline_minus_tool_keep": keep_ci}}


def _write(out: Path, name: str, data: dict) -> None:
    path = out / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _r3(f2_default: float, rizzo_ci=(-0.02, -0.003), rizzo_f2=0.77) -> dict:
    row = {"recall": 0.95, "precision": 0.5, "f2": f2_default}
    return {
        "r3-redact": {"nullpii-default": row, "rizzo-pii": {"recall": 0.9, "precision": 0.6, "f2": 0.8}},
        "_macro": {
            "nullpii-default": {"f2": f2_default, "f1": 0.62, "f05": 0.53},
            "rizzo-pii": {"f2": 0.58, "f1": 0.5, "f05": 0.6, "baseline_minus_tool_f2_ci": [0.1, 0.2]},
            "rizzo-pii@default": {"f2": rizzo_f2, "f1": 0.68, "f05": 0.63, "baseline_minus_tool_f2_ci": list(rizzo_ci)},
            "mask-all": {"f2": 0.26, "f1": 0.2, "f05": 0.1, "baseline_minus_tool_f2_ci": [0.4, 0.5]},
        },
    }


def _run(tmp_path, name, ab1=None, r3=None):
    out = tmp_path / name
    _write(out, "ab1/scores-ab1-a.json", ab1 or {"nullpii-default": _ab1_row()})
    _write(out, "r3/char-r3.json", r3 or _r3(0.758))
    return out


def _verdicts(changes):
    return {c.where: c.verdict for c in changes if c.verdict != compare.SAME}


def test_a_run_compared_with_itself_moved_nothing(tmp_path):
    a = _run(tmp_path, "a")
    changes = compare.compare(a, a, {})
    assert _verdicts(changes) == {}
    assert compare.exit_code(changes) == compare.EXIT_UNCHANGED


def test_a_change_below_the_printed_digit_is_no_change(tmp_path):
    # Both print as 9.5%.
    before = _run(tmp_path, "before", ab1={"nullpii-default": _ab1_row(leak=0.09451)})
    after = _run(tmp_path, "after", ab1={"nullpii-default": _ab1_row(leak=0.09459)})
    assert _verdicts(compare.compare(after, before, {})) == {}
    # Across the printed digit it is a change, however small.
    across = _run(tmp_path, "across", ab1={"nullpii-default": _ab1_row(leak=0.09449)})
    assert _verdicts(compare.compare(across, before, {})) == {"AB-1 ab1-a · nullpii-default · leak_rate": compare.BETTER}


def test_a_lower_leak_is_better_and_a_lower_keep_is_worse(tmp_path):
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", ab1={"nullpii-default": _ab1_row(leak=0.085, keep=0.84)})
    changes = compare.compare(after, before, {})
    verdicts = _verdicts(changes)
    assert verdicts["AB-1 ab1-a · nullpii-default · leak_rate"] == compare.BETTER
    assert verdicts["AB-1 ab1-a · nullpii-default · keep_rate"] == compare.WORSE
    assert compare.exit_code(changes) == compare.EXIT_WORSE


def test_a_rate_a_set_has_no_item_for_is_not_compared(tmp_path):
    out = _run(tmp_path, "a")
    assert not any("encoded_leak_rate" in k for k in compare.ab1_metrics(out, {}))


def test_published_row_names_are_read_under_their_current_ones(tmp_path):
    before = _run(tmp_path, "before", ab1={"nullpii-H3b-cuda-agent": _ab1_row()})
    after = _run(tmp_path, "after")
    assert _verdicts(compare.compare(after, before, {"nullpii-H3b-cuda-agent": "nullpii-default"})) == {}


def test_a_metric_only_one_side_has_is_new_or_gone(tmp_path):
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after")
    _write(after, "piimb/piimb-default.json", {"avg_f2": 0.85, "tasks": {"privy": {"f2": 0.713}}})
    (before / "r3" / "char-r3.json").unlink()
    verdicts = _verdicts(compare.compare(after, before, {}))
    assert verdicts["PIIMB · nullpii-default · average F2"] == compare.NEW
    assert verdicts["R3 char-r3 · _macro · nullpii-default · f2"] == compare.NEW
    changes = compare.compare(before, after, {})
    assert _verdicts(changes)["PIIMB · nullpii-default · privy F2"] == compare.GONE
    assert compare.exit_code(changes) == compare.EXIT_CHANGED


def test_a_lead_that_becomes_too_close_to_call_is_worse(tmp_path):
    before = _run(tmp_path, "before", ab1={"nullpii-default": _ab1_row(), "presidio": _competitor([-0.3, -0.2], [0.1, 0.2])})
    after = _run(tmp_path, "after", ab1={"nullpii-default": _ab1_row(), "presidio": _competitor([-0.05, 0.01], [0.1, 0.2])})
    verdicts = _verdicts(compare.compare(after, before, {}))
    assert verdicts == {"AB-1 ab1-a · nullpii against presidio (leak)": compare.WORSE}


def test_a_gap_that_closes_on_r3_is_better(tmp_path):
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", r3=_r3(0.758, rizzo_ci=(-0.01, 0.004)))
    verdicts = _verdicts(compare.compare(after, before, {}))
    assert verdicts == {"R3 char-r3 · nullpii against rizzo-pii@default (F2)": compare.BETTER}


def test_the_rank_counts_each_tool_once_at_its_better_row(tmp_path):
    out = _run(tmp_path, "a")
    ranks = compare.r3_ranks(out, {})
    # rizzo-pii's better row (0.77) is ahead; mask-all is not a tool.
    assert ranks["R3 char-r3 · nullpii-default · rank by f2 of 2"].shown == 2
    after = _run(tmp_path, "b", r3=_r3(0.78))
    verdicts = _verdicts(compare.compare(after, out, {}))
    assert verdicts["R3 char-r3 · nullpii-default · rank by f2 of 2"] == compare.BETTER


def test_the_report_puts_worse_changes_first(tmp_path):
    before = _run(tmp_path, "before")
    after = _run(tmp_path, "after", ab1={"nullpii-default": _ab1_row(leak=0.085, keep=0.84)})
    text = compare.report(compare.compare(after, before, {}))
    assert text.startswith("**1 worse, 1 better**")
    rows = [line for line in text.splitlines() if line.startswith("| AB-1")]
    assert rows[0].endswith("| worse |")
