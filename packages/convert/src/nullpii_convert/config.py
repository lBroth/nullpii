# SPDX-License-Identifier: Apache-2.0
"""Static configuration for the model fetch & verify pipeline."""
from __future__ import annotations

from pathlib import Path

MODEL_ID: str = "openai/privacy-filter"
"""HuggingFace repo ID of the source model."""

UPSTREAM_REVISION: str = "7ffa9a043d54d1be65afb281eddf0ffbe629385b"
"""Pinned upstream commit SHA. Never use `main` for reproducible builds."""

CONSISTENCY_SAMPLES: int = 50
"""Number of bundled fixture prompts used for quantized-vs-fp32 consistency."""

MAX_F1_DIVERGENCE: dict[str, float] = {
    "model_fp16.onnx": 0.005,
    "model_quantized.onnx": 0.010,
    "model_q4.onnx": 0.060,
    "model_q4f16.onnx": 0.060,
}
"""Per-variant divergence cap vs fp32 baseline. Quantized formats trade
accuracy for size/speed; tolerances reflect industry expectations:
- fp16: lossless in practice (≤0.5%)
- int8: ≤1% — production-acceptable
- int4 family: ≤6% — edge/memory-constrained only"""

PACKAGE_ROOT: Path = Path(__file__).resolve().parent.parent.parent
ARTIFACTS_DIR: Path = PACKAGE_ROOT / "artifacts"
MODEL_DIR: Path = ARTIFACTS_DIR / "model"
MANIFEST_PATH: Path = ARTIFACTS_DIR / "manifest.json"

CHECKSUM_SUFFIX: str = ".sha256"

ONNX_VARIANTS: tuple[str, ...] = (
    "model.onnx",
    "model_fp16.onnx",
    "model_quantized.onnx",
    "model_q4.onnx",
    "model_q4f16.onnx",
)
"""Filenames within `onnx/` we fetch and validate."""

ALLOW_PATTERNS: tuple[str, ...] = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "viterbi_calibration.json",
    "model.sig",
    "onnx/*.onnx",
    "onnx/*.onnx_data",
    "onnx/*.onnx_data_*",
)
"""HF snapshot_download allow_patterns."""

TARGET_HF_REPO: str = "nullpii/privacy-filter-onnx"
"""Target HF repo for mirror upload (deferred publish)."""

DOWNLOAD_TIMEOUT_S: int = 300
SMOKE_PROMPT: str = "Hi, my name is John Smith and my email is john@example.com."
"""Fixed prompt used by smoke tests across runs (deterministic)."""
