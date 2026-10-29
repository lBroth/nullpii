# SPDX-License-Identifier: Apache-2.0
"""Run a built nullpii over the frozen texts: its spans as checkpoints, its
recognizer pack alone, and the mask-restore round trip. Each step is a
script of the eval kit, run as a child process that must succeed."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from pipeline import settings


def run(args: list[str], cwd: Path = settings.EVAL) -> str:
    """Run `args` and return its standard output. A failure raises with the
    command and its exit code; the child's own stderr goes to ours."""
    done = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, args[:2]))} … exited with {done.returncode}")
    return done.stdout


def checkpoints(dist: Path, texts: Path, out_dir: Path, preset: str, resume: bool = False) -> None:
    """nullpii's spans on every row of `texts`, as `<tool>-<dataset>.jsonl`
    checkpoints in `out_dir`, under the preset's tool name."""
    args = [
        settings.NODE, str(settings.SCORE_CAPTURE),
        "--dist", str(dist), "--texts", str(texts),
        "--checkpoints", str(out_dir), "--tool", settings.tool_name(preset),
        "--config", settings.preset_config(preset),
    ]
    run(args + (["--resume", "1"] if resume else []))


def spans(dist: Path, texts: Path, out: Path, preset: str, resume: bool = False) -> None:
    """nullpii's spans on every row of `texts` into one file (PIIMB's form).
    With `resume`, the rows `out` already holds are kept and skipped;
    without it, `out` is written anew."""
    args = [
        settings.NODE, str(settings.SCORE_CAPTURE),
        "--dist", str(dist), "--texts", str(texts), "--out", str(out),
        "--config", settings.preset_config(preset),
    ]
    run(args + (["--resume", "1"] if resume else []))


def recognizer_spans(dist: Path, gold: Path, out: Path) -> None:
    """The spans of nullpii's recognizer pack alone on `gold`'s documents."""
    run([settings.NODE, str(settings.RECOGNIZER_SPANS), "--dist", str(dist), "--gold", str(gold), "--out", str(out)])


def roundtrip(dist: Path, texts: Path, preset: str) -> dict:
    """restore(mask(x)) == x on every row of `texts`: the counts it prints."""
    out = run([
        settings.NODE, str(settings.ROUNDTRIP), "--dist", str(dist), "--texts", str(texts),
        "--config", settings.preset_config(preset),
    ])
    lines = [line for line in out.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("roundtrip.mjs printed no result")
    return json.loads(lines[-1])


def piimb_texts(sentences: Path, out: Path) -> None:
    """PIIMB's `sentences` (the checked frozen copy's) as rows nullpii runs
    on, written whole or not at all (see `texts.write`)."""
    out.parent.mkdir(parents=True, exist_ok=True)
    partial = out.with_name(f"{out.name}.{os.getpid()}.partial")
    run([sys.executable, "-I", str(settings.PIIMB_SCORE), "export", "--data", str(sentences), "--out", str(partial)])
    os.replace(partial, out)
