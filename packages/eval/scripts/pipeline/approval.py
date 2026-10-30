#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The owner's decision on a numbers PR, as the commit status
`bench/approval` on the PR's head.

bench.yml opens a numbers PR from a branch `bench/run-<run id>` when a
re-measurement moved a published number, and first sets `bench/compare`
on the commit it wrote: success when numbers only moved, failure when
something got worse. bench-approval.yml turns it into `bench/approval`,
the status branch protection requires on every PR to main:

- a PR from any other branch: success, the gate is not about it;
- a `bench/run-<id>` PR whose head has no `bench/compare` from the Actions
  bot: failure, since what it would merge is not what was measured (a
  push to the branch, or a branch of that name that bench.yml did not
  write);
- numbers moved, none worse: success (the normal review still applies);
- something got worse: failure, until the repository owner adds the
  `bench-accept-worse` label, and again as soon as it is removed.

A PR is a numbers PR by its branch name alone, whoever opened it and from
whichever repository: bench.yml always opens its PRs from such a branch,
so a PR wrongly taken for one is held, never one wrongly let through. Everything is read from the API by PR number, never
from the event that started the run, so each run decides from the PR's
current state. Only the Actions bot's `bench/compare` counts, and only
the owner's label.

  python -I approval.py --repo OWNER/NAME --pr N --owner LOGIN --target-url URL

Standard library only (it runs from the base branch, with nothing of the
PR checked out); the API is called through `gh api` (GH_TOKEN)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass

BOT = "github-actions[bot]"
BRANCH = re.compile(r"bench/run-[0-9]+")
COMPARE_CONTEXT = "bench/compare"
APPROVAL_CONTEXT = "bench/approval"
ACCEPT_LABEL = "bench-accept-worse"
SUCCESS, FAILURE = "success", "failure"
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


def _login(item: dict, field: str) -> str:
    return (item.get(field) or {}).get("login", "")


def is_numbers_pr(pr: dict) -> bool:
    """A PR from a branch named as bench.yml names its numbers PRs'
    (`bench/run-<run id>`), whoever opened it, from whichever repository.
    Other `bench/` branches are people's own work."""
    return BRANCH.fullmatch(pr["head"]["ref"]) is not None


def compare_state(statuses: list[dict]) -> str | None:
    """The latest `bench/compare` state the Actions bot set on the head, or
    None when it set none (the head is not a commit bench.yml measured)."""
    ours = [s for s in statuses if s["context"] == COMPARE_CONTEXT and _login(s, "creator") == BOT]
    return max(ours, key=lambda s: s["id"])["state"] if ours else None


def accepted_by(pr: dict, events: list[dict]) -> str | None:
    """Who added the accept label last, when it is on the PR now."""
    if ACCEPT_LABEL not in {label["name"] for label in pr["labels"]}:
        return None
    added = [e for e in events if e.get("event") == "labeled" and (e.get("label") or {}).get("name") == ACCEPT_LABEL]
    return _login(max(added, key=lambda e: e["id"]), "actor") if added else None


def decide(pr: dict, statuses: list[dict], events: list[dict], owner: str) -> Decision:
    """`bench/approval` for `pr`, from its head's statuses and its events."""
    if not is_numbers_pr(pr):
        return Decision(SUCCESS, "Not a numbers PR.")
    state = compare_state(statuses)
    if state is None:
        return Decision(FAILURE, "The head is not a commit bench.yml measured: run the benchmark again.")
    if state == SUCCESS:
        return Decision(SUCCESS, "Numbers moved, none got worse: the normal review applies.")
    if state != FAILURE:
        return Decision(FAILURE, f"{COMPARE_CONTEXT} is {state}, neither {SUCCESS} nor {FAILURE}.")
    who = accepted_by(pr, events)
    if who is not None and who.lower() == owner.lower():
        return Decision(SUCCESS, f"Something got worse; {owner} accepted it ({ACCEPT_LABEL}).")
    return Decision(FAILURE, f"Something got worse: needs {owner}'s {ACCEPT_LABEL} label.")


def _gh(*args: str) -> object:
    done = subprocess.run(["gh", "api", *args], stdout=subprocess.PIPE, text=True, check=False)
    if done.returncode != 0:
        endpoint = next((a for a in args if a.startswith("repos/")), "")
        raise RuntimeError(f"gh api {endpoint} exited with {done.returncode}")
    return json.loads(done.stdout)


def _all_pages(path: str) -> list[dict]:
    pages = _gh("--paginate", "--slurp", f"{path}?per_page={PER_PAGE}")
    return [item for page in pages for item in page]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Set bench/approval on a PR's head.")
    p.add_argument("--repo", required=True, help="OWNER/NAME")
    p.add_argument("--pr", type=int, required=True)
    p.add_argument("--owner", required=True, help="the login whose label accepts worse numbers")
    p.add_argument("--target-url", required=True, help="the run that decided")
    args = p.parse_args(argv)
    pr = _gh(f"repos/{args.repo}/pulls/{args.pr}")
    sha = pr["head"]["sha"]
    statuses = _all_pages(f"repos/{args.repo}/commits/{sha}/statuses")
    events = _all_pages(f"repos/{args.repo}/issues/{args.pr}/events")
    decision = decide(pr, statuses, events, args.owner)
    _gh(
        "--method", "POST", f"repos/{args.repo}/statuses/{sha}",
        "-f", f"state={decision.state}", "-f", f"context={APPROVAL_CONTEXT}",
        "-f", f"description={decision.description}", "-f", f"target_url={args.target_url}",
    )
    print(f"{APPROVAL_CONTEXT} on {sha[:12]} of #{args.pr}: {decision.state} ({decision.description})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
