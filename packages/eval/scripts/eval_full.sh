#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Full release benchmark — no sample caps. Estimated 3-4h on Apple M
# (single-thread CPU, int8 ONNX). These are the numbers you publish.
set -euo pipefail

OUT_DIR="${OUT_DIR:-out/full}"
mkdir -p "$OUT_DIR"

# Bundled (180 samples — fixed size by construction)
for loc in en it de fr es; do
  python -m nullpii_eval.run_compare \
    --out "$OUT_DIR/bundled-$loc.json" \
    --dataset bundled --locale "$loc"
done

# Isotonic — entire test split per locale (~43k en, 51k it, 53k de, 62k fr)
for loc in en it de fr; do
  python -m nullpii_eval.run_compare \
    --out "$OUT_DIR/isotonic-$loc.json" \
    --dataset isotonic/pii-masking-200k --locale "$loc"
done

# Presidio synthetic — 5000 samples (generative; no upstream split)
python -m nullpii_eval.run_compare \
  --out "$OUT_DIR/presidio-syn.json" \
  --dataset presidio-synthetic

# WikiAnn — entire test split per locale (~10k each)
for loc in en it de fr es; do
  python -m nullpii_eval.run_compare \
    --out "$OUT_DIR/wikiann-$loc.json" \
    --dataset wikiann --locale "$loc"
done

echo "Full run complete. Results in $OUT_DIR/"
