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
ADAPTER_REPO="${ADAPTER_REPO:-lBroth/nullpii-adapters}"

# Python runner: prefer the project venv if present (local dev); fall back
# to whatever `python` is on PATH (CI runners install deps system-wide via
# `python -m pip install`).
VENV="$REPO_ROOT/packages/eval/.venv/bin/python"
if [ -x "$VENV" ]; then
    PY="$VENV"
elif command -v python >/dev/null 2>&1; then
    PY="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    echo "[release] no python runtime found (looked for .venv, python, python3)"
    exit 1
fi

# Pull raw adapter from HF if not present locally. Lets CI run without
# git-tracking the trained weights.
if [ ! -d "$ADAPTER_DIR" ]; then
    echo "[release] adapter not found locally at $ADAPTER_DIR"
    echo "[release] fetching from $ADAPTER_REPO …"
    mkdir -p "$(dirname "$ADAPTER_DIR")"
    "$PY" -m huggingface_hub.commands.huggingface_cli download \
        "$ADAPTER_REPO" --repo-type model --local-dir "$ADAPTER_DIR"
fi

echo "[release] python:  $PY"
echo "[release] adapter: $ADAPTER_DIR"
echo "[release] staging: $STAGING"
echo "[release] hf-repo: $HF_REPO  (dry-run=$DRY_RUN)"

# 1. Merge + export.
"$PY" packages/eval/scripts/release/export_unified_onnx.py \
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

"$PY" -m huggingface_hub.commands.huggingface_cli upload \
    "$HF_REPO" "$STAGING" . \
    --repo-type model
echo "[release] uploaded to https://huggingface.co/$HF_REPO"
