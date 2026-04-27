#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Smoke run — capped sample sizes, ~5 min on Apple M.
# Use for CI / dev iteration. Numbers NOT for publication.
set -euo pipefail

OUT_DIR="${OUT_DIR:-out/smoke}"
mkdir -p "$OUT_DIR"

# Bundled (180 samples total — already small)
for loc in en it de fr es; do
  python -m nullpii_eval.run_compare \
    --out "$OUT_DIR/bundled-$loc.json" \
    --dataset bundled --locale "$loc"
done

# Isotonic — 200 per locale (en/it/de/fr; no es upstream)
for loc in en it de fr; do
  python -m nullpii_eval.run_compare \
    --out "$OUT_DIR/isotonic-$loc.json" \
    --dataset isotonic/pii-masking-200k --locale "$loc" --max-samples 200
done

# Presidio synthetic — 500
python -m nullpii_eval.run_compare \
  --out "$OUT_DIR/presidio-syn.json" \
  --dataset presidio-synthetic --max-samples 500

# WikiAnn — 200 per locale
for loc in en it de fr es; do
  python -m nullpii_eval.run_compare \
    --out "$OUT_DIR/wikiann-$loc.json" \
    --dataset wikiann --locale "$loc" --max-samples 200
done

echo "Smoke run complete. Results in $OUT_DIR/"
