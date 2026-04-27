# SPDX-License-Identifier: Apache-2.0
"""Bundled datasets — no gated downloads, no real PII."""
from __future__ import annotations

import json
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


@dataclass(frozen=True, slots=True)
class Dataset:
    locale: str
    samples: tuple[Sample, ...]


LOCALES: tuple[str, ...] = ("en", "it", "de", "fr", "es")
ADVERSARIAL = "adversarial"


def load(locale: str) -> Dataset:
    """Load `<locale>-baseline.jsonl` (or `adversarial.jsonl`)."""
    name = f"{locale}.jsonl" if locale == ADVERSARIAL else f"{locale}-baseline.jsonl"
    path = DATASETS_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"dataset not found: {path}")
    samples: list[Sample] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            spans = tuple(Span(s["label"], int(s["start"]), int(s["end"])) for s in row["spans"])
            samples.append(Sample(row["text"], spans))
    return Dataset(locale=locale, samples=tuple(samples))
