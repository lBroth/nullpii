# SPDX-License-Identifier: Apache-2.0
"""SHA256 checksum helpers for model artifact integrity."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .config import CHECKSUM_SUFFIX

_CHUNK_SIZE = 1 << 20  # 1 MiB


def sha256_of(path: Path) -> str:
    """Return hex SHA256 of a file. Raises FileNotFoundError if missing."""
    if not path.is_file():
        raise FileNotFoundError(f"sha256_of: not a file: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(_CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def write_sidecar(path: Path) -> Path:
    """Write `<path>.sha256` containing the hex digest. Returns the sidecar path."""
    digest = sha256_of(path)
    sidecar = path.with_suffix(path.suffix + CHECKSUM_SUFFIX)
    sidecar.write_text(f"{digest}  {path.name}\n", encoding="utf-8")
    return sidecar


def verify_sidecar(path: Path) -> bool:
    """Return True if `<path>.sha256` exists and matches the file."""
    sidecar = path.with_suffix(path.suffix + CHECKSUM_SUFFIX)
    if not sidecar.is_file():
        return False
    expected = sidecar.read_text(encoding="utf-8").split()[0].strip()
    return sha256_of(path) == expected
