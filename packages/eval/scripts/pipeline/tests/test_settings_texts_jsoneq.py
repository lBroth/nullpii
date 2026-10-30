# SPDX-License-Identifier: Apache-2.0
"""The presets, the text rows, and the JSON comparison."""
import json
from dataclasses import dataclass

import pytest

from pipeline import jsoneq, settings, texts


def test_each_preset_has_its_tool_name_and_engine_options():
    assert settings.tool_name("default") == settings.BASELINE == "nullpii-default"
    assert json.loads(settings.preset_config("default")) == {}
    assert json.loads(settings.preset_config("everything")) == {"disabledCategories": []}
    assert settings.OTHER_NULLPII == ("nullpii-everything",)


def test_an_unknown_preset_is_refused():
    with pytest.raises(ValueError, match="unknown preset 'core'"):
        settings.tool_name("core")


@dataclass
class _Sample:
    text: str


def test_rows_keep_each_loaders_order_as_idx(tmp_path):
    loaders = {"ab1-a": lambda n: [_Sample("x"), _Sample("y")], "ab1-b1": lambda n: [_Sample("z")]}
    out = tmp_path / "t.jsonl"
    assert texts.write(["ab1-a", "ab1-b1"], out, loaders) == 3
    rows = [json.loads(line) for line in out.read_text().splitlines()]
    assert rows == [
        {"dataset": "ab1-a", "idx": 0, "text": "x"},
        {"dataset": "ab1-a", "idx": 1, "text": "y"},
        {"dataset": "ab1-b1", "idx": 0, "text": "z"},
    ]


def test_an_unknown_dataset_is_refused():
    with pytest.raises(KeyError, match="no dataset 'r3-nope'"):
        list(texts.rows(["r3-nope"], {}))


def test_equal_values_have_no_difference():
    a = {"x": [1, 0.5, {"y": None}], "z": "s"}
    assert jsoneq.differences(a, json.loads(json.dumps(a))) == []
    assert jsoneq.differences({"f": 0.1 + 0.2}, {"f": 0.3}) == []


def test_every_difference_is_named_by_its_path():
    diffs = jsoneq.differences({"a": [1, 2], "b": 1.0, "c": 1}, {"a": [1, 3], "b": 1.5, "d": 1})
    assert diffs == ["/a[1]: 2 against 3", "/b: 1.0 against 1.5", "/c: only in the first", "/d: only in the second"]


def test_a_type_or_length_change_is_a_difference():
    assert jsoneq.differences([1], [1, 2]) == ["/: 1 items against 2"]
    assert jsoneq.differences({"t": True}, {"t": 1}) == ["/t: True against 1"]
