# SPDX-License-Identifier: Apache-2.0
"""Inter-format consistency: each ONNX variant vs fp32 baseline.

Runs `model.onnx` (fp32) and every quantized variant on a bundled fixture set
of `CONSISTENCY_SAMPLES` deterministic prompts. Compares argmax token labels
and reports macro-F1 vs fp32. Fails if divergence > MAX_F1_DIVERGENCE.
Bundled fixtures keep CI hermetic — no external dataset auth, no flakiness.
"""
from __future__ import annotations

import json
import logging
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .config import CONSISTENCY_SAMPLES, MAX_F1_DIVERGENCE, MODEL_DIR, ONNX_VARIANTS

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class VariantScore:
    variant: str
    f1_vs_fp32: float
    divergence: float
    tolerance: float

    @property
    def passed(self) -> bool:
        return self.divergence <= self.tolerance


def _load_samples(n: int) -> list[str]:
    raw = files("nullpii_convert.fixtures").joinpath("consistency_prompts.json").read_text(
        encoding="utf-8",
    )
    prompts: list[str] = json.loads(raw)
    if len(prompts) < n:
        raise ValueError(
            f"_load_samples: fixtures provide {len(prompts)} prompts, requested {n}",
        )
    log.info("loaded %d bundled prompts (using first %d)", len(prompts), n)
    return prompts[:n]


def _predict(variant_path: Path, model_dir: Path, samples: Iterable[str]) -> list[list[int]]:
    import numpy as np
    import onnxruntime as ort

    from .tokenizer import encode

    sess = ort.InferenceSession(str(variant_path), providers=["CPUExecutionProvider"])
    input_names = {i.name for i in sess.get_inputs()}
    out: list[list[int]] = []
    for text in samples:
        enc = encode(model_dir, text)
        feeds = {k: v.astype(np.int64) for k, v in enc.items() if k in input_names}
        logits = sess.run(None, feeds)[0][0]
        out.append(logits.argmax(axis=-1).tolist())
    return out


def _macro_f1(pred: list[list[int]], base: list[list[int]]) -> float:
    from sklearn.metrics import f1_score

    flat_a: list[int] = [t for seq in pred for t in seq]
    flat_b: list[int] = [t for seq in base for t in seq]
    n = min(len(flat_a), len(flat_b))
    return float(f1_score(flat_b[:n], flat_a[:n], average="macro", zero_division=0))


def consistency(model_dir: Path = MODEL_DIR) -> list[VariantScore]:
    texts = _load_samples(CONSISTENCY_SAMPLES)
    fp32_path = model_dir / "onnx" / "model.onnx"
    if not fp32_path.is_file():
        raise FileNotFoundError(f"consistency: missing fp32 baseline {fp32_path}")
    log.info("running fp32 baseline")
    base = _predict(fp32_path, model_dir, texts)

    scores: list[VariantScore] = []
    for variant in ONNX_VARIANTS:
        if variant == "model.onnx":
            continue
        path = model_dir / "onnx" / variant
        if not path.is_file():
            log.warning("skipping missing variant: %s", variant)
            continue
        log.info("scoring %s", variant)
        pred = _predict(path, model_dir, texts)
        f1 = _macro_f1(pred, base)
        tol = MAX_F1_DIVERGENCE.get(variant, 0.005)
        scores.append(VariantScore(
            variant=variant, f1_vs_fp32=f1, divergence=abs(1.0 - f1), tolerance=tol,
        ))
    return scores


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    scores = consistency()
    for s in scores:
        flag = "OK  " if s.passed else "FAIL"
        log.info(
            "%-26s %s F1=%.4f divergence=%.4f tolerance=%.3f",
            s.variant, flag, s.f1_vs_fp32, s.divergence, s.tolerance,
        )
    failed = [s for s in scores if not s.passed]
    if failed:
        log.error(
            "consistency failed for: %s",
            ", ".join(f"{s.variant} (div={s.divergence:.4f}>{s.tolerance:.3f})" for s in failed),
        )
        return 1
    log.info("consistency passed for %d variant(s)", len(scores))
    return 0


if __name__ == "__main__":
    sys.exit(main())
