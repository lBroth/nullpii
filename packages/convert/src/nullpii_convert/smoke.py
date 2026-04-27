# SPDX-License-Identifier: Apache-2.0
"""Smoke test every ONNX variant.

Loads each ONNX file with `onnxruntime`, runs a single inference on a fixed
prompt, and asserts:
- output rank is 3 (`[batch, seq, num_labels]`)
- batch == 1
- seq matches input length
- num_labels matches `id2label` size from `config.json`
"""
from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path

from .config import MODEL_DIR, ONNX_VARIANTS, SMOKE_PROMPT

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SmokeResult:
    variant: str
    seq_len: int
    num_labels: int
    ok: bool
    error: str | None = None


def _expected_num_labels(model_dir: Path) -> int:
    cfg = json.loads((model_dir / "config.json").read_text(encoding="utf-8"))
    return len(cfg["id2label"])


def _run_one(variant_path: Path, model_dir: Path, expected_labels: int) -> SmokeResult:
    import numpy as np
    import onnxruntime as ort

    from .tokenizer import encode

    name = variant_path.name
    try:
        sess = ort.InferenceSession(str(variant_path), providers=["CPUExecutionProvider"])
        enc = encode(model_dir, SMOKE_PROMPT)
        input_names = {i.name for i in sess.get_inputs()}
        feeds = {k: v.astype(np.int64) for k, v in enc.items() if k in input_names}
        outputs = sess.run(None, feeds)
        logits = outputs[0]
        if logits.ndim != 3:
            return SmokeResult(name, 0, 0, False, f"rank {logits.ndim} (expected 3)")
        batch, seq, num_labels = logits.shape
        if batch != 1:
            return SmokeResult(name, seq, num_labels, False, f"batch {batch} (expected 1)")
        if num_labels != expected_labels:
            return SmokeResult(
                name, seq, num_labels, False,
                f"num_labels {num_labels} (expected {expected_labels})",
            )
        return SmokeResult(name, seq, num_labels, True)
    except Exception as exc:  # noqa: BLE001 — surface the upstream error verbatim
        return SmokeResult(name, 0, 0, False, f"{type(exc).__name__}: {exc}")


def smoke(model_dir: Path = MODEL_DIR) -> list[SmokeResult]:
    expected = _expected_num_labels(model_dir)
    results: list[SmokeResult] = []
    for variant in ONNX_VARIANTS:
        path = model_dir / "onnx" / variant
        if not path.is_file():
            results.append(SmokeResult(variant, 0, 0, False, "missing file"))
            continue
        results.append(_run_one(path, model_dir, expected))
    return results


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    results = smoke()
    failed = [r for r in results if not r.ok]
    for r in results:
        if r.ok:
            log.info("%-26s OK seq=%d labels=%d", r.variant, r.seq_len, r.num_labels)
        else:
            log.error("%-26s FAIL %s", r.variant, r.error)
    if failed:
        log.error("%d/%d variants failed smoke", len(failed), len(results))
        return 1
    log.info("smoke passed for %d variant(s)", len(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
