# SPDX-License-Identifier: Apache-2.0
"""Build manifest for fetched model artifacts.

Produces `manifest.json` with the upstream revision, the SHA256 of every file,
and its size in bytes. The manifest is the deterministic build output of record.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .checksums import sha256_of
from .config import CHECKSUM_SUFFIX, MANIFEST_PATH, MODEL_DIR, MODEL_ID, UPSTREAM_REVISION

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class FileEntry:
    path: str
    sha256: str
    bytes: int


@dataclass(frozen=True, slots=True)
class Manifest:
    model_id: str
    revision: str
    files: list[FileEntry]


def build_manifest(model_dir: Path = MODEL_DIR) -> Manifest:
    """Walk `model_dir`, hash every file (skipping sidecars), return manifest."""
    if not model_dir.is_dir():
        raise FileNotFoundError(f"build_manifest: {model_dir} not found")

    entries: list[FileEntry] = []
    for f in sorted(model_dir.rglob("*")):
        if not f.is_file():
            continue
        if f.name.endswith(CHECKSUM_SUFFIX):
            continue
        rel = f.relative_to(model_dir).as_posix()
        entries.append(FileEntry(path=rel, sha256=sha256_of(f), bytes=f.stat().st_size))

    return Manifest(model_id=MODEL_ID, revision=UPSTREAM_REVISION, files=entries)


def write_manifest(out: Path = MANIFEST_PATH, model_dir: Path = MODEL_DIR) -> Path:
    """Compute and write `manifest.json`. Returns the output path."""
    manifest = build_manifest(model_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "model_id": manifest.model_id,
        "revision": manifest.revision,
        "files": [asdict(e) for e in manifest.files],
    }
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    log.info("manifest written: %s (%d files)", out, len(manifest.files))
    return out


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    write_manifest()
