#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The owner's decision on what a PR would publish, as the commit status
`bench/approval` on the PR's head.

A status belongs to a commit, not to a PR, so the decision is read from
the commit and its content, never from the PR's branch name alone:

- The head carries a trusted `bench/compare`: one the Actions bot set,
  whose target is a run of bench.yml on main (a push or a dispatch) that
  measured the head's parent, the commit bench.yml's numbers commit sits
  on (and, on a branch of this repository named `bench/run-<id>`, that very
  run). Then: success when compare found numbers that only moved; when
  something got worse, success only while the repository owner's
  `bench-accept-worse` label is on a PR of this head and the owner added
  it last; any other state, failure.
- No trusted `bench/compare`: failure for a branch of this repository named
  `bench/run-<id>` (a push to a numbers PR, or a branch of that name
  bench.yml did not measure); failure for a PR that changes
  `packages/eval/published-bench/` (a hand edit of the published outputs),
  until the owner's `bench-accept-manual` label is on it, added last by the
  owner; success otherwise.

A label is replayed: of its `labeled` and `unlabeled` events, in order, the
last must be `labeled`, by the owner, and the label must be on the PR now.
The labels of every open PR whose head is this commit count, so two PRs
of one commit get one decision. Everything is read from the API, never
from the event that started the run.

  python -I approval.py --repo OWNER/NAME --pr N --owner LOGIN --target-url URL

Standard library only (it runs from the base branch, with nothing of the
PR checked out); the API is called through `gh api` (GH_TOKEN). The
status is set to pending first, so a run that fails leaves no stale green
(bench-approval.yml then sets failure)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass, field

BOT = "github-actions[bot]"
BRANCH = re.compile(r"bench/run-([0-9]+)")
COMPARE_CONTEXT = "bench/compare"
APPROVAL_CONTEXT = "bench/approval"
ACCEPT_LABEL = "bench-accept-worse"
MANUAL_LABEL = "bench-accept-manual"
PUBLISHED_PREFIX = "packages/eval/published-bench/"
BENCH_WORKFLOW = ".github/workflows/bench.yml"
BENCH_BRANCH = "main"
BENCH_EVENTS = frozenset({"push", "workflow_dispatch"})
SUCCESS, FAILURE, PENDING = "success", "failure", "pending"
LABEL_EVENTS = frozenset({"labeled", "unlabeled"})
# GitHub's limit on a commit status description.
MAX_DESCRIPTION = 140
PER_PAGE = 100


@dataclass(frozen=True)
class Decision:
    """The state and description `bench/approval` gets."""

    state: str
    description: str

    def __post_init__(self) -> None:
        if self.state not in (SUCCESS, FAILURE):
            raise ValueError(f"a decision is {SUCCESS} or {FAILURE}, not {self.state!r}")
        if len(self.description) > MAX_DESCRIPTION:
            raise ValueError(f"a status description has at most {MAX_DESCRIPTION} characters")


@dataclass(frozen=True)
class Head:
    """What the API says about a PR's head commit, and the PRs on it."""

    repo: str
    pr: dict
    statuses: list[dict]
    runs: dict[int, dict]
    parents: list[str]
    files: list[str]
    # (PR, its issue events) for the PR decided on and every other open PR
    # whose head is this commit.
    prs: list[tuple[dict, list[dict]]] = field(default_factory=list)


def _login(item: dict, field_name: str) -> str:
    return (item.get(field_name) or {}).get("login", "")


def run_id(target_url: str, repo: str) -> int | None:
    """The run a status points to, when it is a run of `repo`."""
    m = re.fullmatch(rf"https://github\.com/{re.escape(repo)}/actions/runs/([0-9]+)", target_url or "")
    return int(m.group(1)) if m else None


def same_repo_branch(pr: dict, repo: str) -> str | None:
    """The head branch, when it is a branch of `repo` (not a fork's)."""
    head_repo = pr["head"].get("repo") or {}
    return pr["head"]["ref"] if head_repo.get("full_name") == repo else None


def trusted(status: dict, head: Head) -> bool:
    """A `bench/compare` bench.yml set on this head, from a run on main
    that measured its parent."""
    if status.get("context") != COMPARE_CONTEXT or _login(status, "creator") != BOT:
        return False
    rid = run_id(status.get("target_url", ""), head.repo)
    run = head.runs.get(rid) if rid is not None else None
    if run is None:
        return False
    ok = (run.get("path") == BENCH_WORKFLOW and run.get("head_branch") == BENCH_BRANCH
          and run.get("event") in BENCH_EVENTS and (run.get("repository") or {}).get("full_name") == head.repo
          and run.get("head_sha") in head.parents)
    branch = same_repo_branch(head.pr, head.repo)
    m = BRANCH.fullmatch(branch) if branch else None
    return ok and (m is None or int(m.group(1)) == rid)


def compare_state(head: Head) -> str | None:
    """The latest trusted `bench/compare` state on the head, or None."""
    ours = [s for s in head.statuses if trusted(s, head)]
    return max(ours, key=lambda s: s["id"])["state"] if ours else None


def label_by(pr: dict, events: list[dict], label: str) -> str | None:
    """Who added `label` to `pr`, when it is on the PR now and its last
    labeled/unlabeled event is that addition."""
    if label not in {item["name"] for item in pr["labels"]}:
        return None
    replay = sorted((e for e in events if e.get("event") in LABEL_EVENTS
                     and (e.get("label") or {}).get("name") == label),
                    key=lambda e: (e.get("created_at", ""), e["id"]))
    if not replay or replay[-1]["event"] != "labeled":
        return None
    return _login(replay[-1], "actor")


def accepted(head: Head, label: str, owner: str) -> bool:
    """The owner's `label` is on one of the PRs of this head, added last."""
    for pr, events in head.prs:
        who = label_by(pr, events, label)
        if who is not None and who.lower() == owner.lower():
            return True
    return False


def decide(head: Head, owner: str) -> Decision:
    """`bench/approval` for the head of `head.pr`."""
    state = compare_state(head)
    if state == SUCCESS:
        return Decision(SUCCESS, "Numbers moved, none got worse: the normal review applies.")
    if state == FAILURE:
        if accepted(head, ACCEPT_LABEL, owner):
            return Decision(SUCCESS, f"Something got worse; {owner} accepted it ({ACCEPT_LABEL}).")
        return Decision(FAILURE, f"Something got worse: needs {owner}'s {ACCEPT_LABEL} label.")
    if state is not None:
        return Decision(FAILURE, f"{COMPARE_CONTEXT} is {state}, neither {SUCCESS} nor {FAILURE}.")
    branch = same_repo_branch(head.pr, head.repo)
    if branch is not None and BRANCH.fullmatch(branch):
        return Decision(FAILURE, "The head is not a commit bench.yml measured: run the benchmark again.")
    if any(path.startswith(PUBLISHED_PREFIX) for path in head.files):
        if accepted(head, MANUAL_LABEL, owner):
            return Decision(SUCCESS, f"published-bench edited by hand; {owner} accepted it ({MANUAL_LABEL}).")
        return Decision(FAILURE, f"Edits published-bench outside bench.yml: needs {owner}'s {MANUAL_LABEL} label.")
    return Decision(SUCCESS, "Publishes no benchmark output.")


def _gh(*args: str) -> object:
    done = subprocess.run(["gh", "api", *args], stdout=subprocess.PIPE, text=True, check=False)
    if done.returncode != 0:
        endpoint = next((a for a in args if a.startswith("repos/")), "")
        raise RuntimeError(f"gh api {endpoint} exited with {done.returncode}")
    return json.loads(done.stdout)


def _all_pages(path: str) -> list[dict]:
    pages = _gh("--paginate", "--slurp", f"{path}?per_page={PER_PAGE}")
    return [item for page in pages for item in page]


def _set(repo: str, sha: str, state: str, description: str, target_url: str) -> None:
    _gh("--method", "POST", f"repos/{repo}/statuses/{sha}", "-f", f"state={state}",
        "-f", f"context={APPROVAL_CONTEXT}", "-f", f"description={description}", "-f", f"target_url={target_url}")


def read_head(repo: str, number: int) -> Head:
    """Everything `decide` reads, from the API."""
    pr = _gh(f"repos/{repo}/pulls/{number}")
    sha = pr["head"]["sha"]
    statuses = _all_pages(f"repos/{repo}/commits/{sha}/statuses")
    ids = {rid for s in statuses if s.get("context") == COMPARE_CONTEXT
           and (rid := run_id(s.get("target_url", ""), repo)) is not None}
    runs = {rid: _gh(f"repos/{repo}/actions/runs/{rid}") for rid in sorted(ids)}
    parents = [p["sha"] for p in _gh(f"repos/{repo}/commits/{sha}")["parents"]]
    files: list[str] = []
    for f in _all_pages(f"repos/{repo}/pulls/{number}/files"):
        files += [f["filename"], *([f["previous_filename"]] if f.get("previous_filename") else [])]
    others = [p for p in _all_pages(f"repos/{repo}/commits/{sha}/pulls")
              if p["state"] == "open" and p["number"] != number and p["head"]["sha"] == sha]
    prs = [(p, _all_pages(f"repos/{repo}/issues/{p['number']}/events")) for p in (pr, *others)]
    return Head(repo, pr, statuses, runs, parents, files, prs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Set bench/approval on a PR's head.")
    p.add_argument("--repo", required=True, help="OWNER/NAME")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--owner", required=True, help="the login whose labels accept")
    p.add_argument("--target-url", required=True, help="the run that decided")
    args = p.parse_args(argv)
    sha = _gh(f"repos/{args.repo}/pulls/{args.pr}")["head"]["sha"]
    _set(args.repo, sha, PENDING, "Deciding.", args.target_url)
    head = read_head(args.repo, args.pr)
    if head.pr["head"]["sha"] != sha:
        raise RuntimeError(f"#{args.pr}'s head moved while deciding: run again")
    decision = decide(head, args.owner)
    _set(args.repo, sha, decision.state, decision.description, args.target_url)
    print(f"{APPROVAL_CONTEXT} on {sha[:12]} of #{args.pr}: {decision.state} ({decision.description})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
