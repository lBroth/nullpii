#!/usr/bin/env bash
#
# Push raw LoRA adapter weights + router prototypes to HuggingFace Hub.
#
# This is the upstream of `push-to-hf.sh` — the CI release workflow pulls
# from this repo to do the merge step. Run once after a training session
# (or when adapter weights change). The downstream "router-embedding" HF
# repo with the merged ONNX bundle gets refreshed by `push-to-hf.sh`.
#
# Layout pushed (matches what the merge script expects):
#   adapters/<profile>/{adapter_config.json,adapter_model.safetensors,README.md}
#   router/router-embeddings.npz
#
# Requirements:
#   - HF_TOKEN env or `huggingface-cli login`
#   - LoRA adapter weights at packages/eval/results/train/adapters/<profile>/adapter/
#
# Usage:
#   bash packages/eval/scripts/release/push-adapters-to-hf.sh [--dry-run]

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO_ROOT"

DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=1 ;;
    esac
done

HF_REPO="lBroth/nullpii-adapters"
ADAPTERS_LOCAL="packages/eval/results/train/adapters"
ROUTER_LOCAL="packages/eval/results/train/router"
STAGING="$REPO_ROOT/packages/eval/results/release/adapters-staging"

log() { printf '\n[push-adapters] %s\n' "$*"; }

log "1/2 stage adapter dirs + prototypes → $STAGING"
rm -rf "$STAGING"
mkdir -p "$STAGING/adapters" "$STAGING/router"

for d in devops legal medical narrative enterprise; do
    src="$ADAPTERS_LOCAL/$d/adapter"
    [ -d "$src" ] || { echo "[push-adapters] missing $src" >&2; exit 1; }
    mkdir -p "$STAGING/adapters/$d"
    cp -f \
        "$src/adapter_config.json" \
        "$src/adapter_model.safetensors" \
        "$src/README.md" \
        "$STAGING/adapters/$d/" 2>/dev/null || true
done

cp -f "$ROUTER_LOCAL/router-embeddings.npz" "$STAGING/router/"

du -sh "$STAGING"
ls -lh "$STAGING/adapters/"*/ "$STAGING/router/"

if [ "$DRY_RUN" = 1 ]; then
    log "DRY RUN — skipping upload to $HF_REPO"
    exit 0
fi

log "2/2 upload → $HF_REPO"
HF_TOKEN_ARG=""
[ -n "${HF_TOKEN:-}" ] && HF_TOKEN_ARG="--token $HF_TOKEN"
huggingface-cli upload --repo-type=model $HF_TOKEN_ARG "$HF_REPO" "$STAGING" .

log "DONE — pushed $HF_REPO. Verify at https://huggingface.co/$HF_REPO"
