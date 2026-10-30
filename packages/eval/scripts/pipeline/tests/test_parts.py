# SPDX-License-Identifier: Apache-2.0
"""A group captured in parts is every text once, in order, balanced by
characters; the parts are put together only when they are every row of
the group once, and a limited (dry-run) capture never."""
import json
from collections import Counter
from pathlib import Path

import pytest

from pipeline import parts
from pipeline.parts import PartError, Shard


def _texts(path: Path, lengths: dict[str, list[int]]) -> Path:
    rows = [{"dataset": d, "idx": i, "text": "x" * n} for d, ns in lengths.items() for i, n in enumerate(ns)]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    return path


def _picked(path: Path) -> list[tuple[str, int]]:
    return [(r["dataset"], r["idx"]) for r in map(json.loads, path.read_text().splitlines())]


@pytest.mark.parametrize("count", [1, 2, 3, 5, 9])
def test_the_shards_are_every_text_once_in_order(tmp_path, count):
    full = _texts(tmp_path / "all.jsonl", {"a": [5, 100, 3, 3, 3, 40], "b": [1] * 7, "c": [250, 2]})
    picked, totals = [], None
    for k in range(1, count + 1):
        rows, totals_k = parts.select(full, tmp_path / f"s{k}.jsonl", Shard(k, count))
        totals = totals or totals_k
        assert totals_k == totals
        assert rows == dict(Counter(d for d, _ in _picked(tmp_path / f"s{k}.jsonl")))
        picked += _picked(tmp_path / f"s{k}.jsonl")
    assert picked == _picked(full)
    assert totals == {"a": 6, "b": 7, "c": 2}


def test_the_shards_are_balanced_by_characters(tmp_path):
    full = _texts(tmp_path / "all.jsonl", {"a": [10] * 100})
    sizes = []
    for k in range(1, 5):
        parts.select(full, tmp_path / f"s{k}.jsonl", Shard(k, 4))
        sizes.append(len(_picked(tmp_path / f"s{k}.jsonl")))
    assert sizes == [25, 25, 25, 25]


def test_a_shard_can_be_empty_when_one_text_outweighs_the_rest(tmp_path):
    full = _texts(tmp_path / "all.jsonl", {"a": [1000, 1]})
    got = [parts.select(full, tmp_path / f"s{k}.jsonl", Shard(k, 3))[0] for k in (1, 2, 3)]
    assert got == [{"a": 1}, {}, {"a": 1}]


def test_a_limit_keeps_the_first_texts_of_each_set(tmp_path):
    full = _texts(tmp_path / "all.jsonl", {"a": [1, 2, 3], "b": [4, 5]})
    rows, totals = parts.select(full, tmp_path / "s.jsonl", parts.WHOLE, limit=2)
    assert _picked(tmp_path / "s.jsonl") == [("a", 0), ("a", 1), ("b", 0), ("b", 1)]
    assert rows == totals == {"a": 2, "b": 2}


@pytest.mark.parametrize("text", ["1/0", "0/1", "2/1", "1", "1/2/3", "a/2", " 1/2", "01/2"])
def test_a_shard_is_k_of_n_from_1(text):
    with pytest.raises(ValueError):
        Shard.parse(text)


def test_a_shard_reads_and_names_itself():
    assert Shard.parse("2/6") == Shard(2, 6)
    assert Shard(2, 6).label == "2-of-6"
    assert parts.part_name("r3", "default", Shard(2, 6)) == "r3-default-2-of-6"


# Putting the parts together -------------------------------------------------------

def _part(root: Path, group: str, preset: str, shard: Shard, files: dict[str, list[dict]],
          rows: dict[str, int], totals: dict[str, int], limit=None) -> Path:
    part = root / parts.part_name(group, preset, shard)
    part.mkdir(parents=True)
    for name, content in files.items():
        if name == parts.ROUNDTRIP_FILE:
            (part / name).write_text(json.dumps(content) + "\n")
        else:
            (part / name).write_text("".join(json.dumps(r) + "\n" for r in content))
    parts.write_marker(part, group, preset, shard, rows, totals, limit)
    return part


def _targets(tmp_path: Path) -> parts.Targets:
    return parts.Targets(tmp_path / "run" / "checkpoints", tmp_path / "spans", tmp_path / "out" / "ab1" / "roundtrip.json")


CK = "nullpii-default-r3-redact.jsonl"
TOTALS = {"r3-redact": 3}


def _two_shards(root: Path, second=None, **kw):
    _part(root, "r3", "default", Shard(1, 2), {CK: [{"idx": 0, "spans": []}, {"idx": 1, "spans": [[0, 1, "x"]]}]},
          {"r3-redact": 2}, TOTALS, **kw)
    _part(root, "r3", "default", Shard(2, 2), {CK: second or [{"idx": 2, "spans": []}]}, {"r3-redact": 1}, TOTALS, **kw)


def test_the_parts_of_a_group_are_put_together_in_order(tmp_path):
    _two_shards(tmp_path / "parts")
    assert parts.assemble(tmp_path / "parts", _targets(tmp_path)) == [("r3", "default")]
    rows = [json.loads(r) for r in (tmp_path / "run" / "checkpoints" / CK).read_text().splitlines()]
    assert [r["idx"] for r in rows] == [0, 1, 2]
    # Again: the same outputs.
    parts.assemble(tmp_path / "parts", _targets(tmp_path))
    assert [json.loads(r)["idx"] for r in (tmp_path / "run" / "checkpoints" / CK).read_text().splitlines()] == [0, 1, 2]


def test_a_missing_shard_is_named(tmp_path):
    _part(tmp_path / "parts", "r3", "default", Shard(1, 3), {CK: [{"idx": 0, "spans": []}]}, {"r3-redact": 1}, TOTALS)
    with pytest.raises(PartError, match="r3 default: shard 2, 3 of 3 not captured"):
        parts.assemble(tmp_path / "parts", _targets(tmp_path))


def test_a_row_captured_twice_is_refused(tmp_path):
    _two_shards(tmp_path / "parts", second=[{"idx": 1, "spans": []}])
    with pytest.raises(PartError, match="a row captured twice, in r3-default-2-of-2"):
        parts.assemble(tmp_path / "parts", _targets(tmp_path))


def test_shards_that_do_not_add_up_to_the_group_are_refused(tmp_path):
    root = tmp_path / "parts"
    _part(root, "r3", "default", Shard(1, 2), {CK: [{"idx": 0, "spans": []}]}, {"r3-redact": 1}, TOTALS)
    _part(root, "r3", "default", Shard(2, 2), {CK: [{"idx": 2, "spans": []}]}, {"r3-redact": 1}, TOTALS)
    with pytest.raises(PartError, match="do not hold every row of the group once"):
        parts.assemble(root, _targets(tmp_path))


def test_parts_of_different_splits_or_texts_are_refused(tmp_path):
    root = tmp_path / "a"
    _part(root, "r3", "default", Shard(1, 2), {CK: [{"idx": 0, "spans": []}]}, {"r3-redact": 1}, TOTALS)
    _part(root, "r3", "default", Shard(2, 3), {CK: [{"idx": 1, "spans": []}]}, {"r3-redact": 1}, TOTALS)
    with pytest.raises(PartError, match="different splits"):
        parts.assemble(root, _targets(tmp_path))
    root = tmp_path / "b"
    _part(root, "r3", "default", Shard(1, 2), {CK: [{"idx": 0, "spans": []}]}, {"r3-redact": 1}, {"r3-redact": 2})
    _part(root, "r3", "default", Shard(2, 2), {CK: [{"idx": 1, "spans": []}]}, {"r3-redact": 1}, {"r3-redact": 3})
    with pytest.raises(PartError, match="cut from different texts"):
        parts.assemble(root, _targets(tmp_path))


def test_a_limited_part_is_never_put_together(tmp_path):
    _two_shards(tmp_path / "parts", limit=3)
    with pytest.raises(PartError, match="limited capture"):
        parts.assemble(tmp_path / "parts", _targets(tmp_path))
    assert not (tmp_path / "run").exists()


def test_an_unfinished_or_misnamed_part_is_refused(tmp_path):
    (tmp_path / "parts" / "r3-default-1-of-1").mkdir(parents=True)
    with pytest.raises(PartError, match="no PART.json, its capture did not finish"):
        parts.assemble(tmp_path / "parts", _targets(tmp_path))
    part = _part(tmp_path / "p2", "r3", "default", Shard(1, 1), {CK: []}, {}, {})
    part.rename(tmp_path / "p2" / "r3-everything-1-of-1")
    with pytest.raises(PartError, match="its PART.json says r3-default-1-of-1"):
        parts.assemble(tmp_path / "p2", _targets(tmp_path))


def test_a_link_where_an_output_goes_is_never_written_through(tmp_path):
    _two_shards(tmp_path / "parts")
    frozen_file = tmp_path / "frozen.jsonl"
    frozen_file.write_text("frozen\n")
    target = tmp_path / "run" / "checkpoints" / CK
    target.parent.mkdir(parents=True)
    target.symlink_to(frozen_file)
    with pytest.raises(PartError, match="is a link"):
        parts.assemble(tmp_path / "parts", _targets(tmp_path))
    assert frozen_file.read_text() == "frozen\n"


def test_piimb_parts_are_keyed_by_task_and_index(tmp_path):
    root = tmp_path / "parts"
    name = parts.piimb_file("everything")
    totals = {"privy": 2, "gretel": 1}
    _part(root, "piimb", "everything", Shard(1, 2), {name: [{"dataset": "privy", "idx": 0, "spans": []},
                                                            {"dataset": "privy", "idx": 1, "spans": []}]},
          {"privy": 2}, totals)
    _part(root, "piimb", "everything", Shard(2, 2), {name: [{"dataset": "gretel", "idx": 0, "spans": []}]},
          {"gretel": 1}, totals)
    parts.assemble(root, _targets(tmp_path))
    rows = [json.loads(r) for r in (tmp_path / "spans" / name).read_text().splitlines()]
    assert [(r["dataset"], r["idx"]) for r in rows] == [("privy", 0), ("privy", 1), ("gretel", 0)]


def test_the_round_trips_parts_add_up(tmp_path):
    root = tmp_path / "parts"
    totals = {"ab1-a": 2, "ab1-b2": 2}
    _part(root, "roundtrip", "default", Shard(1, 2), {parts.ROUNDTRIP_FILE: {
        "docs": 2, "masked": 2, "roundtrip_failures": 1, "failing_idx": {"ab1-a": [1]}}}, {"ab1-a": 2}, totals)
    _part(root, "roundtrip", "default", Shard(2, 2), {parts.ROUNDTRIP_FILE: {
        "docs": 2, "masked": 1, "roundtrip_failures": 2, "failing_idx": {"ab1-b2": [0, 1]}}}, {"ab1-b2": 2}, totals)
    parts.assemble(root, _targets(tmp_path))
    assert json.loads((tmp_path / "out" / "ab1" / "roundtrip.json").read_text()) == {
        "docs": 4, "masked": 3, "roundtrip_failures": 3, "failing_idx": {"ab1-a": [1], "ab1-b2": [0, 1]}}


# A part's own output ----------------------------------------------------------------

def test_a_part_holding_another_file_is_refused(tmp_path):
    part = tmp_path / "r3-default-1-of-1"
    part.mkdir()
    (part / CK).write_text(json.dumps({"idx": 0, "spans": []}) + "\n")
    (part / "texts.jsonl").write_text("{}\n")
    with pytest.raises(PartError, match="holds"):
        parts.check_output(part, "r3", "default", {"r3-redact": 1})


def test_a_part_with_text_in_it_is_refused_without_showing_it(tmp_path):
    from pipeline import artifact
    part = tmp_path / "r3-default-1-of-1"
    part.mkdir()
    (part / CK).write_text(json.dumps({"idx": 0, "spans": [], "text": "a secret"}) + "\n")
    with pytest.raises(artifact.NotOffsetsOnly) as caught:
        parts.check_output(part, "r3", "default", {"r3-redact": 1})
    assert "a secret" not in str(caught.value)


def test_a_round_trip_part_on_fewer_texts_is_refused(tmp_path):
    part = tmp_path / "roundtrip-default-1-of-1"
    part.mkdir()
    (part / parts.ROUNDTRIP_FILE).write_text(json.dumps(
        {"docs": 1, "masked": 1, "roundtrip_failures": 0, "failing_idx": {}}))
    with pytest.raises(PartError, match="ran on 1 texts for 2"):
        parts.check_output(part, "roundtrip", "default", {"ab1-a": 2})
