# SPDX-License-Identifier: Apache-2.0
"""A capture's output is offsets, labels, scores and counts; anything else
stops the capture before CI can upload it, and the error shows no value."""
import json

import pytest

from pipeline import artifact

SECRET = "AKIA-not-a-real-key-0000"


def _jsonl(tmp_path, rows):
    path = tmp_path / "capture.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + "\n")
    return path


def test_checkpoint_and_span_rows_pass(tmp_path):
    rows = [
        {"idx": 0, "spans": [[0, 4, "person"]]},
        {"idx": 1, "spans": []},
        {"dataset": "ai4privacy-en", "idx": 2, "spans": [[3, 9, "email", 0.97]]},
    ]
    assert artifact.check_spans(_jsonl(tmp_path, rows)) == 3


@pytest.mark.parametrize("row", [
    {"idx": 0, "spans": [], "text": SECRET},
    {"idx": 0, "spans": [[0, 4, "person", 0.9, SECRET]]},
    {"idx": 0, "spans": [[0, 4, SECRET * 4]]},
    {"idx": 0, "spans": [[0, 4, "person", SECRET]]},
    {"idx": 0, "spans": [["0", 4, "person"]]},
    {"idx": "0", "spans": []},
    {"dataset": SECRET * 4, "idx": 0, "spans": []},
    {"idx": 0},
    [0, []],
])
def test_a_row_with_anything_else_is_refused_without_showing_it(tmp_path, row):
    path = _jsonl(tmp_path, [{"idx": 0, "spans": []}, row])
    with pytest.raises(artifact.NotOffsetsOnly) as caught:
        artifact.check_spans(path)
    assert str(caught.value) == "capture.jsonl:2: a row that is not offsets and labels"


def test_a_line_that_is_not_json_is_refused_without_showing_it(tmp_path):
    path = tmp_path / "capture.jsonl"
    path.write_text(f'{{"idx": 0, "spans": []}}\n{SECRET}\n')
    with pytest.raises(artifact.NotOffsetsOnly, match=r"^capture.jsonl:2: not a JSON row$"):
        artifact.check_spans(path)


def test_the_round_trip_result_is_counts_and_indices():
    result = {"docs": 16572, "masked": 13704, "roundtrip_failures": 1, "failing_idx": {"ab1-b2": [7]}}
    assert artifact.check_roundtrip(result) is result


@pytest.mark.parametrize("result", [
    {"docs": 1, "masked": 1, "roundtrip_failures": 0, "failing_idx": {}, "text": SECRET},
    {"docs": 1, "masked": 1, "roundtrip_failures": 0},
    {"docs": "1", "masked": 1, "roundtrip_failures": 0, "failing_idx": {}},
    {"docs": 1, "masked": 1, "roundtrip_failures": 1, "failing_idx": {"ab1-a": [SECRET]}},
    {"docs": 1, "masked": 1, "roundtrip_failures": 1, "failing_idx": {SECRET * 4: [0]}},
])
def test_a_round_trip_result_with_anything_else_is_refused(result):
    with pytest.raises(artifact.NotOffsetsOnly) as caught:
        artifact.check_roundtrip(result)
    assert SECRET not in str(caught.value)
