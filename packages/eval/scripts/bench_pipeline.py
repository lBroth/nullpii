#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The benchmark pipeline, one step per subcommand.

  fetch      download the frozen inputs at the pinned revision, check every
             file against the manifest, link the sets where bench_full.py's
             loaders read them (every other step reads the checked copy)
  reproduce  score the published run again from its frozen predictions and
             check each output they give is the published one (AB-1's
             scores and B1's UUID split, R3's 14 reports and 6 verdicts,
             PIIMB), and that the
             recipe declares every R3 output the published run has
  capture    run a built nullpii in one preset over one group of texts
             (ab1, r3, piimb), the mask-restore round trip over AB-1's
             (roundtrip), or its recognizer pack alone (recognizers);
             --shard K/N runs one of N parts of a group (pipeline/parts.py),
             --resume continues an interrupted capture, --limit N (dry runs
             only) keeps the first N texts of each set and is never scored
  score      put the parts together, then every analysis of the published
             run, for nullpii's presets next to every other tool's frozen
             predictions; refuses to start until every capture is there
  reference  the published outputs, laid out as `score` writes its own,
             for a first `compare --published-names`
  compare    a run's numbers, claims and verdicts against a reference, like
             for like, at the precision the docs print them
             (pipeline/compare.py says which, and what it does not
             compare); exits 3 when something moved, is new or is dropped,
             4 when something got worse or is not measured any more, and
             fails when either side lacks an output or holds an
             undeclared nullpii row; --published-bench compares with what
             published-bench/ holds (pipeline/README: the reference)
  render     write published-bench/ from a run's out (or a reference, or
             published-bench/ itself), then every marked region of the
             README, METHOD and the model card, and the README's figures,
             from it (pipeline/render.py); --check writes nothing and
             exits 5 listing each file, region and figure that differs
  propose    after `render`, check it changed only what a numbers PR may
             change, and write that PR's title and body (pipeline/proposal.py)
  measured-differs
             exit 3 when published-bench says it measured another nullpii
             version or model than a run did (a numbers PR is due), 0 when not
  model-card check that MODEL_CARD.md is the card of the release being
             tagged, and with --upload put it on the model repository
             (pipeline/card.py)

The steps share a work directory:

  python bench_pipeline.py fetch --frozen F
  python bench_pipeline.py reproduce --frozen F --work W
  python bench_pipeline.py capture --frozen F --work W --dist D --preset default --group r3
  python bench_pipeline.py capture --frozen F --work W --dist D --preset default --group r3 --shard 2/6
  python bench_pipeline.py score --frozen F --work W
  python bench_pipeline.py compare --new W/out --reference R --report report.md
  python bench_pipeline.py compare --new W/out --published-bench --frozen F --report report.md
  python bench_pipeline.py render --run W/out
  python bench_pipeline.py render --run ../published-bench --check

Relative paths are taken from the directory the command runs in.
The frozen inputs hold real secrets: no step prints a row.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import (  # noqa: E402
    artifact, build, capture, card, compare, frozen, parts, proposal, recipe, render, reproduce, settings, texts, views,
)
from pipeline.parts import Shard  # noqa: E402
from pipeline.prose import RenderError  # noqa: E402
from pipeline.views import ViewError  # noqa: E402

GROUPS = (*parts.TEXT_GROUPS, "recognizers")
# The recognizer pack alone runs in no preset, on whole files, in one part.
UNPRESET_GROUP = "recognizers"
DEFAULT_PRESET = "default"
# The round trip is measured in the configuration a user gets.
ROUNDTRIP_PRESET = "default"
# The captures `score` needs: each text group in each preset it is
# published in.
CAPTURES = tuple(
    (group, preset)
    for group in parts.TEXT_GROUPS
    for preset in (settings.PRESETS if group != parts.ROUNDTRIP_GROUP else (ROUNDTRIP_PRESET,))
)


@dataclass(frozen=True)
class Work:
    """The work directory the steps share."""

    root: Path

    @property
    def run(self) -> Path:
        """A run in char_metrics.py's layout: `checkpoints/` inside."""
        return self.root / "run"

    @property
    def checkpoints(self) -> Path:
        return self.run / "checkpoints"

    def texts(self, name: str) -> Path:
        return self.root / "texts" / f"{name}.jsonl"

    @property
    def parts(self) -> Path:
        return self.root / "parts"

    def part(self, group: str, preset: str, shard: Shard) -> Path:
        return self.parts / parts.part_name(group, preset, shard)

    @property
    def limited(self) -> Path:
        """Marks a work directory a limited (dry-run) capture wrote into."""
        return self.root / parts.LIMIT_MARKER

    def recognizers(self) -> Path:
        return self.root / "recognizers"

    def piimb_spans(self, preset: str) -> Path:
        return self.root / "spans" / parts.piimb_file(preset)

    @property
    def out(self) -> Path:
        return self.root / "out"

    @property
    def roundtrip(self) -> Path:
        return self.out / compare.ROUNDTRIP_FILE

    @property
    def targets(self) -> parts.Targets:
        return parts.Targets(self.checkpoints, self.root / "spans", self.roundtrip)


def cmd_fetch(args: argparse.Namespace) -> None:
    only = frozen.SETS if args.sets_only else None
    f = frozen.download(args.frozen, only) if args.download else frozen.verify(args.frozen, only=only)
    frozen.install_datasets(f)
    pinned = f"{settings.FROZEN_REPO}@{settings.FROZEN_REVISION[:12]}"
    what = "the frozen sets" if args.sets_only else "frozen inputs"
    if args.download:
        print(f"{what} downloaded at {pinned} and checked: {f.root}")
    else:
        print(f"{what}: a local copy, not downloaded now ({f.root}); every file matches the manifest"
              f" of {pinned} (SHA-256 {settings.FROZEN_MANIFEST_SHA256[:12]}, pinned in settings.py)")


def cmd_reproduce(args: argparse.Namespace) -> None:
    reproduce.check(frozen.verify(args.frozen), args.work / "reproduce")
    print("the published run reproduces: AB-1's 3 score files and B1's UUID split, R3's 14 reports and 6 verdicts, and PIIMB"
          " (not checked: AB-1's recognizer coverage and the round trip, which need nullpii itself)")


def _group_texts(work: Work, group: str, f: frozen.Frozen) -> Path:
    """Every text of `group`, in capture order (the round trip runs on
    AB-1's), written whole or not at all."""
    if group == parts.PIIMB_GROUP:
        capture.piimb_texts(f.piimb_sentences, work.texts(group))
        return work.texts(group)
    source = "ab1" if group in ("ab1", parts.ROUNDTRIP_GROUP) else "r3"
    keys = tuple(settings.AB1_GOLD) if source == "ab1" else (*settings.R3_GATED, *settings.R3_REPORTED)
    texts.write(keys, work.texts(source))
    return work.texts(source)


def _run_capture(group: str, dist: Path, texts_path: Path, part: Path, preset: str, resume: bool) -> None:
    if group in parts.CHECKPOINT_GROUPS:
        capture.checkpoints(dist, texts_path, part, preset, resume)
    elif group == parts.PIIMB_GROUP:
        capture.spans(dist, texts_path, part / parts.piimb_file(preset), preset, resume)
    else:
        result = artifact.check_roundtrip(capture.roundtrip(dist, texts_path, preset))
        (part / parts.ROUNDTRIP_FILE).write_text(json.dumps(result) + "\n", encoding="utf-8")


def _capture_part(work: Work, group: str, f: frozen.Frozen, args: argparse.Namespace) -> None:
    preset = args.preset or DEFAULT_PRESET
    if group == parts.ROUNDTRIP_GROUP and preset != ROUNDTRIP_PRESET:
        raise SystemExit(f"capture --group roundtrip runs in the {ROUNDTRIP_PRESET} preset only, not {preset}")
    shard = Shard.parse(args.shard) if args.shard else parts.WHOLE
    part = work.part(group, preset, shard)
    part.mkdir(parents=True, exist_ok=True)
    (part / parts.PART_MARKER).unlink(missing_ok=True)
    full = _group_texts(work, group, f)
    suffix = f"-limit{args.limit}" if args.limit is not None else ""
    shard_texts = work.texts(f"{group}-{shard.label}{suffix}")
    rows, totals = parts.select(full, shard_texts, shard, args.limit)
    if args.limit is not None:
        work.limited.write_text(json.dumps({"limit": args.limit}) + "\n", encoding="utf-8")
    if rows:
        _run_capture(group, args.dist, shard_texts, part, preset, args.resume)
    elif group == parts.ROUNDTRIP_GROUP:
        (part / parts.ROUNDTRIP_FILE).write_text(json.dumps(
            {"docs": 0, "masked": 0, "roundtrip_failures": 0, "failing_idx": {}}) + "\n", encoding="utf-8")
    parts.check_output(part, group, preset, rows)
    parts.write_marker(part, group, preset, shard, rows, totals, args.limit, build.measured(views.ROOT))
    print(f"{part.name}: {sum(rows.values())} of {sum(totals.values())} texts captured as {settings.tool_name(preset)}"
          + (f" (limited to {args.limit} per set: a dry run, never scored)" if args.limit is not None else ""))


def _capture_recognizers(work: Work, dist: Path, f: frozen.Frozen) -> None:
    work.recognizers().mkdir(parents=True, exist_ok=True)
    for key, gold in settings.AB1_GOLD.items():
        out = work.recognizers() / f"{key}.jsonl"
        capture.recognizer_spans(dist, f.dataset("ab1", gold), out)
    artifact.check_recognizers(work.recognizers())


def cmd_capture(args: argparse.Namespace) -> None:
    work = Work(args.work)
    if args.group == UNPRESET_GROUP and (args.preset, args.resume, args.shard, args.limit) != (None, False, None, None):
        raise SystemExit(f"capture --group {UNPRESET_GROUP} takes none of --preset, --resume, --shard, --limit")
    if args.limit is not None and args.limit < 1:
        raise SystemExit("capture --limit takes a number of texts per set, 1 or more")
    f = frozen.verify(args.frozen, only=frozen.SETS)
    if args.group == UNPRESET_GROUP:
        _capture_recognizers(work, args.dist, f)
    else:
        _capture_part(work, args.group, f, args)


def missing_captures(work: Work, assembled: parts.Assembled) -> list[str]:
    """The captures `score` needs that are not there: a group in a preset
    with no part at all, and the recognizer pack's spans."""
    missing = [f"capture --group {g} --preset {p}" for g, p in CAPTURES if (g, p) not in assembled.captures]
    missing += [f"capture --group {UNPRESET_GROUP} ({key})" for key in settings.AB1_GOLD
                if not (work.recognizers() / f"{key}.jsonl").is_file()]
    return missing


def cmd_score(args: argparse.Namespace) -> None:
    work, f = Work(args.work), frozen.verify(args.frozen)
    if work.limited.is_file():
        raise SystemExit(f"score: {work.root} holds a limited capture (--limit, a dry run), which is never scored;"
                         " capture into a new work directory")
    try:
        assembled = parts.assemble(work.parts, work.targets)
    except parts.PartError as e:
        raise SystemExit(f"score: {e}") from e
    missing = missing_captures(work, assembled)
    if missing:
        raise SystemExit("score needs every capture; not captured:\n  " + "\n  ".join(missing))
    artifact.check_recognizers(work.recognizers())
    frozen.install_competitors(f, work.checkpoints)
    work.out.mkdir(parents=True, exist_ok=True)
    (work.out / views.MEASURED_FILE).write_text(json.dumps(assembled.measured, indent=1, sort_keys=True) + "\n",
                                                encoding="utf-8")
    recipe.score_ab1(work.checkpoints, settings.BASELINE, f.dataset("ab1"), work.out / "ab1")
    recipe.score_ab1_coverage(work.checkpoints, work.recognizers(), f.dataset("ab1"), work.out / "ab1")
    recipe.score_ab1_kind_split(work.checkpoints, f.dataset("ab1"), work.out / "ab1")
    recipe.score_r3(work.run, settings.BASELINE, f.openmed_no_output, work.out / "r3")
    for name, text in recipe.verdicts(work.out / "r3", settings.BASELINE, settings.OTHER_NULLPII).items():
        (work.out / "r3" / f"{name}.txt").write_text(text, encoding="utf-8")
    for preset in settings.PRESETS:
        recipe.score_piimb(f.piimb_sentences, work.piimb_spans(preset), f.piimb_leaderboard,
                           settings.tool_name(preset), work.out / "piimb" / f"piimb-{preset}.json")
    print(f"scored: {work.out}")


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


REFERENCE_MARKER = "REFERENCE.json"


def _reference_sources(f: frozen.Frozen) -> dict[str, Path]:
    """Each file of a reference, relative to its --out, and its source in
    the frozen copy: AB-1 and PIIMB from the published run's outputs, R3's
    reports and verdicts from the published run (the core regime's too,
    which `compare` lists as dropped)."""
    r3_reports = (*recipe.R3_RUNS, *recipe.CORE_LABEL_RUNS)
    r3_verdicts = (*recipe.VERDICTS, *recipe.CORE_LABEL_VERDICTS)
    return {
        **{rel: f.published_outputs / rel for rel in compare.expected_files() if rel.startswith("ab1/")},
        **{compare.r3_file(r.name): f.r3_published / f"{r.name}.json" for r in r3_reports},
        **{compare.verdict_file(v.name): f.r3_published / f"{v.name}.log" for v in r3_verdicts},
        **{rel: f.published_outputs / rel for rel in compare.expected_files()
           if rel.startswith("piimb/") and rel not in settings.PUBLISHED_ABSENT},
    }


def _clear_reference(out: Path, rels: list[str], force: bool) -> None:
    """Make room in `out` for a reference: an empty or missing directory is
    used as it is; a previous reference (its marker file) has the files its
    marker lists removed; with `force`, the files a reference writes are
    removed. Any other non-empty directory is refused. Nothing else in
    `out` is ever removed."""
    if not out.exists() or not any(out.iterdir()):
        return
    marker = out / REFERENCE_MARKER
    if marker.is_file():
        rels = sorted(set(rels) | set(json.loads(marker.read_text(encoding="utf-8"))["files"]))
    elif not force:
        raise SystemExit(f"reference --out {out} is not empty and holds no {REFERENCE_MARKER} (not a previous"
                         " reference): give an empty directory, or --force to replace the files a reference writes")
    for rel in (*rels, REFERENCE_MARKER):
        target = out / rel
        if target.is_symlink() or target.is_file():
            target.unlink()


def lay_reference(f: frozen.Frozen, out: Path, force: bool = False) -> None:
    """The published outputs in `out`, as links into the frozen copy."""
    for kept in (settings.PUBLISHED.resolve(), f.root):
        if _inside(out, kept) or _inside(kept, out):
            raise SystemExit(f"reference --out {out} overlaps {kept}: give a directory of its own")
    sources = _reference_sources(f)
    _clear_reference(out, list(sources), force)
    for rel, source in sources.items():
        frozen.link(out / rel, source)
    marker = {"reference_of": f"{settings.FROZEN_REPO}@{settings.FROZEN_REVISION}", "files": sorted(sources)}
    (out / REFERENCE_MARKER).write_text(json.dumps(marker, indent=1) + "\n", encoding="utf-8")


def cmd_reference(args: argparse.Namespace) -> None:
    lay_reference(frozen.verify(args.frozen), args.out, args.force)
    print(f"reference: {args.out} (the published run's outputs, from the frozen copy)")


def _write_report(changes: list[compare.Change], against: str, path: Path | None) -> int:
    text = compare.report(changes) + (f"\n\nCompared with {against}.\n" if against else "")
    if path:
        path.write_text(text, encoding="utf-8")
    print(text)
    return compare.exit_code(changes)


def cmd_compare(args: argparse.Namespace) -> int:
    if not args.published_bench:
        if args.frozen is not None:
            raise SystemExit("compare: --frozen goes with --published-bench")
        layout = compare.PUBLISHED if args.published_names else compare.RUN
        return _write_report(compare.compare(args.new, args.reference, layout), "", args.report)
    if args.published_names or args.frozen is None:
        raise SystemExit("compare --published-bench takes --frozen, and reads the row names from published-bench")
    names = views.layout_names(settings.PUBLISHED)
    if names == views.RUN_NAMES:
        against = f"published-bench/, a run of the pipeline ({views.measured_version(settings.PUBLISHED, names)})"
        return _write_report(compare.compare(args.new, settings.PUBLISHED, compare.RUN), against, args.report)
    f = frozen.verify(args.frozen)
    with tempfile.TemporaryDirectory(prefix="bench-reference-") as tmp:
        lay_reference(f, Path(tmp))
        against = (f"the published {views.PUBLISHED_VERSION} run (published-bench/ holds it), laid out from"
                   f" {settings.FROZEN_REPO}@{settings.FROZEN_REVISION[:12]}, like for like")
        return _write_report(compare.compare(args.new, Path(tmp), compare.PUBLISHED), against, args.report)


EXIT_RENDER_DIFFERS = 5


def cmd_render(args: argparse.Namespace) -> int:
    try:
        if args.check:
            diffs = render.check(args.run)
        else:
            diffs = render.render(args.run)
    except (RenderError, ViewError, render.DocError) as e:
        raise SystemExit(f"render: {e}") from e
    if args.check:
        if diffs:
            print("these differ from what the outputs give (run `render --run <out>` to write them):")
            print("\n".join(f"  {d}" for d in diffs))
            return EXIT_RENDER_DIFFERS
        print(f"published-bench, the docs and the figures say what {args.run} holds")
        return 0
    print("\n".join(f"rendered: {d}" for d in diffs) if diffs else "rendered: nothing changed")
    return 0


def cmd_propose(args: argparse.Namespace) -> None:
    try:
        changed = proposal.check_changes(proposal.changed_paths(views.ROOT))
        measured = views.measured(args.run, views.RUN_NAMES)
    except (proposal.ProposalError, ViewError) as e:
        raise SystemExit(f"propose: {e}") from e
    run = proposal.Run(commit=args.commit, compare_exit=args.compare_exit, run_url=args.run_url,
                       runner=args.runner, measured=measured)
    report = args.report.read_text(encoding="utf-8")
    args.title_out.write_text(proposal.title(run) + "\n", encoding="utf-8")
    args.body_out.write_text(proposal.body(run, report, changed), encoding="utf-8")
    print(f"propose: {len(changed)} files changed, all published outputs, docs or figures")


def cmd_measured_differs(args: argparse.Namespace) -> int:
    """0 when published-bench says it measured the run's nullpii and model,
    3 when not (a numbers PR is due even if no number moved)."""
    try:
        run = views.measured(args.run, views.RUN_NAMES)
        names = views.layout_names(settings.PUBLISHED)
        published = views.measured(settings.PUBLISHED, names)
    except ViewError as e:
        raise SystemExit(f"measured-differs: {e}") from e
    keys = ("nullpii", "model", "backend")
    if names == views.RUN_NAMES and all(run[k] == published[k] for k in keys):
        print(f"published-bench measured nullpii {run['nullpii']} with {run['model']}, as this run did")
        return 0
    print(f"published-bench measured nullpii {published['nullpii']} with {published['model']} on {published['backend']};"
          f" this run nullpii {run['nullpii']} with {run['model']} on {run['backend']}")
    return compare.EXIT_CHANGED


def cmd_model_card(args: argparse.Namespace) -> None:
    try:
        checked = card.check(views.ROOT, args.tag)
        if args.upload:
            print(card.upload(views.ROOT, checked))
        else:
            print(f"model-card: {card.CARD} is the card of {checked.version}; not uploaded (no --upload)")
    except card.CardError as e:
        raise SystemExit(f"model-card: {e}") from e


def _path(text: str) -> Path:
    """A path argument, absolute: the child processes run in another
    directory, and links made from it must hold from any directory."""
    return Path(text).resolve()


def _add_capture(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("capture")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--work", type=_path, required=True)
    s.add_argument("--dist", type=_path, required=True, help="the built nullpii (its dist/)")
    s.add_argument("--preset", choices=tuple(settings.PRESETS),
                   help=f"for ab1, r3 and piimb (default: {DEFAULT_PRESET}); roundtrip runs in {ROUNDTRIP_PRESET}")
    s.add_argument("--group", choices=GROUPS, required=True)
    s.add_argument("--shard", help="K/N: capture shard K of N of the group (default 1/1, the whole group)")
    s.add_argument("--resume", action="store_true",
                   help="keep the rows an interrupted capture of this part wrote and do the rest")
    s.add_argument("--limit", type=int,
                   help="dry runs only: the first N texts of each set; `score` refuses the work directory")


def _add_compare(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("compare")
    s.add_argument("--new", type=_path, required=True)
    against = s.add_mutually_exclusive_group(required=True)
    against.add_argument("--reference", type=_path)
    against.add_argument("--published-bench", action="store_true",
                         help="against what published-bench/ holds: a run of the pipeline as it is, or the published"
                              " run laid out from --frozen and read with --published-names")
    s.add_argument("--frozen", type=_path, help="with --published-bench")
    s.add_argument("--published-names", action="store_true",
                   help="the reference is `reference`'s, in the published run's row names (a first compare): like for like, the core regime listed as dropped")
    s.add_argument("--report", type=_path)


def _add_propose(sub: argparse._SubParsersAction) -> None:
    s = sub.add_parser("propose")
    s.add_argument("--run", type=_path, required=True, help="the run's out (its MEASURED.json)")
    s.add_argument("--report", type=_path, required=True, help="compare's report")
    s.add_argument("--compare-exit", type=int, required=True,
                   choices=(compare.EXIT_UNCHANGED, compare.EXIT_CHANGED, compare.EXIT_WORSE))
    s.add_argument("--commit", required=True, help="the commit measured")
    s.add_argument("--run-url", required=True)
    s.add_argument("--runner", required=True, help="what ran it, e.g. 'GitHub-hosted ubuntu-24.04 runners'")
    s.add_argument("--title-out", type=_path, required=True)
    s.add_argument("--body-out", type=_path, required=True)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("fetch")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--download", action="store_true", help="download first; else check what is there")
    s.add_argument("--sets-only", action="store_true",
                   help="the frozen sets alone (datasets/), all a capture reads; score and reproduce need the rest")
    s = sub.add_parser("reproduce")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--work", type=_path, required=True)
    _add_capture(sub)
    s = sub.add_parser("score")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--work", type=_path, required=True)
    s = sub.add_parser("reference")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--out", type=_path, required=True,
                   help="an empty directory, or a previous reference (its REFERENCE.json)")
    s.add_argument("--force", action="store_true",
                   help="replace the files a reference writes in a non-empty --out that is no reference")
    _add_compare(sub)
    s = sub.add_parser("render")
    s.add_argument("--run", type=_path, required=True,
                   help="a run's out, a reference (its REFERENCE.json) or published-bench itself")
    s.add_argument("--check", action="store_true", help="write nothing; exit 5 listing what differs")
    _add_propose(sub)
    s = sub.add_parser("measured-differs")
    s.add_argument("--run", type=_path, required=True, help="a run's out (its MEASURED.json)")
    s = sub.add_parser("model-card")
    s.add_argument("--tag", required=True, help="the release tag, vX.Y.Z")
    s.add_argument("--upload", action="store_true", help=f"upload it to {card.MODEL_REPO} (token: {card.TOKEN_ENV})")
    return p


COMMANDS = {
    "fetch": cmd_fetch, "reproduce": cmd_reproduce, "capture": cmd_capture,
    "score": cmd_score, "reference": cmd_reference, "compare": cmd_compare, "render": cmd_render,
    "propose": cmd_propose, "measured-differs": cmd_measured_differs, "model-card": cmd_model_card,
}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return COMMANDS[args.command](args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
