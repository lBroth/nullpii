# SPDX-License-Identifier: Apache-2.0
"""Tokenizer wrapper around the upstream `tokenizer.json`.

The upstream `tokenizer_config.json` references a custom `TokenizersBackend`
class that `AutoTokenizer` cannot load. We bypass `transformers` and use the
raw `tokenizers` library directly with `Tokenizer.from_file`.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

TOKENIZER_FILE = "tokenizer.json"
TOKENIZER_CONFIG = "tokenizer_config.json"


@lru_cache(maxsize=4)
def _load(model_dir: Path):  # noqa: ANN202 — tokenizers types are dynamic
    from tokenizers import Tokenizer

    tok_path = model_dir / TOKENIZER_FILE
    if not tok_path.is_file():
        raise FileNotFoundError(f"tokenizer: missing {tok_path}")
    return Tokenizer.from_file(str(tok_path))


def _max_length(model_dir: Path) -> int:
    cfg = json.loads((model_dir / TOKENIZER_CONFIG).read_text(encoding="utf-8"))
    raw = cfg.get("model_max_length", 512)
    # cap to a value ORT can handle in seconds, not minutes
    return min(int(raw), 512)


def encode(model_dir: Path, text: str) -> dict[str, "np.ndarray"]:  # type: ignore[name-defined]
    """Encode `text` to numpy int64 arrays: input_ids, attention_mask.
    Output shape is `[1, seq_len]` for both."""
    import numpy as np

    tok = _load(model_dir)
    max_len = _max_length(model_dir)

    tok.enable_truncation(max_length=max_len)
    enc = tok.encode(text)
    ids = enc.ids
    mask = enc.attention_mask
    return {
        "input_ids": np.asarray([ids], dtype=np.int64),
        "attention_mask": np.asarray([mask], dtype=np.int64),
    }
