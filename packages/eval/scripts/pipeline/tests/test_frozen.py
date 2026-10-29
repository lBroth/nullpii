# SPDX-License-Identifier: Apache-2.0
"""The frozen inputs are used only when every file is the pinned one."""
import hashlib
import json
import re
from pathlib import Path

import pytest

from pipeline import frozen, settings


def _manifest(root: Path) -> None:
    files = [
        {"path": str(p.relative_to(root)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest(), "bytes": p.stat().st_size}
        for p in sorted(root.rglob("*"))
        if p.is_file() and p.name not in settings.UNLISTED
    ]
    (root / settings.MANIFEST).write_text(json.dumps({"format": 1, "files": files}))


def _bundle(root: Path) -> Path:
    for name in settings.AB1_GOLD.values():
        (root / "datasets" / "ab1").mkdir(parents=True, exist_ok=True)
        (root / "datasets" / "ab1" / name).write_text(f'{{"text": "{name}"}}\n')
    (root / "datasets" / "r3").mkdir(parents=True)
    for key in (*settings.R3_GATED, *settings.R3_REPORTED):
        (root / "datasets" / "r3" / f"{key.removeprefix('r3-')}.jsonl").write_text("{}\n")
    (root / "datasets" / "piimb").mkdir(parents=True)
    (root / "datasets" / "piimb" / settings.PIIMB_SENTENCES).write_text("{}\n")
    for group in ("ab1", "r3"):
        (root / "predictions" / group / "checkpoints").mkdir(parents=True)
    (root / "predictions" / "ab1" / "checkpoints" / "presidio-ab1-a.jsonl").write_text("{}\n")
    (root / "predictions" / "ab1" / "checkpoints" / "nullpii-H3b-cuda-agent-ab1-a.jsonl").write_text("{}\n")
    (root / "predictions" / "r3" / "checkpoints" / "rizzo-pii-r3-redact.jsonl").write_text("{}\n")
    (root / "README.md").write_text("private")
    _manifest(root)
    return root


def test_a_copy_that_matches_its_manifest_is_accepted(tmp_path):
    assert frozen.verify(_bundle(tmp_path)).root == tmp_path


def test_the_download_metadata_folder_is_not_a_frozen_file(tmp_path):
    root = _bundle(tmp_path)
    (root / ".cache" / "huggingface").mkdir(parents=True)
    (root / ".cache" / "huggingface" / "x.lock").write_text("")
    frozen.verify(root)


@pytest.mark.parametrize(
    "spoil, said",
    [
        (lambda r: (r / "datasets" / "ab1" / "b2.jsonl").write_text('{"text": "b2.jsonX"}\n'), "SHA-256 differs: datasets/ab1/b2.jsonl"),
        (lambda r: (r / "datasets" / "ab1" / "b1.jsonl").write_text("short"), "size differs: datasets/ab1/b1.jsonl"),
        (lambda r: (r / "datasets" / "piimb" / settings.PIIMB_SENTENCES).unlink(), "missing: datasets/piimb"),
        (lambda r: (r / "datasets" / "extra.jsonl").write_text("{}"), "not in the manifest: datasets/extra.jsonl"),
    ],
)
def test_any_other_copy_is_refused_naming_the_path(tmp_path, spoil, said):
    root = _bundle(tmp_path)
    spoil(root)
    with pytest.raises(frozen.FrozenError, match=re.escape(said)):
        frozen.verify(root)


def test_a_missing_manifest_is_refused(tmp_path):
    with pytest.raises(frozen.FrozenError, match="MANIFEST.json is missing"):
        frozen.verify(tmp_path)


def test_the_sets_go_where_the_scorers_read_them(tmp_path):
    f = frozen.verify(_bundle(tmp_path / "frozen"))
    results = tmp_path / "results"
    frozen.install_datasets(f, results)
    assert (results / "ab1" / "b2.jsonl").resolve() == f.dataset("ab1", "b2.jsonl").resolve()
    assert (results / "r3" / "traces-v3-nodistract.jsonl").is_symlink()
    assert (results / "ab-loop" / "piimb" / settings.PIIMB_SENTENCES).is_file()
    # Twice is fine: the links already point at the frozen files.
    frozen.install_datasets(f, results)


def test_a_file_that_is_already_the_frozen_one_is_kept(tmp_path):
    f = frozen.verify(_bundle(tmp_path / "frozen"))
    results = tmp_path / "results"
    (results / "ab1").mkdir(parents=True)
    (results / "ab1" / "b1.jsonl").write_bytes(f.dataset("ab1", "b1.jsonl").read_bytes())
    frozen.install_datasets(f, results)
    assert not (results / "ab1" / "b1.jsonl").is_symlink()


def test_another_file_in_the_way_is_never_overwritten(tmp_path):
    f = frozen.verify(_bundle(tmp_path / "frozen"))
    results = tmp_path / "results"
    (results / "ab1").mkdir(parents=True)
    (results / "ab1" / "b1.jsonl").write_text("someone else's set")
    with pytest.raises(frozen.FrozenError, match="is not the frozen b1.jsonl"):
        frozen.install_datasets(f, results)
    assert (results / "ab1" / "b1.jsonl").read_text() == "someone else's set"


def test_other_tools_checkpoints_are_linked_and_earlier_nullpii_runs_are_not(tmp_path):
    f = frozen.verify(_bundle(tmp_path / "frozen"))
    checkpoints = tmp_path / "run" / "checkpoints"
    assert frozen.install_competitors(f, checkpoints) == 2
    assert sorted(p.name for p in checkpoints.iterdir()) == ["presidio-ab1-a.jsonl", "rizzo-pii-r3-redact.jsonl"]
