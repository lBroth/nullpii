#!/usr/bin/env bash
#
# One-shot publish of the nullpii fine-tune (PT + ONNX FP32 + ONNX INT4 +
# tokenizer + model card) to HuggingFace Hub.
#
# Prerequisites:
#   pip install huggingface_hub
#   huggingface-cli login           # interactive, one time
#   git lfs install                 # for *.bin / *.onnx
#
# Inputs (override via env):
#   HF_REPO           — target HF model repo, default lBroth/nullpii
#   V2_PT_DIR         — path to PT checkpoint, default packages/eval/results/train/gliner-pii-finetuned-v2/final
#   V2_ONNX_DIR       — path to ONNX dir, default packages/eval/results/train/gliner-pii-finetuned-v2-onnx
#   STAGING_DIR       — temp dir for the assembled HF tree, default ./hf-staging
#
# Usage:
#   bash scripts/release/push-to-hf.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

HF_REPO="${HF_REPO:-lBroth/nullpii}"
V2_PT_DIR="${V2_PT_DIR:-$REPO_ROOT/packages/eval/results/train/gliner-pii-finetuned-v2/final}"
V2_ONNX_DIR="${V2_ONNX_DIR:-$REPO_ROOT/packages/eval/results/train/gliner-pii-finetuned-v2-onnx}"
STAGING_DIR="${STAGING_DIR:-$REPO_ROOT/hf-staging}"

if [ ! -d "$V2_PT_DIR" ] || [ ! -d "$V2_ONNX_DIR" ]; then
    echo "missing v2 dirs:" >&2
    echo "  PT:   $V2_PT_DIR" >&2
    echo "  ONNX: $V2_ONNX_DIR" >&2
    exit 2
fi

echo "[hf-publish] target repo: $HF_REPO"
echo "[hf-publish] staging dir: $STAGING_DIR"

rm -rf "$STAGING_DIR"
mkdir -p "$STAGING_DIR"

# Layout in HF repo:
#   ./pytorch_model.bin (or model.safetensors), gliner_config.json, tokenizer*.json
#   ./onnx/model.onnx, model_int4.onnx, model_int8.onnx
#   ./README.md (model card)
#   ./LICENSE

cp -v "$V2_PT_DIR"/* "$STAGING_DIR/"
mkdir -p "$STAGING_DIR/onnx"
cp -v "$V2_ONNX_DIR"/*.onnx "$STAGING_DIR/onnx/"
cp -v "$V2_ONNX_DIR"/gliner_config.json "$STAGING_DIR/onnx/" 2>/dev/null || true
cp -v "$V2_ONNX_DIR"/tokenizer*.json "$STAGING_DIR/onnx/" 2>/dev/null || true

# Model card lives at scripts/release/MODEL_CARD.md.
if [ -f "$REPO_ROOT/scripts/release/MODEL_CARD.md" ]; then
    cp -v "$REPO_ROOT/scripts/release/MODEL_CARD.md" "$STAGING_DIR/README.md"
else
    echo "[hf-publish] no MODEL_CARD.md — placeholder will be written"
    echo "# nullpii (placeholder)" > "$STAGING_DIR/README.md"
fi
cp -v "$REPO_ROOT/LICENSE" "$STAGING_DIR/LICENSE" 2>/dev/null || true

cd "$STAGING_DIR"

# Initialize as a HF repo. `huggingface-cli repo create` is idempotent.
huggingface-cli repo create "$HF_REPO" --type model --yes >/dev/null 2>&1 || true

git init -q
git lfs install
git lfs track "*.bin" "*.onnx" "*.safetensors"
git add .gitattributes
git remote remove origin 2>/dev/null || true
git remote add origin "https://huggingface.co/$HF_REPO"
git fetch origin main 2>/dev/null || true

git add .
git commit -q -m "Publish nullpii (PT + ONNX FP32 + ONNX INT4)"
git branch -M main
git push -u origin main

echo "[hf-publish] done → https://huggingface.co/$HF_REPO"
