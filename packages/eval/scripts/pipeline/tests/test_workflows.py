# SPDX-License-Identifier: Apache-2.0
"""The numbers PR and the workflows that make and gate it: a numbers PR
changes only what `render` writes, none of which re-runs the benchmark,
and the docs among them redeploy the site; the workflows agree with the
pipeline on the names the gate reads; every action is pinned."""
import re
import subprocess
from pathlib import Path

import pytest

from pipeline import approval, compare, docs, proposal, settings, views

WORKFLOWS = views.ROOT / ".github" / "workflows"
BENCH, DOCS, APPROVAL = WORKFLOWS / "bench.yml", WORKFLOWS / "docs.yml", WORKFLOWS / "bench-approval.yml"


def push_paths(workflow: Path) -> list[str]:
    """The `paths` of the workflow's `push` trigger, in order."""
    lines = workflow.read_text(encoding="utf-8").splitlines()
    start = lines.index("  push:")
    paths, inside = [], False
    for line in lines[start + 1:]:
        if not line.startswith("    "):
            break
        if line.strip() == "paths:":
            inside = True
        elif inside and line.strip().startswith("- "):
            paths.append(line.strip()[2:].strip("'\""))
        elif inside and not line.strip().startswith("#"):
            inside = False
    assert paths, f"{workflow.name} has no push paths"
    return paths


def _glob(pattern: str) -> re.Pattern:
    """GitHub's filter globs: `**` any characters, `*` any but `/`."""
    out, i = "", 0
    while i < len(pattern):
        if pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif pattern[i] == "*":
            out, i = out + "[^/]*", i + 1
        else:
            out, i = out + re.escape(pattern[i]), i + 1
    return re.compile(out)


def triggers(paths: list[str], path: str) -> bool:
    """Whether a change to `path` runs a workflow filtered on `paths` (the
    last pattern that matches decides; `!` excludes)."""
    hit = False
    for pattern in paths:
        negative = pattern.startswith("!")
        if _glob(pattern.lstrip("!")).fullmatch(path):
            hit = not negative
    return hit


def rendered_paths() -> list[str]:
    """Every file `render` writes now, and every file of published-bench."""
    published = [p.relative_to(views.ROOT).as_posix() for p in settings.PUBLISHED.rglob("*") if p.is_file()]
    figures = [p.relative_to(views.ROOT).as_posix() for p in (views.ROOT / docs.FIGURES).glob("*.svg")]
    return [*docs.BLOCKS, *figures, *published]


def test_the_glob_reads_as_github_does():
    assert triggers(["src/**"], "src/a/b.ts") and not triggers(["src/*"], "src/a/b.ts")
    assert not triggers(["packages/eval/scripts/**", "!packages/eval/scripts/**/tests/**"],
                        "packages/eval/scripts/pipeline/tests/test_cli.py")
    assert triggers(["!a/**", "a/**"], "a/b")


def test_a_numbers_pr_never_starts_a_benchmark_run():
    paths = push_paths(BENCH)
    rendered = rendered_paths()
    assert len(rendered) > 20
    assert [p for p in rendered if not proposal.allowed(p)] == []
    assert [p for p in rendered if triggers(paths, p)] == []
    # Nor would any other file a numbers PR may change.
    for p in ("packages/eval/published-bench/r3/new-report.json", "assets/readme/new-figure.svg"):
        assert proposal.allowed(p) and not triggers(paths, p)


@pytest.mark.parametrize("path", [
    "src/defaults.ts", "package-lock.json", "tsconfig.build.json", "packages/eval/scripts/ab/char_metrics.py",
    "packages/eval/scripts/pipeline/capture.py", "packages/eval/scripts/pipeline/compare.py",
    "packages/eval/src/nullpii_eval/public_datasets.py", "packages/eval/requirements-pipeline.txt",
    ".github/workflows/bench.yml",
])
def test_a_change_the_numbers_depend_on_starts_a_run(path):
    assert triggers(push_paths(BENCH), path)


@pytest.mark.parametrize("path", [
    "packages/eval/scripts/pipeline/tests/test_cli.py", "packages/eval/scripts/pipeline/approval.py",
    "packages/eval/scripts/pipeline/card.py", "docs/index.md", ".github/workflows/bench-approval.yml",
    "MODEL_CARD.md",
])
def test_a_change_no_number_depends_on_starts_none(path):
    assert not triggers(push_paths(BENCH), path)


@pytest.mark.parametrize("path", [
    "packages/eval/scripts/pipeline/compare.py", "packages/eval/scripts/bench_pipeline.py", "src/index.ts",
    ".github/workflows/ci.yml",
])
def test_nothing_a_numbers_pr_may_change_is_code(path):
    assert not proposal.allowed(path)


def test_the_site_redeploys_when_a_numbers_pr_changes_what_it_shows():
    paths = push_paths(DOCS)
    for p in rendered_paths():
        on_site = p in (docs.README, docs.METHOD) or p.startswith(f"{docs.FIGURES}/")
        assert triggers(paths, p) == on_site, p


def test_the_numbers_pr_commits_every_file_it_may_change():
    added = re.search(r"git add -- (.+)", BENCH.read_text(encoding="utf-8")).group(1).split()
    assert sorted(added) == sorted([proposal.PUBLISHED_PREFIX.rstrip("/"), *docs.BLOCKS, docs.FIGURES])


def test_the_workflows_use_the_names_the_gate_reads():
    bench = BENCH.read_text(encoding="utf-8")
    branch = re.search(r"BRANCH: (.+)", bench).group(1).strip()
    assert approval.BRANCH.fullmatch(branch.replace("${{ github.run_id }}", "18947312345"))
    assert f"-f context={approval.COMPARE_CONTEXT}" in bench
    assert "bench-accept-worse" == approval.ACCEPT_LABEL == proposal.ACCEPT_LABEL
    assert f"label create {approval.ACCEPT_LABEL} " in bench
    assert proposal.APPROVAL_CONTEXT == approval.APPROVAL_CONTEXT
    assert "pipeline/approval.py" in APPROVAL.read_text(encoding="utf-8")
    # The verdict comes from compare's exit codes.
    assert f'if [ "$CODE" = {compare.EXIT_WORSE} ]' in bench
    assert f"0|{compare.EXIT_CHANGED}|{compare.EXIT_WORSE})" in bench


def test_no_workflow_runs_the_benchmark_on_a_pull_request():
    on = BENCH.read_text(encoding="utf-8").split("\non:\n")[1].split("\npermissions:")[0]
    triggers_ = [line.strip() for line in on.splitlines() if re.match(r"^  [a-z_]+:", line)]
    assert triggers_ == ["push:", "workflow_dispatch:"]


USES = re.compile(r"^\s*(?:-\s+)?uses:\s*(\S+)", re.M)


@pytest.mark.parametrize("workflow", sorted(WORKFLOWS.glob("*.yml")), ids=lambda p: p.name)
def test_every_action_is_pinned_and_every_checkout_keeps_no_credentials(workflow):
    text = workflow.read_text(encoding="utf-8")
    for ref in USES.findall(text):
        if ref.startswith("./"):
            continue
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref), f"{workflow.name}: {ref} is not pinned by SHA"
    checkouts = text.count("uses: actions/checkout@")
    assert text.count("persist-credentials: false") >= checkouts
    assert re.search(r"^permissions:", text, re.M), f"{workflow.name}: no top-level permissions"


# The PR itself ---------------------------------------------------------------------

RUN = proposal.Run(commit="c0ffee" * 6 + "abcd", compare_exit=compare.EXIT_WORSE,
                   run_url="https://github.com/lBroth/nullpii/actions/runs/1", model="lBroth/nullpii@5dd3c799",
                   runner="GitHub-hosted ubuntu-24.04 runner, ONNX Runtime on its CPU")
CHANGED = ["README.md", "packages/eval/published-bench/ab1/scores-ab1-a.json"]


def test_the_body_says_what_was_measured_on_what_and_the_report():
    body = proposal.body(RUN, "**1 worse**\n\n- AB-1 a · keep\n", CHANGED)
    for said in (RUN.commit, settings.FROZEN_REVISION, settings.FROZEN_MANIFEST_SHA256, "CPU re-measurement",
                 RUN.runner, RUN.model, "**1 worse**", "- AB-1 a · keep", "Something got worse",
                 approval.ACCEPT_LABEL, "gh pr merge <number> --repo lBroth/nullpii --squash", "measured nullpii on CUDA"):
        assert said in body
    assert "auto" not in body.lower().replace("automatically", "")
    assert proposal.title(RUN) == f"chore(bench): CPU re-measurement of {RUN.commit[:12]} (something got worse)"


def test_the_body_of_numbers_that_only_moved_says_so():
    moved = proposal.Run(**{**RUN.__dict__, "compare_exit": compare.EXIT_CHANGED})
    body = proposal.body(moved, "**2 moved**\n", CHANGED)
    assert "none got worse" in body and "Something got worse" not in body
    assert proposal.title(moved).endswith("(numbers moved)")


def test_a_long_report_is_cut_at_a_line_and_points_to_the_whole():
    report = "".join(f"- row {i}: {'x' * 80}\n" for i in range(2000))
    body = proposal.body(RUN, report, CHANGED)
    assert len(body) < 65_536
    assert "all of it is the `bench-report` artifact" in body
    shown = body.split("## compare's report\n\n")[1].split("\n\nThe report is longer")[0]
    assert all(line.startswith("- row ") and line.endswith("x" * 80) for line in shown.splitlines())


def test_render_changing_nothing_or_anything_else_is_refused():
    with pytest.raises(proposal.ProposalError, match="changed no file"):
        proposal.check_changes([])
    with pytest.raises(proposal.ProposalError, match="src/defaults.ts"):
        proposal.check_changes(["README.md", "src/defaults.ts"])
    assert proposal.check_changes(CHANGED) == CHANGED


def test_every_kind_of_change_is_seen(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    for name in ("kept.md", "edited.md", "gone.md", "moved.md"):
        (tmp_path / name).write_text(name * 10)
    git("add", ".")
    git("commit", "-qm", "x")
    (tmp_path / "edited.md").write_text("changed")
    (tmp_path / "gone.md").unlink()
    (tmp_path / "dir with space").mkdir()
    git("mv", "moved.md", "dir with space/moved.md")
    (tmp_path / "new.md").write_text("new")
    assert proposal.changed_paths(tmp_path) == sorted(
        ["edited.md", "gone.md", "moved.md", "dir with space/moved.md", "new.md"])
