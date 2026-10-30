# SPDX-License-Identifier: Apache-2.0
"""What a capture leaves behind holds offsets, labels, scores and counts,
never text. The frozen sets hold real secrets and data that may not be
passed on, and a CI run uploads these files as artifacts, so every capture
reads its output back and refuses anything else. An error names the file
and the line, never a value."""
from __future__ import annotations

import json
from pathlib import Path

ROW_KEYS = frozenset({"dataset", "idx", "spans"})
# A span is [start, end, label], or [start, end, label, score].
SPAN_LENGTHS = (3, 4)
# Labels and set names are short identifiers; anything longer is not one.
MAX_NAME = 64
ROUNDTRIP_KEYS = frozenset({"docs", "masked", "roundtrip_failures", "failing_idx"})


class NotOffsetsOnly(Exception):
    """A capture output carries something other than offsets and labels."""


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_name(value: object) -> bool:
    return isinstance(value, str) and len(value) <= MAX_NAME


def _span_ok(span: object) -> bool:
    if not isinstance(span, list) or len(span) not in SPAN_LENGTHS:
        return False
    start, end, label = span[:3]
    score_ok = len(span) == 3 or (isinstance(span[3], (int, float)) and not isinstance(span[3], bool))
    return _is_int(start) and _is_int(end) and _is_name(label) and score_ok


def _row_ok(row: object) -> bool:
    if not isinstance(row, dict) or not set(row) <= ROW_KEYS or not _is_int(row.get("idx")):
        return False
    if "dataset" in row and not _is_name(row["dataset"]):
        return False
    spans = row.get("spans")
    return isinstance(spans, list) and all(_span_ok(s) for s in spans)


def check_spans(path: Path) -> int:
    """Raise NotOffsetsOnly unless every row of the JSONL file `path` is
    `{"idx", "spans"}` (with a `"dataset"` name or not) whose spans are
    offsets, a label and maybe a score. Returns the number of rows."""
    rows = 0
    with path.open(encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                raise NotOffsetsOnly(f"{path.name}:{number}: not a JSON row") from None
            if not _row_ok(row):
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
        _is_name(k) and isinstance(v, list) and all(_is_int(i) for i in v) for k, v in failing.items()
    ):
        raise NotOffsetsOnly("the round trip's failing documents are not set names and indices")
    return result
