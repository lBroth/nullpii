# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

import pytest

from nullpii_convert.manifest import build_manifest, write_manifest


def _seed_dir(root: Path) -> None:
    (root / "config.json").write_text("{}\n", encoding="utf-8")
    (root / "onnx").mkdir()
    (root / "onnx" / "model.onnx").write_bytes(b"\x00onnx\x00")
    (root / "onnx" / "model.onnx.sha256").write_text("dead  model.onnx\n", encoding="utf-8")


def test_build_manifest_skips_sidecars(tmp_path: Path) -> None:
    _seed_dir(tmp_path)
    m = build_manifest(tmp_path)
    paths = [e.path for e in m.files]
    assert "config.json" in paths
    assert "onnx/model.onnx" in paths
    assert "onnx/model.onnx.sha256" not in paths


def test_build_manifest_missing_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_manifest(tmp_path / "nope")


def test_write_manifest_round_trip(tmp_path: Path) -> None:
    _seed_dir(tmp_path)
    out = tmp_path / "manifest.json"
    write_manifest(out, tmp_path)
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["model_id"]
    assert payload["revision"]
    assert any(f["path"] == "config.json" for f in payload["files"])
    assert all("sha256" in f and "bytes" in f for f in payload["files"])


def test_write_manifest_is_deterministic(tmp_path: Path) -> None:
    src = tmp_path / "model"
    src.mkdir()
    _seed_dir(src)
    out_a = tmp_path / "a.json"
    out_b = tmp_path / "b.json"
    write_manifest(out_a, src)
    write_manifest(out_b, src)
    assert out_a.read_text(encoding="utf-8") == out_b.read_text(encoding="utf-8")
