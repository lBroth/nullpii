# SPDX-License-Identifier: Apache-2.0
"""`bench/approval`: green on every PR but a numbers PR whose numbers got
worse, which only the owner's label turns green, and only while it is on."""
import pytest

from pipeline import approval
from pipeline.approval import FAILURE, SUCCESS, decide

OWNER = "lBroth"
APP = "nullpii-bench[bot]"


def _pr(labels=(), user=APP, ref="bench/run-123456", head_repo="lBroth/nullpii"):
    return {
        "user": {"login": user},
        "head": {"ref": ref, "sha": "a" * 40, "repo": {"full_name": head_repo} if head_repo else None},
        "labels": [{"name": name} for name in labels],
    }


def _status(state, id_=1, context=approval.COMPARE_CONTEXT, creator=approval.BOT):
    return {"id": id_, "context": context, "state": state, "creator": {"login": creator}}


def _labeled(actor, id_, event="labeled", label=approval.ACCEPT_LABEL):
    return {"id": id_, "event": event, "label": {"name": label}, "actor": {"login": actor}}


@pytest.mark.parametrize("ref", ["feature/x", "bench/rizzo-pii-comparison", "bench/run-1-evil", "bench/run-", "main"])
def test_a_pr_from_another_branch_passes(ref):
    assert decide(_pr(ref=ref), [_status(FAILURE)], [], OWNER).state == SUCCESS


@pytest.mark.parametrize("pr", [
    _pr(user="someone"),
    _pr(head_repo="someone/nullpii"),
    _pr(head_repo=None),
])
def test_a_numbers_branch_is_held_whoever_opened_it_and_from_wherever(pr):
    # No bench/compare of the bot on its head: what it would merge was not measured.
    assert decide(pr, [], [], OWNER).state == FAILURE
    assert decide(pr, [_status(FAILURE)], [], OWNER).state == FAILURE


def test_numbers_that_only_moved_pass_for_the_normal_review():
    d = decide(_pr(), [_status(SUCCESS)], [], OWNER)
    assert d.state == SUCCESS
    assert "normal review" in d.description


def test_worse_numbers_fail_until_the_owner_accepts():
    d = decide(_pr(), [_status(FAILURE)], [], OWNER)
    assert d.state == FAILURE
    assert approval.ACCEPT_LABEL in d.description
    accepted = decide(_pr([approval.ACCEPT_LABEL]), [_status(FAILURE)], [_labeled(OWNER, 5)], OWNER)
    assert accepted.state == SUCCESS


def test_the_owner_is_matched_whatever_the_case():
    d = decide(_pr([approval.ACCEPT_LABEL]), [_status(FAILURE)], [_labeled("lbroth", 5)], OWNER)
    assert d.state == SUCCESS


@pytest.mark.parametrize("actor", ["a-triager", APP, approval.BOT, "lBroth2", "", "xlBroth"])
def test_the_label_of_anyone_else_accepts_nothing(actor):
    d = decide(_pr([approval.ACCEPT_LABEL]), [_status(FAILURE)], [_labeled(actor, 5)], OWNER)
    assert d.state == FAILURE


def test_the_label_on_the_pr_without_an_event_accepts_nothing():
    assert decide(_pr([approval.ACCEPT_LABEL]), [_status(FAILURE)], [], OWNER).state == FAILURE


def test_the_last_person_to_add_the_label_decides():
    events = [_labeled(OWNER, 5), _labeled(OWNER, 6, "unlabeled"), _labeled("a-triager", 7)]
    assert decide(_pr([approval.ACCEPT_LABEL]), [_status(FAILURE)], events, OWNER).state == FAILURE
    # The same events listed in another order: the id decides, not the order.
    assert decide(_pr([approval.ACCEPT_LABEL]), [_status(FAILURE)], events[::-1], OWNER).state == FAILURE
    events = [_labeled("a-triager", 5), _labeled("a-triager", 6, "unlabeled"), _labeled(OWNER, 7)]
    assert decide(_pr([approval.ACCEPT_LABEL]), [_status(FAILURE)], events, OWNER).state == SUCCESS
    assert decide(_pr([approval.ACCEPT_LABEL]), [_status(FAILURE)], events[::-1], OWNER).state == SUCCESS


def test_removing_the_label_takes_the_acceptance_back():
    d = decide(_pr(), [_status(FAILURE)], [_labeled(OWNER, 5), _labeled(OWNER, 6, "unlabeled")], OWNER)
    assert d.state == FAILURE


def test_another_label_of_the_owner_accepts_nothing():
    events = [_labeled(OWNER, 5, label="bench")]
    assert decide(_pr(["bench"]), [_status(FAILURE)], events, OWNER).state == FAILURE
    assert decide(_pr(["bench", approval.ACCEPT_LABEL]), [_status(FAILURE)], events, OWNER).state == FAILURE


def test_a_head_bench_yml_did_not_measure_fails_even_when_accepted():
    pr = _pr([approval.ACCEPT_LABEL])
    events = [_labeled(OWNER, 5)]
    assert decide(pr, [], events, OWNER).state == FAILURE
    # A bench/compare that someone else set does not count, success or not.
    for creator in ("someone", APP, OWNER):
        assert decide(pr, [_status(SUCCESS, creator=creator)], events, OWNER).state == FAILURE
    # Nor does another context of the bot's.
    assert decide(pr, [_status(SUCCESS, context="bench/approval")], events, OWNER).state == FAILURE


def test_the_latest_compare_status_of_the_bot_counts():
    statuses = [_status(SUCCESS, 1), _status(FAILURE, 2), _status(SUCCESS, 3, context="ci")]
    assert decide(_pr(), statuses, [], OWNER).state == FAILURE
    assert decide(_pr(), statuses[::-1], [], OWNER).state == FAILURE
    # Someone else's later success does not hide the bot's failure.
    statuses = [_status(FAILURE, 1), _status(SUCCESS, 2, creator="someone")]
    assert decide(_pr(), statuses, [], OWNER).state == FAILURE


@pytest.mark.parametrize("state", ["pending", "error", "SUCCESS", ""])
def test_a_compare_status_that_is_neither_success_nor_failure_fails(state):
    assert decide(_pr([approval.ACCEPT_LABEL]), [_status(state)], [_labeled(OWNER, 5)], OWNER).state == FAILURE


def test_every_description_fits_a_status():
    longest_login = "x" * 39
    for statuses in ([], [_status(SUCCESS)], [_status(FAILURE)], [_status("pending")]):
        for labels, events in (((), []), ([approval.ACCEPT_LABEL], [_labeled(longest_login, 5)])):
            d = decide(_pr(labels), statuses, events, longest_login)
            assert len(d.description) <= approval.MAX_DESCRIPTION
    with pytest.raises(ValueError):
        approval.Decision(SUCCESS, "x" * (approval.MAX_DESCRIPTION + 1))
    with pytest.raises(ValueError):
        approval.Decision("pending", "x")


def test_main_sets_the_decision_on_the_head(monkeypatch, capsys):
    calls = []
    pr = _pr()

    def gh(*args):
        calls.append(args)
        if args[0] == "--paginate":
            return [[_status(FAILURE)]] if "statuses" in args[2] else [[]]
        if args[0] == "--method":
            return {}
        return pr
    monkeypatch.setattr(approval, "_gh", gh)
    assert approval.main(["--repo", "lBroth/nullpii", "--pr", "7", "--owner", OWNER, "--target-url", "u"]) == 0
    post = calls[-1]
    assert post[:3] == ("--method", "POST", f"repos/lBroth/nullpii/statuses/{'a' * 40}")
    assert "state=failure" in post and f"context={approval.APPROVAL_CONTEXT}" in post
