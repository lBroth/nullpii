# SPDX-License-Identifier: Apache-2.0
"""Outputs complete enough to render every doc from: `outputs.files()`
with what the docs read beyond what `compare` does (document and item
counts, the README's `+agent` rows of other tools, categories, kinds),
and a copy of the tracked docs to render them into."""
from __future__ import annotations

import json
import shutil
from collections.abc import Callable
from pathlib import Path

from pipeline import compare, docs, settings, views
from pipeline.tests import outputs
from pipeline.tests.outputs import Files, against

A = compare.ab1_file("scores", "ab1-a")
B1 = compare.ab1_file("scores", "ab1-b1")
B2 = compare.ab1_file("scores", "ab1-b2")
R3 = compare.r3_file("char-r3")
R3_EN = compare.r3_file("char-r3-en")
RIZZO, PRESIDIO = "rizzo-pii+agent", "presidio+agent"


def _detail(row: dict, leak: dict[str, float] | None = None) -> dict:
    row.update(docs=966, items={"must_mask": 3386, "must_keep": 5676},
               keep_by_kind={"uuid": [0.979, 145], "reserved_address": [0.575, 160], "date": [0.9, 727]},
               leak_by_category={c: [r, n] for c, (r, n) in {
                   "person": (0.235, 969), "url": (0.305, 59), "email": (0.0, 536), **(leak or {})}.items()})
    return row


def _ab1(scores: dict) -> None:
    for row in scores.values():
        _detail(row)
    scores[RIZZO] = _detail(against(leak=0.081, keep=0.445, leak_ci=(-0.0004, 0.026), keep_ci=(0.387, 0.434)),
                            {"person": (0.1, 969), "url": (0.4, 59)})
    scores[PRESIDIO] = _detail(against(leak=0.406, keep=0.823, leak_ci=(-0.33, -0.29), keep_ci=(0.014, 0.05)),
                               {"person": (0.5, 969), "url": (0.2, 59)})


def _r3(report: dict) -> None:
    for dataset, rows in report.items():
        if dataset != compare.MACRO:
            for row in rows.values():
                row["docs"] = 100


def enrich(out: Files) -> Files:
    for key in settings.AB1_GOLD:
        _ab1(out[compare.ab1_file("scores", key)])
        out[compare.ab1_file("coverage", key)]["secrets"] = 585
    for key in settings.AB1_KIND_SPLITS:
        tools = out[compare.ab1_file(compare.KIND_SPLIT, key)]["tools"]
        tools[RIZZO] = outputs.split_row(280, 400)
        tools[PRESIDIO] = outputs.split_row(290, 1300)
    for rel, data in out.items():
        if rel.startswith("r3/") and rel.endswith(".json") and compare.MACRO in data:
            _r3(data)
    return out


def files() -> Files:
    return enrich(outputs.files())


def published() -> Files:
    return enrich(outputs.published())


def write_run(root: Path, edit: Callable[[Files], None] | None = None, data: Files | None = None) -> Path:
    return outputs.write(root, data if data is not None else files(), edit)


def write_reference(root: Path, edit: Callable[[Files], None] | None = None) -> Path:
    outputs.write(root, published(), edit)
    (root / views.REFERENCE_MARKER).write_text(json.dumps({"reference_of": "test@0", "files": []}))
    return root


def docs_root(tmp: Path) -> Path:
    """A copy of the tracked docs the renderer writes, to render into."""
    root = tmp / "repo"
    for rel in docs.BLOCKS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(views.ROOT / rel, root / rel)
    return root

