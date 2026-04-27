# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from nullpii_convert.checksums import sha256_of, verify_sidecar, write_sidecar


def test_sha256_of_matches_hashlib(tmp_path: Path) -> None:
    f = tmp_path / "data.bin"
    payload = b"nullpii-test-payload"
    f.write_bytes(payload)
    assert sha256_of(f) == hashlib.sha256(payload).hexdigest()


def test_sha256_of_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sha256_of(tmp_path / "missing")


def test_write_and_verify_sidecar_roundtrip(tmp_path: Path) -> None:
    f = tmp_path / "model.bin"
    f.write_bytes(b"abcdef")
    sidecar = write_sidecar(f)
    assert sidecar.exists()
    assert verify_sidecar(f) is True


def test_verify_sidecar_detects_corruption(tmp_path: Path) -> None:
    f = tmp_path / "model.bin"
    f.write_bytes(b"abcdef")
    write_sidecar(f)
    f.write_bytes(b"tampered")
    assert verify_sidecar(f) is False


def test_verify_sidecar_missing_returns_false(tmp_path: Path) -> None:
    f = tmp_path / "model.bin"
    f.write_bytes(b"x")
    assert verify_sidecar(f) is False
