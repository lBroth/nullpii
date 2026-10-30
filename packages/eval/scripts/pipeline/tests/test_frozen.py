# SPDX-License-Identifier: Apache-2.0
"""The frozen inputs are used only when every file is the pinned one."""
import hashlib
import json
import os
import re
import sys
import types
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


def _pin(root: Path) -> str:
    """The SHA-256 of the made-up bundle's manifest, pinned in its place."""
    return hashlib.sha256((root / settings.MANIFEST).read_bytes()).hexdigest()


def _verify(root: Path) -> frozen.Frozen:
    return frozen.verify(root, _pin(root))


def test_a_copy_that_matches_its_manifest_is_accepted(tmp_path):
    assert _verify(_bundle(tmp_path)).root == tmp_path.resolve()


def test_a_copy_that_only_agrees_with_itself_is_refused(tmp_path):
    # Every file matches its manifest, but the manifest is not the pinned
    # revision's: an older copy, or a file changed with its entry.
    with pytest.raises(frozen.FrozenError, match="is not the manifest of"):
        frozen.verify(_bundle(tmp_path))


def test_the_download_metadata_folder_is_not_a_frozen_file(tmp_path):
    root = _bundle(tmp_path)
    (root / ".cache" / "huggingface").mkdir(parents=True)
    (root / ".cache" / "huggingface" / "x.lock").write_text("")
    _verify(root)


@pytest.mark.parametrize("extra", [".cache-old/x.jsonl", ".cachex.jsonl", ".cache/other/x.jsonl"])
def test_only_the_download_metadata_folder_is_left_out(tmp_path, extra):
    root = _bundle(tmp_path / "frozen")
    (root / extra).parent.mkdir(parents=True, exist_ok=True)
    (root / extra).write_text("{}")
    with pytest.raises(frozen.FrozenError, match=re.escape(f"not in the manifest: {extra}")):
        _verify(root)


def test_a_linked_folder_inside_the_copy_is_refused(tmp_path):
    # Behind the link are a listed checkpoint and one the manifest never saw.
    root = _bundle(tmp_path / "frozen")
    outside = tmp_path / "elsewhere"
    (root / "predictions" / "ab1" / "checkpoints").rename(outside)
    (outside / "extra-tool-ab1-a.jsonl").write_text("{}\n")
    (root / "predictions" / "ab1" / "checkpoints").symlink_to(outside)
    with pytest.raises(frozen.FrozenError, match="not a regular file: predictions/ab1/checkpoints"):
        _verify(root)


def test_a_linked_file_inside_the_copy_is_refused(tmp_path):
    root = _bundle(tmp_path / "frozen")
    b1 = root / "datasets" / "ab1" / "b1.jsonl"
    (tmp_path / "b1.jsonl").write_bytes(b1.read_bytes())
    b1.unlink()
    b1.symlink_to(tmp_path / "b1.jsonl")
    with pytest.raises(frozen.FrozenError, match="not a regular file: datasets/ab1/b1.jsonl"):
        _verify(root)


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
    pin = _pin(root)
    spoil(root)
    with pytest.raises(frozen.FrozenError, match=re.escape(said)):
        frozen.verify(root, pin)


def test_a_missing_manifest_is_refused(tmp_path):
    with pytest.raises(frozen.FrozenError, match="MANIFEST.json is missing"):
        frozen.verify(tmp_path)


def test_the_sets_go_where_the_scorers_read_them(tmp_path):
    f = _verify(_bundle(tmp_path / "frozen"))
    results = tmp_path / "results"
    frozen.install_datasets(f, results)
    assert (results / "ab1" / "b2.jsonl").resolve() == f.dataset("ab1", "b2.jsonl").resolve()
    assert (results / "r3" / "traces-v3-nodistract.jsonl").is_symlink()
    assert (results / "ab-loop" / "piimb" / settings.PIIMB_SENTENCES).is_file()
    # Twice is fine: the links already point at the frozen files.
    frozen.install_datasets(f, results)


def test_a_file_that_is_already_the_frozen_one_is_kept(tmp_path):
    f = _verify(_bundle(tmp_path / "frozen"))
    results = tmp_path / "results"
    (results / "ab1").mkdir(parents=True)
    (results / "ab1" / "b1.jsonl").write_bytes(f.dataset("ab1", "b1.jsonl").read_bytes())
    frozen.install_datasets(f, results)
    assert not (results / "ab1" / "b1.jsonl").is_symlink()


def test_another_file_in_the_way_is_never_overwritten(tmp_path):
    f = _verify(_bundle(tmp_path / "frozen"))
    results = tmp_path / "results"
    (results / "ab1").mkdir(parents=True)
    (results / "ab1" / "b1.jsonl").write_text("someone else's set")
    with pytest.raises(frozen.FrozenError, match=r"b1.jsonl exists and is not .*datasets/ab1/b1.jsonl"):
        frozen.install_datasets(f, results)
    assert (results / "ab1" / "b1.jsonl").read_text() == "someone else's set"


def test_other_tools_checkpoints_are_linked_and_earlier_nullpii_runs_are_not(tmp_path):
    f = _verify(_bundle(tmp_path / "frozen"))
    checkpoints = tmp_path / "run" / "checkpoints"
    assert frozen.install_competitors(f, checkpoints) == 2
    assert sorted(p.name for p in checkpoints.iterdir()) == ["presidio-ab1-a.jsonl", "rizzo-pii-r3-redact.jsonl"]


def test_links_made_from_a_relative_root_hold_from_any_directory(tmp_path, monkeypatch):
    _bundle(tmp_path / "frozen")
    monkeypatch.chdir(tmp_path)
    f = frozen.verify(Path("frozen"), _pin(tmp_path / "frozen"))
    results, checkpoints = tmp_path / "results", tmp_path / "run" / "checkpoints"
    frozen.install_datasets(f, results)
    frozen.install_competitors(f, checkpoints)
    monkeypatch.chdir(tmp_path / "results")
    links = [p for p in (*results.rglob("*.jsonl"), *checkpoints.iterdir())]
    assert links and all(p.is_symlink() and os.path.isabs(os.readlink(p)) and p.is_file() for p in links)
    assert (results / "ab1" / "b2.jsonl").read_text() == '{"text": "b2.jsonl"}\n'
    # Twice is fine: the links already are the frozen files.
    frozen.install_datasets(f, results)


class _Unreachable(Exception):
    pass


def _fake_hub(monkeypatch, info):
    """A huggingface_hub whose dataset_info calls `info`, recording every
    snapshot_download."""
    downloads = []
    hub = types.ModuleType("huggingface_hub")
    hub.HfApi = lambda: types.SimpleNamespace(dataset_info=info)
    hub.snapshot_download = lambda **kwargs: downloads.append(kwargs)
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    return downloads


def test_a_download_that_cannot_reach_the_pinned_revision_raises(tmp_path, monkeypatch):
    # snapshot_download alone would hand back what the folder holds.
    def unreachable(repo, revision):
        raise _Unreachable(f"{repo}@{revision}")
    downloads = _fake_hub(monkeypatch, unreachable)
    _bundle(tmp_path)
    with pytest.raises(_Unreachable):
        frozen.download(tmp_path)
    assert downloads == []


def test_a_download_answered_with_another_revision_raises(tmp_path, monkeypatch):
    downloads = _fake_hub(monkeypatch, lambda repo, revision: types.SimpleNamespace(sha="0" * 40))
    with pytest.raises(frozen.FrozenError, match="answered revision"):
        frozen.download(tmp_path)
    assert downloads == []


def test_a_download_is_checked_against_the_pinned_manifest(tmp_path, monkeypatch):
    downloads = _fake_hub(monkeypatch, lambda repo, revision: types.SimpleNamespace(sha=settings.FROZEN_REVISION))
    _bundle(tmp_path)
    with pytest.raises(frozen.FrozenError, match="is not the manifest of"):
        frozen.download(tmp_path)
    assert downloads == [{"repo_id": settings.FROZEN_REPO, "repo_type": "dataset",
                          "revision": settings.FROZEN_REVISION, "local_dir": tmp_path, "allow_patterns": None}]


def test_a_download_of_the_sets_alone_asks_for_them_and_the_manifest(tmp_path, monkeypatch):
    downloads = _fake_hub(monkeypatch, lambda repo, revision: types.SimpleNamespace(sha=settings.FROZEN_REVISION))
    _bundle(tmp_path)
    with pytest.raises(frozen.FrozenError, match="is not the manifest of"):
        frozen.download(tmp_path, frozen.SETS)
    assert downloads[0]["allow_patterns"] == [settings.MANIFEST, "datasets/*"]


def _sets_only(root: Path) -> Path:
    import shutil
    _bundle(root)
    shutil.rmtree(root / "predictions")
    return root


def test_a_copy_of_the_sets_alone_is_accepted_for_the_sets_only(tmp_path):
    root = _sets_only(tmp_path)
    assert frozen.verify(root, _pin(root), only=frozen.SETS).root == root.resolve()
    with pytest.raises(frozen.FrozenError, match="missing: predictions/"):
        frozen.verify(root, _pin(root))


def test_a_copy_of_the_sets_alone_still_checks_every_set_and_everything_present(tmp_path):
    root = _sets_only(tmp_path)
    (root / "datasets" / "ab1" / "b2.jsonl").write_text('{"text": "changed"}\n')
    with pytest.raises(frozen.FrozenError, match="datasets/ab1/b2.jsonl"):
        frozen.verify(root, _pin(root), only=frozen.SETS)
    root = _sets_only(tmp_path / "again")
    (root / "datasets" / "r3" / "redact.jsonl").unlink()
    with pytest.raises(frozen.FrozenError, match="missing: datasets/r3/redact.jsonl"):
        frozen.verify(root, _pin(root), only=frozen.SETS)
    root = _sets_only(tmp_path / "extra")
    (root / "predictions").mkdir()
    (root / "predictions" / "planted.jsonl").write_text("{}\n")
    with pytest.raises(frozen.FrozenError, match="not in the manifest: predictions/planted.jsonl"):
        frozen.verify(root, _pin(root), only=frozen.SETS)


def test_a_link_to_a_relative_source_is_made_absolute(tmp_path, monkeypatch):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.jsonl").write_text("{}\n")
    monkeypatch.chdir(tmp_path)
    frozen.link(tmp_path / "out" / "a.jsonl", Path("src") / "a.jsonl")
    assert os.readlink(tmp_path / "out" / "a.jsonl") == str((tmp_path / "src" / "a.jsonl").resolve())
