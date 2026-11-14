# SPDX-License-Identifier: Apache-2.0
"""The model card, uploaded at release only: MODEL_CARD.md becomes the
README.md of the model repository the library pins.

`check` makes sure the card is the card of the release being tagged:
- the tag is the package's version, a release (not a pre-release), and
  the highest release tagged, so an older release re-run never replaces
  a newer card;
- the card's Files table lists exactly the files and SHA-256 the library
  pins (`DEFAULT_MODEL_SHA256` in src/defaults.ts), and the model
  repository holds those files at the pinned revision;
- published-bench/ holds a run of the pipeline that measured this very
  version with this very model (its OUTPUTS.json), and the card's
  rendered regions say what it holds.
`upload` then puts it on the model repository with a token of its own
(HF_MODEL_CARD_TOKEN, write access to that repository only) and reads it
back at the commit the upload made."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pipeline import build, render, settings, views

CARD = "MODEL_CARD.md"
HF_CARD = "README.md"
DEFAULTS = build.DEFAULTS
PACKAGE_JSON = build.PACKAGE_JSON
TOKEN_ENV = "HF_MODEL_CARD_TOKEN"
MODEL_REPO = "lBroth/nullpii"
FILES_ROW = re.compile(r"^\| `([^`]+)` \| [0-9,]+ bytes \| `([0-9a-f]{64})` \|$", re.MULTILINE)
RELEASE_TAG = re.compile(r"v([0-9]+)\.([0-9]+)\.([0-9]+)")


class CardError(Exception):
    """The card is not the card of this release, or could not be uploaded."""


@dataclass(frozen=True)
class Checked:
    """A card checked against the release it is uploaded with."""

    tag: str
    version: str
    commit: str
    content: bytes
    repo: str
    revision: str


def pinned_model(root: Path) -> tuple[str, str, dict[str, str]]:
    try:
        return build.pinned_model(root)
    except build.BuildError as e:
        raise CardError(str(e)) from e


def card_files(card: str) -> dict[str, str]:
    """The card's Files table: each file and its SHA-256."""
    return {m.group(1): m.group(2) for m in FILES_ROW.finditer(card)}


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], stdout=subprocess.PIPE, check=True, text=True).stdout


def release_of(tag: str) -> tuple[int, int, int] | None:
    m = RELEASE_TAG.fullmatch(tag)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


def newer_releases(tag: str, tags: list[str]) -> list[str]:
    """The release tags above `tag`; a tag that is no release is an error."""
    mine = release_of(tag)
    if mine is None:
        raise CardError(f"{tag} is not a release tag (vX.Y.Z): a pre-release does not replace the card")
    return sorted(t for t in tags if (v := release_of(t)) is not None and v > mine)


def _card_regions_render(root: Path) -> list[str]:
    diffs = render.check(settings.PUBLISHED, settings.PUBLISHED, root)
    return [str(d) for d in diffs if str(d).startswith(CARD)]


def published_measurement(published: Path) -> tuple[str, dict]:
    """In whose row names published-bench is, and what it measured."""
    names = views.layout_names(published)
    return names, views.measured(published, names)


def _remote_hashes(repo: str, revision: str, names: list[str]) -> dict[str, str]:
    """The SHA-256 of each file of the model repository at `revision`."""
    from huggingface_hub import HfApi, hf_hub_download

    out = {}
    for info in HfApi().get_paths_info(repo, names, revision=revision, repo_type="model"):
        if getattr(info, "lfs", None) is not None:
            out[info.path] = info.lfs.sha256
        else:
            local = Path(hf_hub_download(repo, info.path, revision=revision, repo_type="model"))
            out[info.path] = hashlib.sha256(local.read_bytes()).hexdigest()
    return out


def _check_measurement(version: str, repo: str, revision: str) -> None:
    names, measured = published_measurement(settings.PUBLISHED)
    if names != views.RUN_NAMES:
        raise CardError("published-bench holds the published 0.5 run, not a run of the pipeline of this release:"
                        " merge a numbers PR of bench.yml for it before tagging")
    want = {"nullpii": version, "model": f"{repo}@{revision}"}
    got = {k: measured.get(k) for k in want}
    if got != want:
        raise CardError(f"published-bench measured nullpii {got['nullpii']} with {got['model']}; the release is"
                        f" nullpii {version} with {want['model']}: re-measure (bench.yml) and merge its numbers PR first")


def check(root: Path, tag: str) -> Checked:
    """Raise CardError naming the first way the card is not this release's."""
    version = json.loads((root / PACKAGE_JSON).read_text(encoding="utf-8"))["version"]
    if tag != f"v{version}":
        raise CardError(f"the tag is {tag}, the package's version is {version}")
    newer = newer_releases(tag, _git(root, "tag", "--list", "v*").split())
    if newer:
        raise CardError(f"{', '.join(newer)} {'is' if len(newer) == 1 else 'are'} released after {tag}: its card stays")
    repo, revision, pinned = pinned_model(root)
    if repo != MODEL_REPO:
        raise CardError(f"the library pins {repo}; the card goes to {MODEL_REPO}")
    content = (root / CARD).read_bytes()
    listed = card_files(content.decode("utf-8"))
    if listed != pinned:
        differ = sorted({name for name in set(listed) | set(pinned) if listed.get(name) != pinned.get(name)})
        raise CardError(f"{CARD}'s Files table is not the files and SHA-256 {DEFAULTS} pins (differ: {', '.join(differ)})")
    _check_measurement(version, repo, revision)
    stale = _card_regions_render(root)
    if stale:
        raise CardError(f"{CARD} does not say what published-bench holds: {'; '.join(stale)}")
    remote = _remote_hashes(repo, revision, sorted(pinned))
    if remote != pinned:
        raise CardError(f"{repo}@{revision[:12]} does not hold the files {DEFAULTS} pins")
    return Checked(tag, version, _git(root, "rev-parse", "HEAD").strip(), content, repo, revision)


def upload(root: Path, checked: Checked) -> str:
    """Upload the checked card as the model repository's README.md, read
    it back at the commit the upload made, and say where it is."""
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        raise CardError(f"{TOKEN_ENV} is not set: the owner creates a fine-grained Hugging Face token with write"
                        f" access to {MODEL_REPO} only, and adds it as the secret {TOKEN_ENV} of the release"
                        " environment")
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=token)
    info = api.upload_file(
        path_or_fileobj=checked.content, path_in_repo=HF_CARD, repo_id=checked.repo, repo_type="model",
        commit_message=f"Model card of nullpii {checked.version} ({checked.tag})",
        commit_description=(f"{CARD} of lBroth/nullpii at {checked.commit}, the release {checked.tag}. It describes"
                            f" the files at revision {checked.revision}, which the release pins."),
    )
    back = Path(hf_hub_download(checked.repo, HF_CARD, repo_type="model", revision=info.oid, token=token,
                                force_download=True))
    if back.read_bytes() != checked.content:
        raise CardError(f"{checked.repo}'s {HF_CARD} at {info.oid[:12]} is not {CARD} after the upload")
    return f"model-card: {CARD} of {checked.tag} is {checked.repo}'s {HF_CARD} ({info.commit_url})"
