# SPDX-License-Identifier: Apache-2.0
"""What a capture leaves behind holds offsets, labels, scores and counts,
never text. The frozen sets hold real secrets and data that may not be
passed on, and a CI run uploads these files as artifacts, so every capture
reads its output back and refuses anything else. An error names the file
and the line, never a value."""
from __future__ import annotations

import json
from pathlib import Path

from pipeline import settings

ROW_KEYS = frozenset({"dataset", "idx", "spans"})
# A span is [start, end, label], or [start, end, label, score]; a label is
# one of nullpii's (settings.SPAN_LABELS), a set name one of the
# benchmark's (settings.set_names()).
SPAN_LENGTHS = (3, 4)
RECOGNIZER_FILES = frozenset(f"{key}.jsonl" for key in settings.AB1_GOLD)
ROUNDTRIP_KEYS = frozenset({"docs", "masked", "roundtrip_failures", "failing_idx"})


class NotOffsetsOnly(Exception):
    """A capture output carries something other than offsets and labels."""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _span_ok(span: object, labels: frozenset[str]) -> bool:
    if not isinstance(span, list) or len(span) not in SPAN_LENGTHS:
        return False
    start, end, label = span[:3]
    score_ok = len(span) == 3 or (isinstance(span[3], (int, float)) and not isinstance(span[3], bool))
    return _is_int(start) and _is_int(end) and label in labels and score_ok


def _row_ok(row: object, labels: frozenset[str], datasets: frozenset[str]) -> bool:
    if not isinstance(row, dict) or not set(row) <= ROW_KEYS or not _is_int(row.get("idx")):
        return False
    if "dataset" in row and row["dataset"] not in datasets:
        return False
    spans = row.get("spans")
    return isinstance(spans, list) and all(_span_ok(s, labels) for s in spans)


def check_spans(path: Path, labels: frozenset[str] = settings.SPAN_LABELS,
                datasets: frozenset[str] | None = None) -> int:
    """Raise NotOffsetsOnly unless every row of the JSONL file `path` is
    `{"idx", "spans"}` (with a `"dataset"` among `datasets`, by default
    every set and task of the benchmark, or not) whose spans are offsets,
    a label of `labels` (nullpii's) and maybe a score. Returns the number
    of rows."""
    datasets = settings.set_names() if datasets is None else datasets
    rows = 0
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                raise NotOffsetsOnly(f"{path.name}:{number}: not a JSON row") from None
            if not _row_ok(row, labels, datasets):
                raise NotOffsetsOnly(f"{path.name}:{number}: a row that is not offsets and labels")
            rows += 1
    return rows


def check_roundtrip(result: object) -> dict:
    """Return the round trip's result if it is counts and document indices
    only (`roundtrip.mjs`'s fields); raise NotOffsetsOnly otherwise."""
    if not isinstance(result, dict) or set(result) != ROUNDTRIP_KEYS:
        raise NotOffsetsOnly("the round trip's result has other fields than its counts")
    if not all(_is_int(result[k]) for k in ROUNDTRIP_KEYS - {"failing_idx"}):
        raise NotOffsetsOnly("the round trip's counts are not integers")
    failing = result["failing_idx"]
    if not isinstance(failing, dict) or not all(
        k in settings.set_names() and isinstance(v, list) and all(_is_int(i) for i in v) for k, v in failing.items()
    ):
        raise NotOffsetsOnly("the round trip's failing documents are not set names and indices")
    return result


def check_recognizers(folder: Path) -> int:
    """Raise NotOffsetsOnly unless `folder` holds exactly the recognizer
    pack's span file of each AB-1 set, each offsets and labels only.
    Returns the rows."""
    present = {p.name for p in folder.iterdir()}
    if present != RECOGNIZER_FILES:
        raise NotOffsetsOnly(f"{folder.name}: holds {sorted(present)}, the recognizer capture writes"
                             f" {sorted(RECOGNIZER_FILES)}")
    return sum(check_spans(folder / name) for name in sorted(RECOGNIZER_FILES))
