# SPDX-License-Identifier: Apache-2.0
"""The numbers PR bench.yml opens after `render`: which files it may
change, and its title and body.

A numbers PR changes only what `render` writes: `published-bench/`, the
rendered docs (`docs.BLOCKS`) and the README's figures. None of these is
a path bench.yml runs on (a test checks it), so merging the PR starts no
re-measurement; the docs and figures among them redeploy the site
(docs.yml)."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from pipeline import compare, docs, settings, views

PUBLISHED_PREFIX = f"{settings.PUBLISHED.relative_to(views.ROOT).as_posix()}/"
FIGURE_SUFFIX = ".svg"
# GitHub refuses a PR body over 65,536 characters; the report is cut, at
# a line, to leave room for the rest.
MAX_REPORT = 60_000
REPORT_ARTIFACT = "bench-report"
ACCEPT_LABEL = "bench-accept-worse"
APPROVAL_CONTEXT = "bench/approval"
REPO = "lBroth/nullpii"
# The published run measured nullpii on CUDA; METHOD.md gives how far its
# CPU outputs are from those.
CUDA_CPU_AGREEMENT = "37 of the 14,701 tuning-set documents differ (release build, fp32 on both)"


class ProposalError(Exception):
    """`render` changed nothing, or something a numbers PR may not change."""


def allowed(path: str) -> bool:
    """A file a numbers PR may change."""
    if path.startswith(PUBLISHED_PREFIX):
        return True
    if path in docs.BLOCKS:
        return True
    folder, _, name = path.rpartition("/")
    return folder == docs.FIGURES and name.endswith(FIGURE_SUFFIX)


def changed_paths(root: Path) -> list[str]:
    """Every path `git status` reports changed, added, removed or renamed
    (both names of a rename) in the checkout at `root`."""
    done = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        stdout=subprocess.PIPE, check=True,
    )
    entries = done.stdout.decode("utf-8").split("\0")
    paths: list[str] = []
    i = 0
    while i < len(entries):
        entry = entries[i]
        i += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path)
        if "R" in status or "C" in status:
            paths.append(entries[i])
            i += 1
    return sorted(set(paths))


def check_changes(paths: list[str]) -> list[str]:
    """`paths`, when there is at least one and each may be changed."""
    if not paths:
        raise ProposalError("compare found a change, yet render changed no file")
    outside = [p for p in paths if not allowed(p)]
    if outside:
        raise ProposalError("render changed files a numbers PR may not change:\n  " + "\n  ".join(outside))
    return paths


@dataclass(frozen=True)
class Run:
    """The run a numbers PR proposes."""

    commit: str
    compare_exit: int
    run_url: str
    model: str
    runner: str

    @property
    def worse(self) -> bool:
        return self.compare_exit == compare.EXIT_WORSE


def title(run: Run) -> str:
    what = "something got worse" if run.worse else "numbers moved"
    return f"chore(bench): CPU re-measurement of {run.commit[:12]} ({what})"


def _cut(report: str) -> tuple[str, bool]:
    if len(report) <= MAX_REPORT:
        return report, False
    kept = report[:MAX_REPORT]
    return kept[:kept.rfind("\n") + 1] if "\n" in kept else kept, True


def _verdict(run: Run) -> str:
    if run.worse:
        return (f"**Something got worse.** The required check `{APPROVAL_CONTEXT}` stays red until the repository"
                f" owner adds the `{ACCEPT_LABEL}` label to this PR; removing the label takes the acceptance back, and"
                " a push to this branch voids the measurement. Read the worse rows first.")
    return (f"**Numbers moved, none got worse.** `{APPROVAL_CONTEXT}` is green; the normal review applies.")


def _changed_summary(changed: list[str]) -> str:
    published = sum(p.startswith(PUBLISHED_PREFIX) for p in changed)
    rest = [p for p in changed if not p.startswith(PUBLISHED_PREFIX)]
    listed = ", ".join(f"`{p}`" for p in rest)
    return f"{published} files of `{PUBLISHED_PREFIX}`" + (f", and {listed}" if rest else "")


def body(run: Run, report: str, changed: list[str]) -> str:
    """The PR body: what was measured and on what, the verdict, and
    compare's report."""
    shown, cut = _cut(report)
    lines = [
        f"Opened by [bench.yml]({run.run_url}) after a change on `main` that nullpii's numbers depend on. Only"
        " nullpii was run again; every other tool's rows are scored from its frozen predictions of the published"
        " run.",
        "",
        f"- **CPU re-measurement**: {run.runner}. The published {views.PUBLISHED_VERSION} run measured nullpii on CUDA; its CUDA and CPU"
        f" outputs agree on all but a few documents in a thousand ({CUDA_CPU_AGREEMENT}; METHOD.md, Results).",
        f"- **Commit measured**: `{run.commit}`",
        f"- **Frozen inputs**: `{settings.FROZEN_REPO}@{settings.FROZEN_REVISION}` (manifest SHA-256"
        f" `{settings.FROZEN_MANIFEST_SHA256}`)",
        f"- **Model**: `{run.model}`",
        f"- **compare** exited {run.compare_exit}",
        "",
        _verdict(run),
        "",
        f"This PR changes {_changed_summary(changed)}: what `render` writes from the run's outputs. Latency is not"
        " measured here and the CHANGELOG is not touched. Nothing merges it automatically; the owner merges it"
        f" with `gh pr merge <number> --repo {REPO} --squash`. A newer numbers PR replaces this one: close the"
        " older.",
        "",
        "## compare's report",
        "",
        shown.rstrip("\n"),
    ]
    if cut:
        lines += ["", f"The report is longer than a PR body holds: all of it is the `{REPORT_ARTIFACT}` artifact of"
                      f" [the run]({run.run_url})."]
    return "\n".join(lines) + "\n"
