# SPDX-License-Identifier: Apache-2.0
"""The frozen inputs: download them at the pinned revision, check every
file against the manifest, and put the sets where bench_full.py's loaders
read them.

Nothing here prints a row: the frozen repository holds real secrets."""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from pipeline import settings

HASH_CHUNK = 1 << 20
# The frozen sets alone: what a capture reads (the texts), a small part of
# the copy. A CI capture job downloads only these.
SETS = ("datasets/",)


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
    def piimb_sentences(self) -> Path:
        return self.dataset("piimb", settings.PIIMB_SENTENCES)

    @property
    def published_outputs(self) -> Path:
        """The published 0.5 run's AB-1 and PIIMB outputs (`ab1/`, `piimb/`)."""
        return self.root / settings.PUBLISHED_RUN_OUTPUTS

    @property
    def piimb_published_spans(self) -> Path:
        return self.predictions("piimb", "nullpii-spans-v2.jsonl")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _walk(root: Path) -> tuple[set[str], list[str]]:
    """The relative path of every file of the copy, outside huggingface_hub's
    download metadata, and every entry that is not a regular file or a
    folder (a symlink, say): a copy is regular files only, so a link, which
    could bring in files the manifest never saw, is refused."""
    files: set[str] = set()
    odd: list[str] = []
    for top, dirs, names in os.walk(root, followlinks=False):
        here = Path(top)
        if here.relative_to(root).parts == settings.DOWNLOAD_METADATA:
            dirs.clear()
            continue
        for name in sorted(dirs + names):
            path = here / name
            rel = str(path.relative_to(root))
            if path.is_symlink() or not (path.is_dir() or path.is_file()):
                odd.append(rel)
            elif path.is_file():
                files.add(rel)
        dirs[:] = [d for d in dirs if not (here / d).is_symlink()]
    return files, odd


def _under(path: str, only: tuple[str, ...] | None) -> bool:
    return only is None or path.startswith(only)


def verify(root: Path, manifest_sha256: str = settings.FROZEN_MANIFEST_SHA256,
           only: tuple[str, ...] | None = None) -> Frozen:
    """Check the frozen copy at `root`: its manifest is the pinned one (by
    SHA-256), and every file is listed in it with its size and SHA-256,
    and nothing else is there. With `only` (path prefixes, e.g. SETS), the
    copy may be that part alone: the listed files under them are checked,
    the others may be missing, and nothing unlisted may be there. Raises
    FrozenError naming the paths that differ (never their content). The
    Frozen it returns has an absolute root, so links to its files hold
    from any directory."""
    root = root.resolve()
    manifest_path = root / settings.MANIFEST
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise FrozenError(f"{manifest_path} is missing")
    if sha256_of(manifest_path) != manifest_sha256:
        raise FrozenError(
            f"{manifest_path} is not the manifest of {settings.FROZEN_REPO}@{settings.FROZEN_REVISION[:12]}"
            " (its SHA-256 is not the one pinned in settings.py): this is an unpinned copy, whatever its"
            " files agree with; download the pinned revision with `fetch --download`")
    listed = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    present, odd = _walk(root)
    problems = [f"not a regular file: {p}" for p in odd]
    for entry in listed:
        path = root / entry["path"]
        if not _under(entry["path"], only) and entry["path"] not in present:
            continue
        if entry["path"] not in present:
            problems.append(f"missing: {entry['path']}")
        elif path.stat().st_size != entry["bytes"]:
            problems.append(f"size differs: {entry['path']}")
        elif sha256_of(path) != entry["sha256"]:
            problems.append(f"SHA-256 differs: {entry['path']}")
    expected = {entry["path"] for entry in listed} | settings.UNLISTED
    problems += [f"not in the manifest: {p}" for p in sorted(present - expected)]
    if problems:
        raise FrozenError("the frozen inputs are not the pinned ones:\n  " + "\n  ".join(problems))
    return Frozen(root)


def download(dest: Path, only: tuple[str, ...] | None = None) -> Frozen:
    """Download the frozen repository at the pinned revision into `dest`
    and check it; with `only`, the files under those prefixes and the
    manifest alone. The token comes from the environment (`HF_TOKEN`) or
    the local Hugging Face login.

    The revision is asked for first: snapshot_download, when it cannot
    reach the repository (offline, no or a wrong token, a server error),
    returns whatever `dest` already holds with only a logged warning."""
    from huggingface_hub import HfApi, snapshot_download

    info = HfApi().dataset_info(settings.FROZEN_REPO, revision=settings.FROZEN_REVISION)
    if info.sha != settings.FROZEN_REVISION:
        raise FrozenError(f"{settings.FROZEN_REPO} answered revision {info.sha}, not {settings.FROZEN_REVISION}")
    snapshot_download(
        repo_id=settings.FROZEN_REPO,
        repo_type="dataset",
        revision=settings.FROZEN_REVISION,
        local_dir=dest,
        allow_patterns=None if only is None else [settings.MANIFEST, *(f"{p}*" for p in only)],
    )
    return verify(dest, only=only)


def link(target: Path, source: Path) -> None:
    """Make `target` a symlink to `source` (by its absolute path, so the
    link holds whatever directory it was made from). An existing `target`
    is kept when it already is that file (a link to it, or the same
    bytes); any other is an error, never overwritten."""
    source = source.resolve()
    if target.is_symlink() and target.resolve() == source:
        return
    if target.exists() or target.is_symlink():
        if target.is_file() and sha256_of(target) == sha256_of(source):
            return
        raise FrozenError(f"{target} exists and is not {source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(source, target)


def install_datasets(frozen: Frozen, results: Path = settings.RESULTS) -> None:
    """Put the frozen sets where bench_full.py's loaders read them (they
    check each set's SHA-256): `results/ab1/`, `results/r3/` and
    `results/ab-loop/piimb/`. The pipeline's own scorers are handed the
    checked copy's files instead, never what `results/` holds."""
    for name in settings.AB1_GOLD.values():
        link(results / "ab1" / name, frozen.dataset("ab1", name))
    for key in (*settings.R3_GATED, *settings.R3_REPORTED):
        name = f"{key.removeprefix(settings.R3_PREFIX)}.jsonl"
        link(results / "r3" / name, frozen.dataset("r3", name))
    link(results / "ab-loop" / "piimb" / settings.PIIMB_SENTENCES, frozen.piimb_sentences)


def install_competitors(frozen: Frozen, checkpoints: Path) -> int:
    """Link every other tool's frozen checkpoints into `checkpoints`, and
    none of nullpii's earlier runs. Returns the number of files linked."""
    linked = 0
    for source_dir in (frozen.ab1_checkpoints, frozen.r3_run / "checkpoints"):
        for source in sorted(source_dir.glob("*.jsonl")):
            if source.name.startswith(settings.NULLPII_PREFIX):
                continue
            link(checkpoints / source.name, source)
            linked += 1
    return linked
