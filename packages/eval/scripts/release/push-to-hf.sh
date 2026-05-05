#!/usr/bin/env bash
#
# Build + push the nullpii router-stack model artifacts to the HuggingFace Hub.
#
# Pipeline:
#   1. If raw adapter weights aren't present locally, pull them from
#      `lBroth/nullpii-v10-adapters` (one-shot upstream HF repo).
#   2. Merge each per-domain LoRA adapter into base GLiNER → 5 ONNX shards.
#   3. Export distiluse encoder to ONNX + dump prototypes to JSON.
#   4. Stage all artifacts under release/v10-hf-staging/ in the layout the
#      npm runtime expects (matches `src/model-manager.ts:ROUTER_FILES`).
#   5. `huggingface-cli upload` to `lBroth/nullpii-v10-router-embedding`.
#
# Requirements:
#   - HF_TOKEN env or `huggingface-cli login` already done
#   - Python venv at packages/eval/.venv with gliner + peft + onnxruntime + sentence-transformers
#   - The raw adapter weights upstream HF repo `lBroth/nullpii-v10-adapters`
#     must already exist (push it once with `push-adapters-to-hf.sh`).
#
# Usage:
#   bash packages/eval/scripts/release/push-to-hf.sh
#   bash packages/eval/scripts/release/push-to-hf.sh --dry-run   # build + stage but skip upload

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
    esac
done

HF_REPO="lBroth/nullpii-v10-router-embedding"
STAGING="$REPO_ROOT/packages/eval/results/release/v10-hf-staging"
MERGED="$REPO_ROOT/packages/eval/results/release/v10-onnx-merged"
ROUTER="$REPO_ROOT/packages/eval/results/release/v10-router"
HF_CACHE_BASE="$HOME/.cache/huggingface/hub/models--onnx-community--gliner_multi_pii-v1/snapshots"

VENV="$REPO_ROOT/packages/eval/.venv/bin/python"
[ -x "$VENV" ] || { echo "[push-to-hf] python venv missing at $VENV" >&2; exit 1; }

log() { printf '\n[push-to-hf] %s\n' "$*"; }

ADAPTERS_HF="lBroth/nullpii-v10-adapters"
ADAPTERS_LOCAL="$REPO_ROOT/packages/eval/results/train/v10/adapters"
ROUTER_LOCAL="$REPO_ROOT/packages/eval/results/train/v10/router"

# ─── Step 0: pull raw adapter weights from HF if missing ────────────
need_pull=0
for d in devops legal medical narrative enterprise; do
    [ -f "$ADAPTERS_LOCAL/$d/adapter/adapter_model.safetensors" ] || need_pull=1
done
[ -f "$ROUTER_LOCAL/router-embeddings.npz" ] || need_pull=1

if [ "$need_pull" = 1 ]; then
    log "0/4 raw adapter weights not local — pulling $ADAPTERS_HF"
    HF_DL_TOKEN_ARG=""
    [ -n "${HF_TOKEN:-}" ] && HF_DL_TOKEN_ARG="--token $HF_TOKEN"
    PULL_DIR="$REPO_ROOT/packages/eval/results/train/v10/__hf_pull__"
    rm -rf "$PULL_DIR"
    mkdir -p "$PULL_DIR"
    huggingface-cli download --repo-type=model $HF_DL_TOKEN_ARG "$ADAPTERS_HF" --local-dir "$PULL_DIR"
    # Reshape pulled `adapters/<profile>/` → expected `<profile>/adapter/`.
    for d in devops legal medical narrative enterprise; do
        mkdir -p "$ADAPTERS_LOCAL/$d/adapter"
        cp -f "$PULL_DIR/adapters/$d/"* "$ADAPTERS_LOCAL/$d/adapter/" 2>/dev/null
    done
    mkdir -p "$ROUTER_LOCAL"
    cp -f "$PULL_DIR/router/router-embeddings.npz" "$ROUTER_LOCAL/"
    rm -rf "$PULL_DIR"
fi

# Sync v10-weights symlink layout used by the merge script default.
WEIGHTS_LOCAL="$REPO_ROOT/packages/eval/v10-weights"
mkdir -p "$WEIGHTS_LOCAL/adapters" "$WEIGHTS_LOCAL/router"
for d in devops legal medical narrative enterprise; do
    mkdir -p "$WEIGHTS_LOCAL/adapters/$d"
    cp -f "$ADAPTERS_LOCAL/$d/adapter/"{adapter_config.json,adapter_model.safetensors} \
        "$WEIGHTS_LOCAL/adapters/$d/" 2>/dev/null
    [ -f "$ADAPTERS_LOCAL/$d/adapter/README.md" ] && cp -f "$ADAPTERS_LOCAL/$d/adapter/README.md" "$WEIGHTS_LOCAL/adapters/$d/" || true
done
cp -f "$ROUTER_LOCAL/router-embeddings.npz" "$WEIGHTS_LOCAL/router/"

# ─── Step 1: merge LoRA → 5 ONNX shards ─────────────────────────────
log "1/4 merge LoRA adapters → ONNX (FP32)"
"$VENV" -u packages/eval/scripts/release/export_merged_lora_onnx.py --no-quantize

# ─── Step 2: export distiluse + prototypes ──────────────────────────
log "2/4 export distiluse encoder + prototypes"
"$VENV" -u packages/eval/scripts/release/export_router_artifacts.py

# ─── Step 3: stage HF repo layout ───────────────────────────────────
log "3/4 stage HF repo layout → $STAGING"
mkdir -p "$STAGING/v10-onnx-merged"

# Base GLiNER tokenizer + spm + config (from upstream HF cache).
GLINER_BASE=$(ls -dt "$HF_CACHE_BASE"/* 2>/dev/null | head -1)
[ -d "$GLINER_BASE" ] || { echo "[push-to-hf] gliner base not in HF cache: $HF_CACHE_BASE" >&2; exit 1; }
cp -f "$GLINER_BASE/tokenizer.json" "$STAGING/"
cp -f "$GLINER_BASE/spm.model" "$STAGING/"
cp -f "$GLINER_BASE/gliner_config.json" "$STAGING/"

# Distiluse + prototypes.
cp -f "$ROUTER/distiluse.onnx" "$STAGING/"
cp -f "$ROUTER/distiluse-tokenizer.json" "$STAGING/"
cp -f "$ROUTER/router-embeddings.json" "$STAGING/"

# Per-domain merged-LoRA ONNX.
for d in devops legal medical narrative enterprise; do
    src="$MERGED/$d/model.onnx"
    [ -f "$src" ] || { echo "[push-to-hf] missing merged ONNX: $src" >&2; exit 1; }
    mkdir -p "$STAGING/v10-onnx-merged/$d"
    cp -f "$src" "$STAGING/v10-onnx-merged/$d/model.onnx"
done

# Stage README (model card) at the staging root.
cp -f docs/v10/model-cards/router-embedding.md "$STAGING/README.md"

du -sh "$STAGING"
ls -lh "$STAGING/" "$STAGING/v10-onnx-merged"/*

# ─── Step 4: upload to HF ───────────────────────────────────────────
if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN — skipping upload to $HF_REPO"
    log "Inspect $STAGING and run without --dry-run to push."
    exit 0
fi

log "4/4 upload → $HF_REPO"
HF_TOKEN_ARG=""
[ -n "${HF_TOKEN:-}" ] && HF_TOKEN_ARG="--token $HF_TOKEN"
huggingface-cli upload --repo-type=model $HF_TOKEN_ARG "$HF_REPO" "$STAGING" .

log "DONE — pushed $HF_REPO. Verify at https://huggingface.co/$HF_REPO"
