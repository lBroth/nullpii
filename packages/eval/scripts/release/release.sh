#!/usr/bin/env bash
#
# Build + push nullpii model artifacts to HuggingFace Hub.
#
# Pipeline:
#   1. (optional, --push-adapters) push raw LoRA weights + prototypes
#      to lBroth/nullpii-adapters. Run once per training session.
#   2. Pull adapters from HF if not local.
#   3. Merge per-domain LoRA → 5 ONNX shards (export_merged_lora_onnx.py).
#   4. Export distiluse encoder + prototypes JSON (export_router_artifacts.py).
#   5. Stage everything under release/hf-staging/ in the layout the npm
#      runtime expects (`src/model-manager.ts:ROUTER_FILES`).
#   6. huggingface-cli upload → lBroth/nullpii.
#
# Requirements:
#   - HF_TOKEN env or `huggingface-cli login` already done
#   - Python venv at packages/eval/.venv with gliner + peft + onnxruntime + sentence-transformers
#
# Usage:
#   bash packages/eval/scripts/release/release.sh                # full ship pipeline
#   bash packages/eval/scripts/release/release.sh --dry-run      # build + stage, no upload
#   bash packages/eval/scripts/release/release.sh --push-adapters # also push raw adapters
#                                                                # to lBroth/nullpii-adapters first
#   bash packages/eval/scripts/release/release.sh --push-adapters-only --dry-run

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0
PUSH_ADAPTERS=0
ADAPTERS_ONLY=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
        --push-adapters) PUSH_ADAPTERS=1 ;;
        --push-adapters-only) PUSH_ADAPTERS=1; ADAPTERS_ONLY=1 ;;
        *) echo "[release] unknown arg: $arg" >&2; exit 1 ;;
    esac
done

HF_SHIP_REPO="lBroth/nullpii"
HF_ADAPTERS_REPO="lBroth/nullpii-adapters"
ADAPTERS_LOCAL="$REPO_ROOT/packages/eval/results/train/adapters"
ROUTER_LOCAL="$REPO_ROOT/packages/eval/results/train/router"
STAGING_ROOT="$REPO_ROOT/packages/eval/results/release"
ADAPTERS_STAGING="$STAGING_ROOT/adapters-staging"
SHIP_STAGING="$STAGING_ROOT/hf-staging"
MERGED="$STAGING_ROOT/onnx-merged"
ROUTER_OUT="$STAGING_ROOT/router"
WEIGHTS_LOCAL="$REPO_ROOT/packages/eval/weights"
HF_CACHE_BASE="$HOME/.cache/huggingface/hub/models--onnx-community--gliner_multi_pii-v1/snapshots"

VENV="$REPO_ROOT/packages/eval/.venv/bin/python"
[ -x "$VENV" ] || { echo "[release] python venv missing at $VENV" >&2; exit 1; }

log() { printf '\n[release] %s\n' "$*"; }
hf_token_arg() { [ -n "${HF_TOKEN:-}" ] && printf -- '--token %s' "$HF_TOKEN" || true; }

# ── Step 1 (optional): push raw adapters → lBroth/nullpii-adapters ──
if [ "$PUSH_ADAPTERS" = 1 ]; then
    log "1 stage raw adapters + prototypes → $ADAPTERS_STAGING"
    rm -rf "$ADAPTERS_STAGING"
    mkdir -p "$ADAPTERS_STAGING/adapters" "$ADAPTERS_STAGING/router"
    for d in devops legal medical narrative enterprise; do
        src="$ADAPTERS_LOCAL/$d/adapter"
        [ -d "$src" ] || { echo "[release] missing $src" >&2; exit 1; }
        mkdir -p "$ADAPTERS_STAGING/adapters/$d"
        cp -f \
            "$src/adapter_config.json" \
            "$src/adapter_model.safetensors" \
            "$src/README.md" \
            "$ADAPTERS_STAGING/adapters/$d/" 2>/dev/null || true
    done
    cp -f "$ROUTER_LOCAL/router-embeddings.npz" "$ADAPTERS_STAGING/router/"
    du -sh "$ADAPTERS_STAGING"

    if [ "$DRY_RUN" = 1 ]; then
        log "DRY RUN — skipping adapters upload to $HF_ADAPTERS_REPO"
    else
        log "upload adapters → $HF_ADAPTERS_REPO"
        huggingface-cli upload --repo-type=model $(hf_token_arg) "$HF_ADAPTERS_REPO" "$ADAPTERS_STAGING" .
        log "adapters pushed → https://huggingface.co/$HF_ADAPTERS_REPO"
    fi

    [ "$ADAPTERS_ONLY" = 1 ] && exit 0
fi

# ── Step 2: pull adapters from HF if not local ──────────────────────
need_pull=0
for d in devops legal medical narrative enterprise; do
    [ -f "$ADAPTERS_LOCAL/$d/adapter/adapter_model.safetensors" ] || need_pull=1
done
[ -f "$ROUTER_LOCAL/router-embeddings.npz" ] || need_pull=1

if [ "$need_pull" = 1 ]; then
    log "2 raw adapter weights not local — pulling $HF_ADAPTERS_REPO"
    PULL_DIR="$REPO_ROOT/packages/eval/results/train/__hf_pull__"
    rm -rf "$PULL_DIR"
    mkdir -p "$PULL_DIR"
    huggingface-cli download --repo-type=model $(hf_token_arg) "$HF_ADAPTERS_REPO" --local-dir "$PULL_DIR"
    for d in devops legal medical narrative enterprise; do
        mkdir -p "$ADAPTERS_LOCAL/$d/adapter"
        cp -f "$PULL_DIR/adapters/$d/"* "$ADAPTERS_LOCAL/$d/adapter/" 2>/dev/null
    done
    mkdir -p "$ROUTER_LOCAL"
    cp -f "$PULL_DIR/router/router-embeddings.npz" "$ROUTER_LOCAL/"
    rm -rf "$PULL_DIR"
fi

# Sync weights symlink layout used by the merge script default.
mkdir -p "$WEIGHTS_LOCAL/adapters" "$WEIGHTS_LOCAL/router"
for d in devops legal medical narrative enterprise; do
    mkdir -p "$WEIGHTS_LOCAL/adapters/$d"
    cp -f "$ADAPTERS_LOCAL/$d/adapter/"{adapter_config.json,adapter_model.safetensors} \
        "$WEIGHTS_LOCAL/adapters/$d/" 2>/dev/null
    [ -f "$ADAPTERS_LOCAL/$d/adapter/README.md" ] \
        && cp -f "$ADAPTERS_LOCAL/$d/adapter/README.md" "$WEIGHTS_LOCAL/adapters/$d/" || true
done
cp -f "$ROUTER_LOCAL/router-embeddings.npz" "$WEIGHTS_LOCAL/router/"

# ── Step 3: merge LoRA → 5 ONNX shards ──────────────────────────────
log "3 merge LoRA adapters → ONNX (FP32)"
"$VENV" -u packages/eval/scripts/release/export_merged_lora_onnx.py --no-quantize

# ── Step 4: export distiluse + prototypes ───────────────────────────
log "4 export distiluse encoder + prototypes"
"$VENV" -u packages/eval/scripts/release/export_router_artifacts.py

# ── Step 5: stage HF repo layout ────────────────────────────────────
log "5 stage HF repo layout → $SHIP_STAGING"
mkdir -p "$SHIP_STAGING/onnx-merged"

GLINER_BASE=$(ls -dt "$HF_CACHE_BASE"/* 2>/dev/null | head -1)
[ -d "$GLINER_BASE" ] || { echo "[release] gliner base not in HF cache: $HF_CACHE_BASE" >&2; exit 1; }
cp -f "$GLINER_BASE/tokenizer.json" "$SHIP_STAGING/"
cp -f "$GLINER_BASE/spm.model" "$SHIP_STAGING/"
cp -f "$GLINER_BASE/gliner_config.json" "$SHIP_STAGING/"

cp -f "$ROUTER_OUT/distiluse.onnx" "$SHIP_STAGING/"
cp -f "$ROUTER_OUT/distiluse-tokenizer.json" "$SHIP_STAGING/"
cp -f "$ROUTER_OUT/router-embeddings.json" "$SHIP_STAGING/"

for d in devops legal medical narrative enterprise; do
    src="$MERGED/$d/model.onnx"
    [ -f "$src" ] || { echo "[release] missing merged ONNX: $src" >&2; exit 1; }
    mkdir -p "$SHIP_STAGING/onnx-merged/$d"
    cp -f "$src" "$SHIP_STAGING/onnx-merged/$d/model.onnx"
done

cp -f packages/eval/private/model-cards/router.md "$SHIP_STAGING/README.md"

du -sh "$SHIP_STAGING"
ls -lh "$SHIP_STAGING/" "$SHIP_STAGING/onnx-merged"/*

# ── Step 6: upload to HF ────────────────────────────────────────────
if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN — skipping ship upload to $HF_SHIP_REPO"
    log "inspect $SHIP_STAGING and run without --dry-run to push."
    exit 0
fi

log "6 upload → $HF_SHIP_REPO"
huggingface-cli upload --repo-type=model $(hf_token_arg) "$HF_SHIP_REPO" "$SHIP_STAGING" .
log "DONE — pushed $HF_SHIP_REPO. Verify at https://huggingface.co/$HF_SHIP_REPO"
