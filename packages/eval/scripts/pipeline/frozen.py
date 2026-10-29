# SPDX-License-Identifier: Apache-2.0
"""The frozen inputs: download them at the pinned revision, check every
file against the manifest, and put them where the scorers read them.

Nothing here prints a row: the frozen repository holds real secrets."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from pipeline import settings

HASH_CHUNK = 1 << 20


class FrozenError(Exception):
    """The frozen inputs are not the pinned ones, or cannot be installed."""


@dataclass(frozen=True)
class Frozen:
    """The paths inside a checked copy of the frozen repository."""

    root: Path

    def dataset(self, *parts: str) -> Path:
        return self.root.joinpath("datasets", *parts)

    def predictions(self, *parts: str) -> Path:
        return self.root.joinpath("predictions", *parts)

    @property
    def ab1_checkpoints(self) -> Path:
        return self.predictions("ab1", "checkpoints")

    @property
    def r3_run(self) -> Path:
        """The published R3 run: its `checkpoints/` and scoring outputs."""
        return self.predictions("r3")

    @property
    def r3_published(self) -> Path:
        return self.predictions("r3", "published-run")

    @property
    def openmed_no_output(self) -> Path:
        return self.predictions("r3", "openmed-no-output", "openmed-union.json")

    @property
    def piimb_leaderboard(self) -> Path:
        return self.predictions("piimb", "leaderboard")

    @property
    def piimb_published_spans(self) -> Path:
        return self.predictions("piimb", "nullpii-spans-v2.jsonl")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _listed_files(root: Path) -> set[str]:
    return {
        str(p.relative_to(root))
        for p in root.rglob("*")
        if p.is_file() and not p.relative_to(root).parts[0].startswith(".cache")
    }


def verify(root: Path) -> Frozen:
    """Check every file of the frozen copy at `root` against its manifest:
    each listed file present with its size and SHA-256, and nothing else.
    Raises FrozenError naming the paths that differ (never their content)."""
    manifest_path = root / settings.MANIFEST
    if not manifest_path.is_file():
        raise FrozenError(f"{manifest_path} is missing")
    listed = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    problems: list[str] = []
    for entry in listed:
        path = root / entry["path"]
        if not path.is_file():
            problems.append(f"missing: {entry['path']}")
        elif path.stat().st_size != entry["bytes"]:
            problems.append(f"size differs: {entry['path']}")
        elif sha256_of(path) != entry["sha256"]:
            problems.append(f"SHA-256 differs: {entry['path']}")
    expected = {entry["path"] for entry in listed} | settings.UNLISTED
    problems += [f"not in the manifest: {p}" for p in sorted(_listed_files(root) - expected)]
    if problems:
        raise FrozenError("the frozen inputs are not the pinned ones:\n  " + "\n  ".join(problems))
    return Frozen(root)


def download(dest: Path) -> Frozen:
    """Download the frozen repository at the pinned revision into `dest`
    and check it. The token comes from the environment (`HF_TOKEN`) or
    the local Hugging Face login."""
    from huggingface_hub import snapshot_download

    snapshot_download(
        repo_id=settings.FROZEN_REPO,
        repo_type="dataset",
        revision=settings.FROZEN_REVISION,
        local_dir=dest,
    )
    return verify(dest)


def _link(target: Path, source: Path) -> None:
    """Make `target` a symlink to `source`. An existing `target` is kept
    when it already is that file (a link to it, or the same bytes); any
    other is an error, never overwritten."""
    if target.is_symlink() and target.resolve() == source.resolve():
        return
    if target.exists() or target.is_symlink():
        if target.is_file() and sha256_of(target) == sha256_of(source):
            return
        raise FrozenError(f"{target} exists and is not the frozen {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(source, target)


def install_datasets(frozen: Frozen, results: Path = settings.RESULTS) -> None:
    """Put the frozen sets where bench_full.py and the scorers read them:
    `results/ab1/`, `results/r3/` and `results/ab-loop/piimb/`."""
    for name in settings.AB1_GOLD.values():
        _link(results / "ab1" / name, frozen.dataset("ab1", name))
    for key in (*settings.R3_GATED, *settings.R3_REPORTED):
        name = f"{key.removeprefix(settings.R3_PREFIX)}.jsonl"
        _link(results / "r3" / name, frozen.dataset("r3", name))
    _link(results / "ab-loop" / "piimb" / settings.PIIMB_SENTENCES, frozen.dataset("piimb", settings.PIIMB_SENTENCES))


def install_competitors(frozen: Frozen, checkpoints: Path) -> int:
    """Link every other tool's frozen checkpoints into `checkpoints`, and
    none of nullpii's earlier runs. Returns the number of files linked."""
    linked = 0
    for source_dir in (frozen.ab1_checkpoints, frozen.r3_run / "checkpoints"):
        for source in sorted(source_dir.glob("*.jsonl")):
            if source.name.startswith(settings.NULLPII_PREFIX):
                continue
            _link(checkpoints / source.name, source)
            linked += 1
    return linked
