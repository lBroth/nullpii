#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""The benchmark pipeline, one step per subcommand.

  fetch      download the frozen inputs at the pinned revision, check every
             file against the manifest, put the sets where the scorers read them
  reproduce  score the published run again from its frozen predictions and
             check every output is the published one
  capture    run a built nullpii in one preset over one group of texts
             (ab1, r3, piimb) or its recognizer pack alone (recognizers)
  score      every analysis of the published run, for nullpii's presets next
             to every other tool's frozen predictions
  reference  the published outputs, laid out as `score` writes its own,
             for a first `compare`
  compare    a run's numbers and claims against a reference, at the precision
             the docs print them; exits 3 when something moved, 4 when
             something got worse

The steps share a work directory:

  python bench_pipeline.py fetch --frozen F
  python bench_pipeline.py reproduce --frozen F --work W
  python bench_pipeline.py capture --frozen F --work W --dist D --preset default --group r3
  python bench_pipeline.py score --frozen F --work W
  python bench_pipeline.py compare --new W/out --reference R --report report.md

The frozen inputs hold real secrets: no step prints a row.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import capture, compare, frozen, recipe, reproduce, settings, texts  # noqa: E402

GROUPS = ("ab1", "r3", "piimb", "recognizers")
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
    print(f"frozen inputs checked: {settings.FROZEN_REPO}@{settings.FROZEN_REVISION[:12]}")


def cmd_reproduce(args: argparse.Namespace) -> None:
    reproduce.check(frozen.verify(args.frozen), args.work / "reproduce")
    print("the published run reproduces: every AB-1 and R3 output, and every verdict")


def _capture_texts(work: Work, group: str, dist: Path, preset: str, resume: bool) -> None:
    keys = tuple(settings.AB1_GOLD) if group == "ab1" else (*settings.R3_GATED, *settings.R3_REPORTED)
    n = texts.write(keys, work.texts(group))
    capture.checkpoints(dist, work.texts(group), work.checkpoints, preset, resume)
    print(f"{group}: {n} texts captured as {settings.tool_name(preset)}")
    if group == "ab1" and preset == ROUNDTRIP_PRESET:
        result = capture.roundtrip(dist, work.texts(group), preset)
        (work.out / "ab1").mkdir(parents=True, exist_ok=True)
        (work.out / "ab1" / "roundtrip.json").write_text(json.dumps(result) + "\n", encoding="utf-8")


def cmd_capture(args: argparse.Namespace) -> None:
    work = Work(args.work)
    frozen.verify(args.frozen)
    if args.group in ("ab1", "r3"):
        _capture_texts(work, args.group, args.dist, args.preset, args.resume)
    elif args.group == "piimb":
        capture.piimb_texts(work.texts("piimb"))
        work.piimb_spans(args.preset).parent.mkdir(parents=True, exist_ok=True)
        capture.spans(args.dist, work.texts("piimb"), work.piimb_spans(args.preset), args.preset)
    else:
        work.recognizers().mkdir(parents=True, exist_ok=True)
        for key, gold in settings.AB1_GOLD.items():
            capture.recognizer_spans(args.dist, settings.RESULTS / "ab1" / gold, work.recognizers() / f"{key}.jsonl")


def cmd_score(args: argparse.Namespace) -> None:
    work, f = Work(args.work), frozen.verify(args.frozen)
    frozen.install_competitors(f, work.checkpoints)
    recipe.score_ab1(work.checkpoints, settings.BASELINE, work.out / "ab1")
    recipe.score_ab1_coverage(work.checkpoints, work.recognizers(), work.out / "ab1")
    recipe.score_r3(work.run, settings.BASELINE, f.openmed_no_output, work.out / "r3")
    for name, text in recipe.verdicts(work.out / "r3", settings.BASELINE, settings.OTHER_NULLPII).items():
        (work.out / "r3" / f"{name}.txt").write_text(text, encoding="utf-8")
    sentences = settings.RESULTS / "ab-loop" / "piimb" / settings.PIIMB_SENTENCES
    for preset in settings.PRESETS:
        recipe.score_piimb(sentences, work.piimb_spans(preset), f.piimb_leaderboard,
                           settings.tool_name(preset), work.out / "piimb" / f"piimb-{preset}.json")
    print(f"scored: {work.out}")


def _link_all(sources: list[Path], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for source in sources:
        (dest / source.name).unlink(missing_ok=True)
        (dest / source.name).symlink_to(source.resolve())


def cmd_reference(args: argparse.Namespace) -> None:
    f = frozen.verify(args.frozen)
    _link_all(sorted((settings.PUBLISHED / "ab1").glob("*.json")), args.out / "ab1")
    _link_all([f.r3_published / f"{run.name}.json" for run in recipe.R3_RUNS], args.out / "r3")
    print(f"reference: {args.out} (AB-1 from published-bench, R3 from the published run)")


def cmd_compare(args: argparse.Namespace) -> int:
    aliases = settings.PUBLISHED_ALIASES if args.published_names else {}
    changes = compare.compare(args.new, args.reference, aliases)
    text = compare.report(changes)
    if args.report:
        args.report.write_text(text, encoding="utf-8")
    print(text)
    return compare.exit_code(changes)


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("fetch")
    s.add_argument("--frozen", type=Path, required=True)
    s.add_argument("--download", action="store_true", help="download first; else check what is there")
    s = sub.add_parser("reproduce")
    s.add_argument("--frozen", type=Path, required=True)
    s.add_argument("--work", type=Path, required=True)
    s = sub.add_parser("capture")
    s.add_argument("--frozen", type=Path, required=True)
    s.add_argument("--work", type=Path, required=True)
    s.add_argument("--dist", type=Path, required=True, help="the built nullpii (its dist/)")
    s.add_argument("--preset", choices=tuple(settings.PRESETS), default=ROUNDTRIP_PRESET)
    s.add_argument("--group", choices=GROUPS, required=True)
    s.add_argument("--resume", action="store_true")
    s = sub.add_parser("score")
    s.add_argument("--frozen", type=Path, required=True)
    s.add_argument("--work", type=Path, required=True)
    s = sub.add_parser("reference")
    s.add_argument("--frozen", type=Path, required=True)
    s.add_argument("--out", type=Path, required=True)
    s = sub.add_parser("compare")
    s.add_argument("--new", type=Path, required=True)
    s.add_argument("--reference", type=Path, required=True)
    s.add_argument("--published-names", action="store_true",
                   help="the reference uses the published run's row names (a first compare)")
    s.add_argument("--report", type=Path)
    return p


COMMANDS = {
    "fetch": cmd_fetch, "reproduce": cmd_reproduce, "capture": cmd_capture,
    "score": cmd_score, "reference": cmd_reference, "compare": cmd_compare,
}


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    return COMMANDS[args.command](args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
