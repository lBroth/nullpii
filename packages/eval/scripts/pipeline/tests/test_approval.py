# SPDX-License-Identifier: Apache-2.0
"""`bench/approval` is decided from the commit and what it publishes: green
unless the head carries numbers bench.yml found worse (the owner's
`bench-accept-worse` turns it green), is a numbers branch bench.yml did not
measure, or edits published-bench by hand (the owner's
`bench-accept-manual` turns it green). A worse result never passes."""
import pytest

from pipeline import approval
from pipeline.approval import ACCEPT_LABEL, FAILURE, MANUAL_LABEL, SUCCESS, Head, decide

REPO = "lBroth/nullpii"
OWNER = "lBroth"
APP = "nullpii-bench[bot]"
RUN = 18947312345
MEASURED = "m" * 40
SHA = "a" * 40
RUN_URL = f"https://github.com/{REPO}/actions/runs/{RUN}"


def _pr(labels=(), ref=f"bench/run-{RUN}", head_repo=REPO, number=7):
    return {
        "number": number, "user": {"login": APP},
        "head": {"ref": ref, "sha": SHA, "repo": {"full_name": head_repo} if head_repo else None},
        "labels": [{"name": name} for name in labels],
    }


def _status(state, id_=1, context=approval.COMPARE_CONTEXT, creator=approval.BOT, url=RUN_URL):
    return {"id": id_, "context": context, "state": state, "creator": {"login": creator}, "target_url": url}


def _run(**over):
    run = {"id": RUN, "path": approval.BENCH_WORKFLOW, "head_branch": "main", "event": "push",
           "repository": {"full_name": REPO}, "head_sha": MEASURED}
    return {**run, **over}


def _event(actor, id_, event="labeled", label=ACCEPT_LABEL, at=None):
    return {"id": id_, "event": event, "label": {"name": label}, "actor": {"login": actor},
            "created_at": at or f"2026-10-30T10:00:{id_:02d}Z"}


def _head(pr=None, statuses=(), events=(), runs=None, parents=(MEASURED,), files=("README.md",), others=()):
    pr = pr or _pr()
    return Head(REPO, pr, list(statuses), {RUN: _run()} if runs is None else runs, list(parents), list(files),
                [(pr, list(events)), *others])


def _decide(**kw):
    return decide(_head(**kw), OWNER)


# A PR that publishes nothing ---------------------------------------------------------------

@pytest.mark.parametrize("ref", ["feature/x", "bench/rizzo-pii-comparison", "bench/run-1-evil", "bench/run-", "main"])
def test_a_pr_that_publishes_nothing_passes(ref):
    assert _decide(pr=_pr(ref=ref)).state == SUCCESS


def test_a_numbers_branch_of_this_repository_bench_yml_did_not_measure_is_held():
    assert _decide().state == FAILURE
    assert _decide(statuses=[_status(SUCCESS, creator="someone")]).state == FAILURE


def test_a_forks_branch_named_like_a_numbers_branch_cannot_turn_an_innocent_head_red():
    # The status is the commit's: a fork naming its branch bench/run-1 at
    # another PR's head must not fail that head.
    assert _decide(pr=_pr(ref="bench/run-1", head_repo="someone/nullpii")).state == SUCCESS
    assert _decide(pr=_pr(ref="bench/run-1", head_repo=None)).state == SUCCESS


# Hand edits of published-bench -----------------------------------------------------------

PUBLISHED = ("packages/eval/published-bench/ab1/scores-ab1-a.json",)


@pytest.mark.parametrize("ref, repo", [("feature/x", REPO), ("x", "someone/nullpii"), ("bench/run-9", "someone/nullpii")])
def test_a_hand_edit_of_published_bench_is_held_from_any_branch(ref, repo):
    d = _decide(pr=_pr(ref=ref, head_repo=repo), files=PUBLISHED)
    assert d.state == FAILURE and MANUAL_LABEL in d.description


def test_the_owners_manual_label_accepts_a_hand_edit_and_nothing_else_does():
    pr = _pr([MANUAL_LABEL], ref="feature/x")
    assert _decide(pr=pr, files=PUBLISHED, events=[_event(OWNER, 5, label=MANUAL_LABEL)]).state == SUCCESS
    assert _decide(pr=pr, files=PUBLISHED, events=[_event("a-triager", 5, label=MANUAL_LABEL)]).state == FAILURE
    # The worse label is not the manual one.
    pr = _pr([ACCEPT_LABEL], ref="feature/x")
    assert _decide(pr=pr, files=PUBLISHED, events=[_event(OWNER, 5)]).state == FAILURE


def test_a_renamed_file_out_of_published_bench_is_a_hand_edit():
    assert _decide(pr=_pr(ref="x"), files=["elsewhere.json", PUBLISHED[0]]).state == FAILURE


# Numbers bench.yml measured ------------------------------------------------------------------

def test_numbers_that_only_moved_pass_for_the_normal_review():
    d = _decide(statuses=[_status(SUCCESS)])
    assert d.state == SUCCESS and "normal review" in d.description


def test_worse_numbers_fail_until_the_owner_accepts():
    d = _decide(statuses=[_status(FAILURE)], files=PUBLISHED)
    assert d.state == FAILURE and ACCEPT_LABEL in d.description
    assert _decide(pr=_pr([ACCEPT_LABEL]), statuses=[_status(FAILURE)], events=[_event(OWNER, 5)]).state == SUCCESS


@pytest.mark.parametrize("ref, repo", [("x", "someone/nullpii"), ("feature/x", REPO), ("bench/run-1", "someone/nullpii")])
def test_worse_numbers_stay_red_from_any_branch_or_fork(ref, repo):
    # A fork's PR from any branch at a numbers head: the commit's numbers decide.
    d = _decide(pr=_pr(ref=ref, head_repo=repo), statuses=[_status(FAILURE)], files=PUBLISHED)
    assert d.state == FAILURE
    # And a manual label does not accept worse numbers.
    pr = _pr([MANUAL_LABEL], ref=ref, head_repo=repo)
    assert _decide(pr=pr, statuses=[_status(FAILURE)], files=PUBLISHED,
                   events=[_event(OWNER, 5, label=MANUAL_LABEL)]).state == FAILURE


def test_the_owners_label_on_another_open_pr_of_the_same_head_counts():
    numbers = _pr([ACCEPT_LABEL], number=7)
    fork = _pr(ref="x", head_repo="someone/nullpii", number=8)
    head = _head(pr=fork, statuses=[_status(FAILURE)], others=[(numbers, [_event(OWNER, 5)])])
    assert decide(head, OWNER).state == SUCCESS


def test_the_owner_is_matched_whatever_the_case():
    assert _decide(pr=_pr([ACCEPT_LABEL]), statuses=[_status(FAILURE)], events=[_event("lbroth", 5)]).state == SUCCESS


@pytest.mark.parametrize("actor", ["a-triager", APP, approval.BOT, "lBroth2", "", "xlBroth"])
def test_the_label_of_anyone_else_accepts_nothing(actor):
    assert _decide(pr=_pr([ACCEPT_LABEL]), statuses=[_status(FAILURE)], events=[_event(actor, 5)]).state == FAILURE


def test_the_label_on_the_pr_without_an_event_accepts_nothing():
    assert _decide(pr=_pr([ACCEPT_LABEL]), statuses=[_status(FAILURE)]).state == FAILURE


def test_the_label_events_are_replayed_in_order():
    pr = _pr([ACCEPT_LABEL])
    # The owner's label, removed, then added again by someone else.
    events = [_event(OWNER, 5), _event(OWNER, 6, "unlabeled"), _event("a-triager", 7)]
    assert _decide(pr=pr, statuses=[_status(FAILURE)], events=events).state == FAILURE
    assert _decide(pr=pr, statuses=[_status(FAILURE)], events=events[::-1]).state == FAILURE
    events = [_event("a-triager", 5), _event("a-triager", 6, "unlabeled"), _event(OWNER, 7)]
    assert _decide(pr=pr, statuses=[_status(FAILURE)], events=events).state == SUCCESS
    assert _decide(pr=pr, statuses=[_status(FAILURE)], events=events[::-1]).state == SUCCESS


def test_the_last_label_event_must_be_an_addition():
    # The label is on the PR (a label renamed to it, say) but its last event
    # is a removal: nothing accepted.
    events = [_event(OWNER, 5), _event(OWNER, 6, "unlabeled")]
    assert _decide(pr=_pr([ACCEPT_LABEL]), statuses=[_status(FAILURE)], events=events).state == FAILURE


def test_the_time_orders_the_events_before_the_id():
    events = [_event("a-triager", 9, at="2026-10-30T10:00:01Z"), _event(OWNER, 3, at="2026-10-30T11:00:00Z")]
    assert _decide(pr=_pr([ACCEPT_LABEL]), statuses=[_status(FAILURE)], events=events).state == SUCCESS


def test_removing_the_label_takes_the_acceptance_back():
    events = [_event(OWNER, 5), _event(OWNER, 6, "unlabeled")]
    assert _decide(statuses=[_status(FAILURE)], events=events).state == FAILURE


def test_another_label_of_the_owner_accepts_nothing():
    events = [_event(OWNER, 5, label="bench")]
    assert _decide(pr=_pr(["bench"]), statuses=[_status(FAILURE)], events=events).state == FAILURE
    assert _decide(pr=_pr(["bench", ACCEPT_LABEL]), statuses=[_status(FAILURE)], events=events).state == FAILURE


# Which bench/compare is trusted ---------------------------------------------------------------

@pytest.mark.parametrize("status, runs, parents", [
    (_status(SUCCESS, creator="someone"), None, (MEASURED,)),
    (_status(SUCCESS, creator=APP), None, (MEASURED,)),
    (_status(SUCCESS, context="bench/approval"), None, (MEASURED,)),
    (_status(SUCCESS, url="https://github.com/someone/nullpii/actions/runs/18947312345"), None, (MEASURED,)),
    (_status(SUCCESS, url="https://example.com/x"), None, (MEASURED,)),
    (_status(SUCCESS), {}, (MEASURED,)),
    (_status(SUCCESS), {RUN: _run(path=".github/workflows/ci.yml")}, (MEASURED,)),
    (_status(SUCCESS), {RUN: _run(head_branch="feature/x")}, (MEASURED,)),
    (_status(SUCCESS), {RUN: _run(event="pull_request")}, (MEASURED,)),
    (_status(SUCCESS), {RUN: _run(repository={"full_name": "someone/nullpii"})}, (MEASURED,)),
    (_status(SUCCESS), None, ("b" * 40,)),
])
def test_a_compare_status_bench_yml_did_not_set_on_this_measurement_is_not_trusted(status, runs, parents):
    # On a numbers branch: held. On another branch that edits published-bench: held.
    assert _decide(statuses=[status], runs=runs, parents=parents).state == FAILURE
    assert _decide(pr=_pr(ref="x"), statuses=[status], runs=runs, parents=parents, files=PUBLISHED).state == FAILURE


def test_a_numbers_branch_trusts_only_its_own_run():
    other = RUN + 1
    status = _status(SUCCESS, url=f"https://github.com/{REPO}/actions/runs/{other}")
    assert _decide(statuses=[status], runs={other: _run(id=other)}).state == FAILURE
    # From a fork's branch, the run need not match a name it chose.
    assert _decide(pr=_pr(ref="bench/run-1", head_repo="x/y"), statuses=[status],
                   runs={other: _run(id=other)}).state == SUCCESS


def test_a_dispatched_run_is_trusted():
    assert _decide(statuses=[_status(SUCCESS)], runs={RUN: _run(event="workflow_dispatch")}).state == SUCCESS


def test_the_latest_trusted_compare_status_counts():
    statuses = [_status(SUCCESS, 1), _status(FAILURE, 2), _status(SUCCESS, 3, context="ci")]
    assert _decide(statuses=statuses).state == FAILURE
    assert _decide(statuses=statuses[::-1]).state == FAILURE
    # Someone else's later success does not hide the trusted failure.
    statuses = [_status(FAILURE, 1), _status(SUCCESS, 2, creator="someone")]
    assert _decide(statuses=statuses).state == FAILURE


@pytest.mark.parametrize("state", ["pending", "error", "SUCCESS", ""])
def test_a_compare_status_that_is_neither_success_nor_failure_fails(state):
    assert _decide(pr=_pr([ACCEPT_LABEL]), statuses=[_status(state)], events=[_event(OWNER, 5)]).state == FAILURE


def test_every_description_fits_a_status():
    longest = "x" * 39
    for statuses in ([], [_status(SUCCESS)], [_status(FAILURE)], [_status("pending")]):
        for files in (("README.md",), PUBLISHED):
            for labels, events in (((), []), ([ACCEPT_LABEL, MANUAL_LABEL], [_event(longest, 5)])):
                d = decide(_head(pr=_pr(labels), statuses=statuses, events=events, files=files), longest)
                assert len(d.description) <= approval.MAX_DESCRIPTION
    with pytest.raises(ValueError):
        approval.Decision(SUCCESS, "x" * (approval.MAX_DESCRIPTION + 1))
    with pytest.raises(ValueError):
        approval.Decision("pending", "x")


# main ---------------------------------------------------------------------------------------

def _fake_api(monkeypatch, pr, statuses, files, moved=False, fail_on=None):
    calls = []

    def gh(*args):
        calls.append(args)
        path = next(a for a in args if a.startswith("repos/"))
        if fail_on and fail_on in path:
            raise RuntimeError(f"gh api {path} exited with 1")
        if args[0] == "--method":
            return {}
        if args[0] == "--paginate":
            if path.endswith("/statuses?per_page=100"):
                return [statuses]
            if path.endswith("/files?per_page=100"):
                return [[{"filename": f} for f in files]]
            return [[]]
        if "/actions/runs/" in path:
            return _run()
        if path.startswith(f"repos/{REPO}/commits/"):
            return {"parents": [{"sha": MEASURED}]}
        if moved and len([c for c in calls if c == args]) > 1:
            return {**pr, "head": {**pr["head"], "sha": "b" * 40}}
        return pr
    monkeypatch.setattr(approval, "_gh", gh)
    return calls


def _posts(calls):
    return [dict(a.split("=", 1) for a in c[4::2]) for c in calls if c[0] == "--method"]


def test_main_sets_pending_then_the_decision_on_the_head(monkeypatch):
    calls = _fake_api(monkeypatch, _pr(), [_status(FAILURE)], PUBLISHED)
    assert approval.main(["--repo", REPO, "--pr", "7", "--owner", OWNER, "--target-url", "u"]) == 0
    posts = _posts(calls)
    assert [p["state"] for p in posts] == ["pending", "failure"]
    assert all(p["context"] == approval.APPROVAL_CONTEXT for p in posts)
    assert all(c[2] == f"repos/{REPO}/statuses/{SHA}" for c in calls if c[0] == "--method")


def test_main_trusts_the_run_it_reads_and_lets_moved_numbers_through(monkeypatch):
    calls = _fake_api(monkeypatch, _pr(), [_status(SUCCESS)], PUBLISHED)
    approval.main(["--repo", REPO, "--pr", "7", "--owner", OWNER, "--target-url", "u"])
    assert [p["state"] for p in _posts(calls)] == ["pending", "success"]


def test_an_api_failure_leaves_pending_never_green(monkeypatch):
    calls = _fake_api(monkeypatch, _pr(), [_status(SUCCESS)], (), fail_on="/files")
    with pytest.raises(RuntimeError):
        approval.main(["--repo", REPO, "--pr", "7", "--owner", OWNER, "--target-url", "u"])
    assert [p["state"] for p in _posts(calls)] == ["pending"]


def test_a_head_that_moves_while_deciding_is_not_decided(monkeypatch):
    calls = _fake_api(monkeypatch, _pr(), [_status(SUCCESS)], (), moved=True)
    with pytest.raises(RuntimeError, match="head moved"):
        approval.main(["--repo", REPO, "--pr", "7", "--owner", OWNER, "--target-url", "u"])
    assert [p["state"] for p in _posts(calls)] == ["pending"]


def test_main_reads_a_file_renamed_out_of_published_bench_as_a_hand_edit(monkeypatch):
    calls = []

    def gh(*args):
        calls.append(args)
        path = next(a for a in args if a.startswith("repos/"))
        if args[0] == "--method":
            return {}
        if args[0] == "--paginate":
            if path.endswith("/files?per_page=100"):
                return [[{"filename": "elsewhere.json", "previous_filename": PUBLISHED[0]}]]
            return [[]]
        if path.startswith(f"repos/{REPO}/commits/"):
            return {"parents": [{"sha": MEASURED}]}
        return _pr(ref="feature/x")
    monkeypatch.setattr(approval, "_gh", gh)
    approval.main(["--repo", REPO, "--pr", "7", "--owner", OWNER, "--target-url", "u"])
    assert [p["state"] for p in _posts(calls)] == ["pending", "failure"]
