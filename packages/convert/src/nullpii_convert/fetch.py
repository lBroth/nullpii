# SPDX-License-Identifier: Apache-2.0
"""Fetch model artifacts from HuggingFace at a pinned revision."""
from __future__ import annotations

import logging
from pathlib import Path

from huggingface_hub import snapshot_download

from .config import ALLOW_PATTERNS, MODEL_DIR, MODEL_ID, UPSTREAM_REVISION

log = logging.getLogger(__name__)


def fetch_model(target_dir: Path = MODEL_DIR) -> Path:
    """Snapshot-download the model into `target_dir` at the pinned revision.
    Idempotent: HF cache dedupes; rerun produces identical layout."""
    target_dir.mkdir(parents=True, exist_ok=True)
    log.info(
        "fetching %s @ %s -> %s", MODEL_ID, UPSTREAM_REVISION[:12], target_dir,
    )
    snapshot_download(
        repo_id=MODEL_ID,
        revision=UPSTREAM_REVISION,
        local_dir=str(target_dir),
        allow_patterns=list(ALLOW_PATTERNS),
    )
    log.info("fetch complete: %s", target_dir)
    return target_dir


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    fetch_model()
