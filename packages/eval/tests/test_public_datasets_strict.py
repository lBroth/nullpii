# SPDX-License-Identifier: Apache-2.0
"""Pre-release strict-load contract: public dataset loaders MUST raise
on schema regressions instead of silently dropping samples.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Skip whole file if huggingface `datasets` isn't installed (CI matrix
# may run a "core only" job without it). Keeps the strict-load contract
# tests visible without forcing a heavy dep on every consumer.
pytest.importorskip("datasets")

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "packages" / "eval" / "src"))

from nullpii_eval import public_datasets  # noqa: E402


def _fake_ds(rows: list[dict]):
    """Return an iterable that mimics a HF `datasets.Dataset`."""
    class _Iter:
        def __iter__(self):
            return iter(rows)
    return _Iter()


def test_load_isotonic_raises_on_empty_unmasked_text() -> None:
    rows = [
        {"language": "en", "unmasked_text": "good text", "span_labels": []},
        {"language": "en", "unmasked_text": "", "span_labels": []},
    ]
    with patch("datasets.load_dataset", return_value=_fake_ds(rows)):
        with pytest.raises(ValueError, match="empty unmasked_text"):
            public_datasets._load_isotonic(max_samples=10, lang="en")


def test_load_isotonic_raises_on_unparseable_span_labels() -> None:
    rows = [
        {"language": "en", "unmasked_text": "txt", "span_labels": "not[a]list)"},
    ]
    with patch("datasets.load_dataset", return_value=_fake_ds(rows)):
        with pytest.raises(ValueError, match="could not parse span_labels"):
            public_datasets._load_isotonic(max_samples=10, lang="en")


def test_load_isotonic_raises_on_malformed_span_entry() -> None:
    rows = [
        {"language": "en", "unmasked_text": "txt", "span_labels": [["only-2-fields"]]},
    ]
    with patch("datasets.load_dataset", return_value=_fake_ds(rows)):
        with pytest.raises(ValueError, match="malformed span entry"):
            public_datasets._load_isotonic(max_samples=10, lang="en")


def test_load_isotonic_skips_non_matching_locale_silently() -> None:
    """Locale filter is NOT a schema error — those rows are wrongly-labelled
    and we just want our slice. This must NOT raise."""
    rows = [
        {"language": "fr", "unmasked_text": "salut", "span_labels": []},
        {"language": "en", "unmasked_text": "hello", "span_labels": []},
    ]
    with patch("datasets.load_dataset", return_value=_fake_ds(rows)):
        ds = public_datasets._load_isotonic(max_samples=10, lang="en")
    assert len(ds.samples) == 1
    assert ds.samples[0].text == "hello"


def test_thestack_planted_raises_on_zero_samples() -> None:
    """If every row falls below the length cutoff, raise — never ship empty."""
    short_rows = [{"content": "x"} for _ in range(10)]
    with patch("datasets.load_dataset", return_value=_fake_ds(short_rows)):
        with pytest.raises(RuntimeError, match="produced 0 samples"):
            public_datasets._load_thestack_planted(max_samples=5)
