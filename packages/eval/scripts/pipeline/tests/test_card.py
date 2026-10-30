# SPDX-License-Identifier: Apache-2.0
"""The model card goes up at release only as the card of that release:
the tag's version, the files and hashes the library pins, the numbers
published-bench holds; and never without its own token."""
import json
import shutil
import sys
import types
from pathlib import Path

import pytest

from pipeline import card, views


def test_the_card_lists_the_files_the_library_pins():
    repo, revision, pinned = card.pinned_model(views.ROOT)
    assert repo == card.MODEL_REPO and len(revision) == 40
    assert card.card_files((views.ROOT / card.CARD).read_text(encoding="utf-8")) == pinned
    assert len(pinned) == 5


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A copy of what `check` reads, the model repository answering with
    the pinned hashes, and the card's regions saying what published-bench
    holds."""
    for rel in (card.CARD, card.DEFAULTS, card.PACKAGE_JSON):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(views.ROOT / rel, tmp_path / rel)
    repo, revision, pinned = card.pinned_model(views.ROOT)
    version = json.loads((tmp_path / card.PACKAGE_JSON).read_text())["version"]
    monkeypatch.setattr(card, "_remote_hashes", lambda repo, revision, names: dict(pinned))
    monkeypatch.setattr(card, "_card_regions_render", lambda r: [])
    monkeypatch.setattr(card, "published_measurement", lambda p: (views.RUN_NAMES, {
        "nullpii": version, "model": f"{repo}@{revision}", "backend": "cpu"}))
    tags = ["v0.4.0", "v0.5.0", f"v{version}", "v99.0.0-rc.1"]

    def git(root, *args):
        return "\n".join(tags) + "\n" if args[0] == "tag" else "f" * 40 + "\n"
    monkeypatch.setattr(card, "_git", git)
    tmp_path.joinpath(".tags").write_text(json.dumps(tags))
    return tmp_path


def _tag(root: Path) -> str:
    return "v" + json.loads((root / card.PACKAGE_JSON).read_text())["version"]


def test_the_card_of_this_release_passes(root):
    checked = card.check(root, _tag(root))
    assert checked.content == (root / card.CARD).read_bytes()
    assert checked.commit == "f" * 40 and checked.repo == card.MODEL_REPO


def test_another_versions_tag_is_refused(root):
    with pytest.raises(card.CardError, match="the package's version is"):
        card.check(root, "v0.0.1")


def test_a_release_older_than_one_already_tagged_keeps_the_newer_card(root, monkeypatch):
    tag = _tag(root)
    monkeypatch.setattr(card, "_git", lambda r, *a: f"{tag}\nv99.1.0\nv99.0.0\n" if a[0] == "tag" else "f" * 40)
    with pytest.raises(card.CardError, match="v99.0.0, v99.1.0 are released after"):
        card.check(root, tag)


@pytest.mark.parametrize("tag, tags, newer", [
    ("v0.5.4", ["v0.5.4", "v0.5.10"], ["v0.5.10"]),
    ("v0.5.10", ["v0.5.4", "v0.5.10", "v0.6.0-rc.1"], []),
    ("v1.0.0", ["v0.99.99"], []),
])
def test_releases_are_ordered_as_versions_not_text(tag, tags, newer):
    assert card.newer_releases(tag, tags) == newer


def test_a_pre_release_never_uploads_a_card():
    with pytest.raises(card.CardError, match="not a release tag"):
        card.newer_releases("v0.6.0-rc.1", [])


def test_a_card_published_bench_did_not_measure_for_this_release_is_refused(root, monkeypatch):
    repo, revision, _ = card.pinned_model(views.ROOT)
    version = json.loads((root / card.PACKAGE_JSON).read_text())["version"]
    for names, measured, said in (
        (views.PUBLISHED_NAMES, {"nullpii": "0.5", "model": f"{repo}@{revision}", "backend": "cuda"}, "published 0.5 run"),
        (views.RUN_NAMES, {"nullpii": "0.0.1", "model": f"{repo}@{revision}", "backend": "cpu"}, "measured nullpii 0.0.1"),
        (views.RUN_NAMES, {"nullpii": version, "model": f"{repo}@{'0' * 40}", "backend": "cpu"}, "re-measure"),
    ):
        monkeypatch.setattr(card, "published_measurement", lambda p, n=names, m=measured: (n, m))
        with pytest.raises(card.CardError, match=said):
            card.check(root, _tag(root))


def test_a_card_whose_files_are_not_the_pinned_ones_is_refused(root):
    text = (root / card.CARD).read_text()
    (root / card.CARD).write_text(text.replace("58b6d795693fc3e79f465134a8e5acd4", "0" * 32))
    with pytest.raises(card.CardError, match="Files table is not the files and SHA-256"):
        card.check(root, _tag(root))


def test_a_card_that_lost_a_file_is_refused(root):
    lines = [line for line in (root / card.CARD).read_text().splitlines(keepends=True) if "`tokenizer.json`" not in line]
    (root / card.CARD).write_text("".join(lines))
    with pytest.raises(card.CardError, match="Files table"):
        card.check(root, _tag(root))


def test_a_card_that_does_not_say_what_published_bench_holds_is_refused(root, monkeypatch):
    monkeypatch.setattr(card, "_card_regions_render", lambda r: ["MODEL_CARD.md <!-- card-r3 -->: differs"])
    with pytest.raises(card.CardError, match="card-r3"):
        card.check(root, _tag(root))


def test_a_model_repository_without_the_pinned_files_is_refused(root, monkeypatch):
    monkeypatch.setattr(card, "_remote_hashes", lambda repo, revision, names: {n: "0" * 64 for n in names})
    with pytest.raises(card.CardError, match="does not hold the files"):
        card.check(root, _tag(root))


def test_the_card_regions_are_checked_against_published_bench():
    assert card._card_regions_render(views.ROOT) == []


def test_published_bench_holding_the_published_run_reads_as_that_run():
    names, measured = card.published_measurement(views.ROOT / "packages" / "eval" / "published-bench")
    assert names == views.PUBLISHED_NAMES and measured["backend"] == "cuda"


def _checked(root):
    return card.check(root, _tag(root))


def test_no_upload_without_the_cards_own_token(root, monkeypatch):
    monkeypatch.delenv(card.TOKEN_ENV, raising=False)
    monkeypatch.setenv("HF_TOKEN", "the frozen inputs' token")
    with pytest.raises(card.CardError, match="HF_MODEL_CARD_TOKEN is not set: the owner creates a fine-grained"):
        card.upload(root, _checked(root))


def _fake_hub(monkeypatch, back: bytes):
    calls = {}
    hub = types.ModuleType("huggingface_hub")

    class Api:
        def __init__(self, token=None):
            calls["token"] = token

        def upload_file(self, **kwargs):
            calls["upload"] = kwargs
            return types.SimpleNamespace(oid="c" * 40, commit_url="https://huggingface.co/lBroth/nullpii/commit/abc")

    def download(repo, name, **kwargs):
        path = Path(calls["dir"]) / name
        path.write_bytes(back)
        calls["download"] = (repo, name, kwargs)
        return str(path)
    hub.HfApi, hub.hf_hub_download = Api, download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)
    return calls


def test_the_upload_is_the_card_as_readme_read_back(root, monkeypatch, tmp_path):
    checked = _checked(root)
    calls = _fake_hub(monkeypatch, checked.content)
    calls["dir"] = tmp_path
    monkeypatch.setenv(card.TOKEN_ENV, "write-to-the-model-only")
    said = card.upload(root, checked)
    assert calls["token"] == "write-to-the-model-only"
    up = calls["upload"]
    assert (up["path_in_repo"], up["repo_id"], up["repo_type"]) == ("README.md", "lBroth/nullpii", "model")
    assert up["path_or_fileobj"] == checked.content
    assert checked.tag in up["commit_message"] and checked.commit in up["commit_description"]
    assert calls["download"][2]["force_download"] is True
    # Read back at the commit the upload made, not at whatever main is.
    assert calls["download"][2]["revision"] == "c" * 40
    assert "commit/abc" in said


def test_an_upload_that_does_not_read_back_fails(root, monkeypatch, tmp_path):
    checked = _checked(root)
    calls = _fake_hub(monkeypatch, b"another card")
    calls["dir"] = tmp_path
    monkeypatch.setenv(card.TOKEN_ENV, "t")
    with pytest.raises(card.CardError, match="is not MODEL_CARD.md after the upload"):
        card.upload(root, checked)
