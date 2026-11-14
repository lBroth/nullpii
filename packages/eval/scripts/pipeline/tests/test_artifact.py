# SPDX-License-Identifier: Apache-2.0
"""A capture's output is offsets, labels, scores and counts; anything else
stops the capture before CI can upload it, and the error shows no value."""
import json

import pytest

from pipeline import artifact, settings

SECRET = "AKIA-not-a-real-key-0000"


def _jsonl(tmp_path, rows):
    path = tmp_path / "capture.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in rows) + "\n")
    return path


def test_checkpoint_and_span_rows_pass(tmp_path):
    rows = [
        {"idx": 0, "spans": [[0, 4, "private_person"]]},
        {"idx": 1, "spans": []},
        {"dataset": "ai4privacy-en", "idx": 2, "spans": [[3, 9, "private_email", 0.97]]},
    ]
    assert artifact.check_spans(_jsonl(tmp_path, rows)) == 3


@pytest.mark.parametrize("row", [
    {"idx": 0, "spans": [[0, 4, "person"]]},
    {"idx": 0, "spans": [[0, 4, "O"]]},
    {"idx": 0, "spans": [[0, 4, "hunter2"]]},
    {"dataset": "not-a-set", "idx": 0, "spans": []},
    {"dataset": "ab1-a", "idx": 0, "spans": []},
])
def test_a_label_or_set_name_that_is_not_the_benchmarks_is_refused(tmp_path, row):
    path = _jsonl(tmp_path, [row])
    with pytest.raises(artifact.NotOffsetsOnly, match="capture.jsonl:1: a row that is not offsets and labels"):
        artifact.check_spans(path, datasets=frozenset({"privy"}))


def test_the_span_labels_are_the_librarys():
    import re
    from pipeline import views
    text = (views.ROOT / "src" / "types" / "labels.ts").read_text()
    block = text.split("export const PII_LABELS = [", 1)[1].split("] as const;", 1)[0]
    assert set(re.findall(r"'([a-z_A-Z]+)'", block)) - {"O"} == settings.SPAN_LABELS


def test_the_recognizer_folder_holds_its_three_files_and_nothing_else(tmp_path):
    for key in settings.AB1_GOLD:
        (tmp_path / f"{key}.jsonl").write_text(json.dumps({"idx": 0, "spans": [[0, 3, "secret"]]}) + "\n")
    assert artifact.check_recognizers(tmp_path) == 3
    (tmp_path / "texts.jsonl").write_text("{}\n")
    with pytest.raises(artifact.NotOffsetsOnly, match="holds"):
        artifact.check_recognizers(tmp_path)
    (tmp_path / "texts.jsonl").unlink()
    (tmp_path / "ab1-a.jsonl").unlink()
    with pytest.raises(artifact.NotOffsetsOnly, match="holds"):
        artifact.check_recognizers(tmp_path)


@pytest.mark.parametrize("row", [
    {"idx": 0, "spans": [], "text": SECRET},
    {"idx": 0, "spans": [[0, 4, "private_person", 0.9, SECRET]]},
    {"idx": 0, "spans": [[0, 4, SECRET * 4]]},
    {"idx": 0, "spans": [[0, 4, SECRET]]},
    {"idx": 0, "spans": [[0, 4, "private_person", SECRET]]},
    {"idx": 0, "spans": [["0", 4, "private_person"]]},
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
    {"docs": 1, "masked": 1, "roundtrip_failures": 1, "failing_idx": {SECRET: [0]}},
])
def test_a_round_trip_result_with_anything_else_is_refused(result):
    with pytest.raises(artifact.NotOffsetsOnly) as caught:
        artifact.check_roundtrip(result)
    assert SECRET not in str(caught.value)
