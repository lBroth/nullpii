"""Shared record types for bundled datasets — Sample / Span / Dataset.

The project's canonical bench file `nullpii-bench.jsonl` is loaded
directly by `scripts/bench_full.py` and `scripts/failure_analysis.py`
via local `_load_nullpii_bench()` helpers. External dataset adapters
(presidio, tab-echr, isotonic, ai4privacy, nemotron, argilla) compose
on top of the Sample / Span / Dataset shape exported here.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

DATASETS_DIR = Path(__file__).resolve().parent.parent.parent / "datasets"


@dataclass(frozen=True, slots=True)
class Span:
    label: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class Sample:
    text: str
    spans: tuple[Span, ...]
    # ISO 639-1 code of the text, where the source records it. Only tools
    # whose documented API takes the language per call receive it (Presidio).
    language: str | None = None
    # Character ranges scored as neither true nor false positive: text the
    # gold deliberately leaves out of scope (R3's non-core labels, a
    # distractor-free traces variant). Gold characters inside one still count.
    ignore: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class Dataset:
    locale: str
    samples: tuple[Sample, ...]
