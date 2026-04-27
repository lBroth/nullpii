# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

from nullpii_convert.checksums import sha256_of, write_sidecar
from nullpii_convert.manifest import write_manifest
from nullpii_convert.verify import verify_manifest, verify_signature, write_sidecars


def _seed(root: Path) -> Path:
    f = root / "weights.bin"
    f.write_bytes(b"abc")
    return f


def test_write_sidecars_creates_one_per_file(tmp_path: Path) -> None:
    _seed(tmp_path)
    n = write_sidecars(tmp_path)
    assert n == 1
    assert (tmp_path / "weights.bin.sha256").exists()


def test_verify_manifest_passes_for_intact_files(tmp_path: Path) -> None:
    f = _seed(tmp_path)
    write_sidecar(f)
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, tmp_path)
    assert verify_manifest(tmp_path, manifest) is True


def test_verify_manifest_detects_corruption(tmp_path: Path) -> None:
    f = _seed(tmp_path)
    write_sidecar(f)
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, tmp_path)
    f.write_bytes(b"corrupted")
    assert verify_manifest(tmp_path, manifest) is False


def test_verify_manifest_missing_file_returns_false(tmp_path: Path) -> None:
    f = _seed(tmp_path)
    write_sidecar(f)
    manifest = tmp_path / "manifest.json"
    write_manifest(manifest, tmp_path)
    f.unlink()
    assert verify_manifest(tmp_path, manifest) is False


def test_verify_manifest_missing_manifest_returns_false(tmp_path: Path) -> None:
    assert verify_manifest(tmp_path, tmp_path / "missing.json") is False


def test_verify_signature_skips_when_absent(tmp_path: Path) -> None:
    assert verify_signature(tmp_path) is None


def test_sha256_basic(tmp_path: Path) -> None:
    f = _seed(tmp_path)
    h = sha256_of(f)
    assert len(h) == 64

    payload = json.dumps({"x": h})
    assert h in payload
