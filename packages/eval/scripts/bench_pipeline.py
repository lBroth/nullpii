#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The benchmark pipeline, one step per subcommand.

  fetch      download the frozen inputs at the pinned revision, check every
             file against the manifest, link the sets where bench_full.py's
             loaders read them (every other step reads the checked copy)
  reproduce  score the published run again from its frozen predictions and
             check each output they give is the published one (AB-1's
             scores, R3's 14 reports and 6 verdicts, PIIMB), and that the
             recipe declares every R3 output the published run has
  capture    run a built nullpii in one preset over one group of texts
             (ab1, r3, piimb) or its recognizer pack alone (recognizers);
             --resume continues an interrupted ab1, r3 or piimb capture
  score      every analysis of the published run, for nullpii's presets next
             to every other tool's frozen predictions
  reference  the published outputs, laid out as `score` writes its own,
             for a first `compare --published-names`
  compare    a run's numbers, claims and verdicts against a reference, like
             for like, at the precision the docs print them
             (pipeline/compare.py says which, and what it does not
             compare); exits 3 when something moved, is new or is dropped,
             4 when something got worse or is not measured any more, and
             fails when either side lacks an output or holds an
             undeclared nullpii row
  render     write published-bench/ from a run's out (or a reference, or
             published-bench/ itself), then every marked region of the
             README, METHOD and the model card, and the README's figures,
             from it (pipeline/render.py); --check writes nothing and
             exits 5 listing each file, region and figure that differs

The steps share a work directory:

  python bench_pipeline.py fetch --frozen F
  python bench_pipeline.py reproduce --frozen F --work W
  python bench_pipeline.py capture --frozen F --work W --dist D --preset default --group r3
  python bench_pipeline.py score --frozen F --work W
  python bench_pipeline.py compare --new W/out --reference R --report report.md
  python bench_pipeline.py render --run W/out
  python bench_pipeline.py render --run ../published-bench --check

Relative paths are taken from the directory the command runs in.
The frozen inputs hold real secrets: no step prints a row.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import capture, compare, frozen, recipe, render, reproduce, settings, texts  # noqa: E402
from pipeline.prose import RenderError  # noqa: E402
from pipeline.views import OUTPUTS_MARKER, PUBLISHED_NAMES, ViewError  # noqa: E402

GROUPS = ("ab1", "r3", "piimb", "recognizers")
# The recognizer pack alone runs in no preset and writes whole files.
UNPRESET_GROUP = "recognizers"
DEFAULT_PRESET = "default"
ROUNDTRIP_PRESET = "default"


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

    def texts(self, group: str) -> Path:
        return self.root / "texts" / f"{group}.jsonl"

    def recognizers(self) -> Path:
        return self.root / "recognizers"

    def piimb_spans(self, preset: str) -> Path:
        return self.root / "spans" / f"piimb-{preset}.jsonl"

    @property
    def out(self) -> Path:
        return self.root / "out"


def cmd_fetch(args: argparse.Namespace) -> None:
    f = frozen.download(args.frozen) if args.download else frozen.verify(args.frozen)
    frozen.install_datasets(f)
    pinned = f"{settings.FROZEN_REPO}@{settings.FROZEN_REVISION[:12]}"
    if args.download:
        print(f"frozen inputs downloaded at {pinned} and checked: {f.root}")
    else:
        print(f"frozen inputs: a local copy, not downloaded now ({f.root}); every file matches the manifest"
              f" of {pinned} (SHA-256 {settings.FROZEN_MANIFEST_SHA256[:12]}, pinned in settings.py)")


def _published_run_in_published_bench(step: str) -> None:
    """`reproduce` and `reference` read the published 0.5 run's AB-1 and
    PIIMB outputs from published-bench/; once `render` has written a run of
    the pipeline there, they are not there any more."""
    marker = settings.PUBLISHED / OUTPUTS_MARKER
    if marker.is_file() and json.loads(marker.read_text(encoding="utf-8"))["names"] != PUBLISHED_NAMES:
        raise SystemExit(f"{step}: {settings.PUBLISHED} holds a run of the pipeline ({OUTPUTS_MARKER}), not the"
                         " published run's outputs it reads")


def cmd_reproduce(args: argparse.Namespace) -> None:
    _published_run_in_published_bench("reproduce")
    reproduce.check(frozen.verify(args.frozen), args.work / "reproduce")
    print("the published run reproduces: AB-1's 3 score files, R3's 14 reports and 6 verdicts, and PIIMB"
          " (not checked: AB-1's recognizer coverage and the round trip, which need nullpii itself)")


def _capture_texts(work: Work, group: str, dist: Path, preset: str, resume: bool) -> None:
    keys = tuple(settings.AB1_GOLD) if group == "ab1" else (*settings.R3_GATED, *settings.R3_REPORTED)
    n = texts.write(keys, work.texts(group))
    capture.checkpoints(dist, work.texts(group), work.checkpoints, preset, resume)
    print(f"{group}: {n} texts captured as {settings.tool_name(preset)}")
    if group == "ab1" and preset == ROUNDTRIP_PRESET:
        result = capture.roundtrip(dist, work.texts(group), preset)
        (work.out / "ab1").mkdir(parents=True, exist_ok=True)
        (work.out / "ab1" / "roundtrip.json").write_text(json.dumps(result) + "\n", encoding="utf-8")


def _capture_recognizers(work: Work, dist: Path, f: frozen.Frozen) -> None:
    work.recognizers().mkdir(parents=True, exist_ok=True)
    for key, gold in settings.AB1_GOLD.items():
        capture.recognizer_spans(dist, f.dataset("ab1", gold), work.recognizers() / f"{key}.jsonl")


def cmd_capture(args: argparse.Namespace) -> None:
    work = Work(args.work)
    if args.group == UNPRESET_GROUP and (args.preset is not None or args.resume):
        raise SystemExit(f"capture --group {UNPRESET_GROUP} takes neither --preset nor --resume")
    f = frozen.verify(args.frozen)
    preset = args.preset or DEFAULT_PRESET
    if args.group in ("ab1", "r3"):
        _capture_texts(work, args.group, args.dist, preset, args.resume)
    elif args.group == "piimb":
        capture.piimb_texts(f.piimb_sentences, work.texts("piimb"))
        work.piimb_spans(preset).parent.mkdir(parents=True, exist_ok=True)
        capture.spans(args.dist, work.texts("piimb"), work.piimb_spans(preset), preset, args.resume)
    else:
        _capture_recognizers(work, args.dist, f)


def cmd_score(args: argparse.Namespace) -> None:
    work, f = Work(args.work), frozen.verify(args.frozen)
    frozen.install_competitors(f, work.checkpoints)
    recipe.score_ab1(work.checkpoints, settings.BASELINE, f.dataset("ab1"), work.out / "ab1")
    recipe.score_ab1_coverage(work.checkpoints, work.recognizers(), f.dataset("ab1"), work.out / "ab1")
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
    """Each file of a reference, relative to its --out, and its source: AB-1
    and PIIMB from published-bench, R3's reports and verdicts from the
    published run (the core regime's too, which `compare` lists as dropped)."""
    r3_reports = (*recipe.R3_RUNS, *recipe.CORE_LABEL_RUNS)
    r3_verdicts = (*recipe.VERDICTS, *recipe.CORE_LABEL_VERDICTS)
    return {
        **{rel: settings.PUBLISHED / rel for rel in compare.expected_files() if rel.startswith("ab1/")},
        **{compare.r3_file(r.name): f.r3_published / f"{r.name}.json" for r in r3_reports},
        **{compare.verdict_file(v.name): f.r3_published / f"{v.name}.log" for v in r3_verdicts},
        **{rel: settings.PUBLISHED / rel for rel in compare.expected_files()
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


def cmd_reference(args: argparse.Namespace) -> None:
    _published_run_in_published_bench("reference")
    f = frozen.verify(args.frozen)
    for kept in (settings.PUBLISHED.resolve(), f.root):
        if _inside(args.out, kept) or _inside(kept, args.out):
            raise SystemExit(f"reference --out {args.out} overlaps {kept}: give a directory of its own")
    sources = _reference_sources(f)
    _clear_reference(args.out, list(sources), args.force)
    for rel, source in sources.items():
        frozen.link(args.out / rel, source)
    marker = {"reference_of": f"{settings.FROZEN_REPO}@{settings.FROZEN_REVISION}", "files": sorted(sources)}
    (args.out / REFERENCE_MARKER).write_text(json.dumps(marker, indent=1) + "\n", encoding="utf-8")
    print(f"reference: {args.out} (AB-1 and PIIMB from published-bench, R3 from the published run)")


def cmd_compare(args: argparse.Namespace) -> int:
    layout = compare.PUBLISHED if args.published_names else compare.RUN
    changes = compare.compare(args.new, args.reference, layout)
    text = compare.report(changes)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return compare.exit_code(changes)


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


def _path(text: str) -> Path:
    """A path argument, absolute: the child processes run in another
    directory, and links made from it must hold from any directory."""
    return Path(text).resolve()


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("fetch")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--download", action="store_true", help="download first; else check what is there")
    s = sub.add_parser("reproduce")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--work", type=_path, required=True)
    s = sub.add_parser("capture")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--work", type=_path, required=True)
    s.add_argument("--dist", type=_path, required=True, help="the built nullpii (its dist/)")
    s.add_argument("--preset", choices=tuple(settings.PRESETS),
                   help=f"for ab1, r3 and piimb (default: {DEFAULT_PRESET})")
    s.add_argument("--group", choices=GROUPS, required=True)
    s.add_argument("--resume", action="store_true",
                   help="keep the rows an interrupted capture wrote and do the rest (ab1, r3, piimb)")
    s = sub.add_parser("score")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--work", type=_path, required=True)
    s = sub.add_parser("reference")
    s.add_argument("--frozen", type=_path, required=True)
    s.add_argument("--out", type=_path, required=True,
                   help="an empty directory, or a previous reference (its REFERENCE.json)")
    s.add_argument("--force", action="store_true",
                   help="replace the files a reference writes in a non-empty --out that is no reference")
    s = sub.add_parser("compare")
    s.add_argument("--new", type=_path, required=True)
    s.add_argument("--reference", type=_path, required=True)
    s.add_argument("--published-names", action="store_true",
                   help="the reference is `reference`'s, in the published run's row names (a first compare): like for like, the core regime listed as dropped")
    s.add_argument("--report", type=_path)
    s = sub.add_parser("render")
    s.add_argument("--run", type=_path, required=True,
                   help="a run's out, a reference (its REFERENCE.json) or published-bench itself")
    s.add_argument("--check", action="store_true", help="write nothing; exit 5 listing what differs")
    return p


COMMANDS = {
    "fetch": cmd_fetch, "reproduce": cmd_reproduce, "capture": cmd_capture,
    "score": cmd_score, "reference": cmd_reference, "compare": cmd_compare, "render": cmd_render,
}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return COMMANDS[args.command](args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
