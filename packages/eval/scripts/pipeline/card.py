# SPDX-License-Identifier: Apache-2.0
"""The model card, uploaded at release only: MODEL_CARD.md becomes the
README.md of the model repository the library pins.

`check` makes sure the card is the card of the release being tagged:
the tag is the package's version; the card's Files table lists exactly
the files and SHA-256 the library pins (`DEFAULT_MODEL_SHA256` in
src/defaults.ts), and the model repository holds those files at the
pinned revision; and its rendered regions say what published-bench/
holds. `upload` then puts it on the model repository with a token of its
own (HF_MODEL_CARD_TOKEN, write access to that repository only) and reads
it back."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from pipeline import render, settings

CARD = "MODEL_CARD.md"
HF_CARD = "README.md"
DEFAULTS = "src/defaults.ts"
PACKAGE_JSON = "package.json"
TOKEN_ENV = "HF_MODEL_CARD_TOKEN"
MODEL_REPO = "lBroth/nullpii"
REVISION = re.compile(r"^export const DEFAULT_MODEL_REVISION = '([0-9a-f]{40})';$", re.M)
REPO = re.compile(r"^export const DEFAULT_MODEL_REPO = '([^']+)';$", re.M)
HASHES = re.compile(r"^export const DEFAULT_MODEL_SHA256[^=]*= \{\n(.*?)\n\};$", re.M | re.S)
HASH_ENTRY = re.compile(r"^\s*'([^']+)': '([0-9a-f]{64})',$")
FILES_ROW = re.compile(r"^\| `([^`]+)` \| [0-9,]+ bytes \| `([0-9a-f]{64})` \|$", re.M)


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
    """The repository, revision and per-file SHA-256 the library pins."""
    text = (root / DEFAULTS).read_text(encoding="utf-8")
    repo, revision, hashes = REPO.search(text), REVISION.search(text), HASHES.search(text)
    if repo is None or revision is None or hashes is None:
        raise CardError(f"{DEFAULTS}: no DEFAULT_MODEL_REPO, 40-hex DEFAULT_MODEL_REVISION or DEFAULT_MODEL_SHA256")
    entries = {}
    for line in hashes.group(1).splitlines():
        m = HASH_ENTRY.match(line)
        if m is None:
            raise CardError(f"{DEFAULTS}: a DEFAULT_MODEL_SHA256 line that is not 'file': 'sha256',")
        entries[m.group(1)] = m.group(2)
    return repo.group(1), revision.group(1), entries


def card_files(card: str) -> dict[str, str]:
    """The card's Files table: each file and its SHA-256."""
    return {m.group(1): m.group(2) for m in FILES_ROW.finditer(card)}


def _card_regions_render(root: Path) -> list[str]:
    diffs = render.check(settings.PUBLISHED, settings.PUBLISHED, root)
    return [str(d) for d in diffs if str(d).startswith(CARD)]


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


def check(root: Path, tag: str) -> Checked:
    """Raise CardError naming each way the card is not this release's."""
    version = json.loads((root / PACKAGE_JSON).read_text(encoding="utf-8"))["version"]
    if tag != f"v{version}":
        raise CardError(f"the tag is {tag}, the package's version is {version}")
    repo, revision, pinned = pinned_model(root)
    if repo != MODEL_REPO:
        raise CardError(f"the library pins {repo}; the card goes to {MODEL_REPO}")
    content = (root / CARD).read_bytes()
    listed = card_files(content.decode("utf-8"))
    if listed != pinned:
        differ = sorted({name for name in set(listed) | set(pinned) if listed.get(name) != pinned.get(name)})
        raise CardError(f"{CARD}'s Files table is not the files and SHA-256 {DEFAULTS} pins (differ: {', '.join(differ)})")
    stale = _card_regions_render(root)
    if stale:
        raise CardError(f"{CARD} does not say what published-bench holds: {'; '.join(stale)}")
    remote = _remote_hashes(repo, revision, sorted(pinned))
    if remote != pinned:
        raise CardError(f"{repo}@{revision[:12]} does not hold the files {DEFAULTS} pins")
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], stdout=subprocess.PIPE,
                            check=True, text=True).stdout.strip()
    return Checked(tag, version, commit, content, repo, revision)


def upload(root: Path, checked: Checked) -> str:
    """Upload the checked card as the model repository's README.md, read
    it back, and say where it is."""
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        raise CardError(f"{TOKEN_ENV} is not set: the owner creates a fine-grained Hugging Face token with write"
                        f" access to {MODEL_REPO} only, and adds it as the repository secret {TOKEN_ENV}")
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi(token=token)
    info = api.upload_file(
        path_or_fileobj=checked.content, path_in_repo=HF_CARD, repo_id=checked.repo, repo_type="model",
        commit_message=f"Model card of nullpii {checked.version} ({checked.tag})",
        commit_description=(f"{CARD} of lBroth/nullpii at {checked.commit}, the release {checked.tag}. It describes"
                            f" the files at revision {checked.revision}, which the release pins."),
    )
    back = Path(hf_hub_download(checked.repo, HF_CARD, repo_type="model", token=token, force_download=True))
    if back.read_bytes() != checked.content:
        raise CardError(f"{checked.repo}'s {HF_CARD} is not {CARD} after the upload")
    return f"model-card: {CARD} of {checked.tag} is {checked.repo}'s {HF_CARD} ({info.commit_url})"
