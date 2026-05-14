#!/usr/bin/env bash
#
# Build + push the nullpii unified model artifacts to HuggingFace Hub.
#
# Pipeline:
#   1. Merge the trained LoRA adapter into base GLiNER and export ONE
#      ONNX (`export_unified_onnx.py`). Default source = ship adapter
#      under `packages/eval/results/train/unified/run-aug2/adapter`.
#   2. Stage everything under `release/hf-staging/` in the layout the
#      npm runtime expects (`src/model-manager.ts:UNIFIED_FILES`).
#   3. `huggingface-cli upload` → lBroth/nullpii.
#
# Requirements:
#   - HF_TOKEN env or `huggingface-cli login` already done
#   - Python venv at packages/eval/.venv with gliner + peft + onnxruntime
#
# Usage:
#   bash packages/eval/scripts/release/release.sh                # full pipeline
#   bash packages/eval/scripts/release/release.sh --dry-run      # build + stage, no upload
#   ADAPTER_DIR=...  bash …/release.sh                           # override adapter source

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
    DRY_RUN=1
fi

ADAPTER_DIR="${ADAPTER_DIR:-$REPO_ROOT/packages/eval/results/train/unified/run-aug2/adapter}"
STAGING="$REPO_ROOT/packages/eval/results/release/hf-staging"
HF_REPO="${HF_REPO:-lBroth/nullpii}"

VENV="$REPO_ROOT/packages/eval/.venv/bin/python"
[ -x "$VENV" ] || { echo "venv missing at $VENV"; exit 1; }

echo "[release] adapter: $ADAPTER_DIR"
echo "[release] staging: $STAGING"
echo "[release] hf-repo: $HF_REPO  (dry-run=$DRY_RUN)"

# 1. Merge + export.
"$VENV" packages/eval/scripts/release/export_unified_onnx.py \
    --adapter-dir "$ADAPTER_DIR" \
    --out-dir "$STAGING"

# 2. Sanity-check what we staged.
for f in model.onnx tokenizer.json gliner_config.json tokenizer_config.json; do
    [ -f "$STAGING/$f" ] || { echo "[release] missing $f"; exit 1; }
done
echo "[release] staged:"
ls -lh "$STAGING"

# 3. Upload (or skip on dry-run).
if [ "$DRY_RUN" = 1 ]; then
    echo "[release] dry-run: skipping huggingface upload"
    exit 0
fi

"$VENV" -m huggingface_hub.commands.huggingface_cli upload \
    "$HF_REPO" "$STAGING" . \
    --repo-type model
echo "[release] uploaded to https://huggingface.co/$HF_REPO"
