#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Runs INSIDE the pod. Orchestrates the full comparison bench:
# all tools (nullpii cuda, gliner cuda, presidio, deberta, piiranha,
# regex, ensemble) × all datasets (existing + Tier A: enron, stack
# secrets, SPY/adversarial), serial across datasets, parallel within.
#
# Mode:
#   full   = no caps (millions of samples; resumes on crash)
#   smoke  = 10k cap per dataset (fast sanity)
#
# Resume: bench_full.py writes per-(tool,dataset) checkpoints under
# packages/eval/results/checkpoints/. Re-run to continue from last idx.

set -euo pipefail

MODE="${1:-full}"
REPO=/workspace/nullpii
cd "$REPO"

# shellcheck disable=SC1091
[ -f .env ] && { set -a; source .env; set +a; }

VENV=/workspace/.venv/bin/python
OUT_DIR=packages/eval/results/runpod-$(date -u +%Y%m%d)
mkdir -p "$OUT_DIR/checkpoints"

# CUDA tunables for ONNX-Runtime + transformers on a 4090 (24GB).
export CUDA_VISIBLE_DEVICES=0
export OMP_NUM_THREADS=8
export ORT_DISABLE_ALL_OPTIMIZATION=0
export TF_CPP_MIN_LOG_LEVEL=3
export TOKENIZERS_PARALLELISM=true

EXTRA_FLAGS=""
# RunPod 5090 secure-cloud instance ships 256 vCPU + 1.1 TiB RAM. With
# CPU backend, parallel=4 + pool=8 saturates ~half the cores (room for
# other tools). Override POOL_SIZE / PARALLEL via env if cores differ.
PARALLEL="${PARALLEL:-4}"
POOL_SIZE="${POOL_SIZE:-8}"
case "$MODE" in
    smoke)    EXTRA_FLAGS="--max-per-dataset 1000" ;;
    medium)   EXTRA_FLAGS="" ;;            # per-dataset caps
    full)     EXTRA_FLAGS="--no-cap" ;;    # publishable
    *)
        EXTRA_FLAGS="--datasets $MODE"
        ;;
esac

echo "[bench] mode=$MODE out=$OUT_DIR"
echo "[bench] python=$VENV"
$VENV --version

# BACKEND defaults:
#   smoke = cpu (apple-to-apple sanity)
#   medium/full = cuda for ML competitors, cpu for nullpii (ORT
#                 Blackwell SM_120 MoE limitation)
case "$MODE" in
    smoke) BACKEND_DEFAULT=cpu ;;
    *)     BACKEND_DEFAULT=cuda ;;
esac
BACKEND="${BACKEND:-$BACKEND_DEFAULT}"

# nullpii always cpu on Blackwell. On Ada (4090) cuda works and could
# be set to cuda manually via NULLPII_BACKEND env override.
NULLPII_BE="${NULLPII_BACKEND:-cpu}"

$VENV packages/eval/scripts/bench_full.py \
    --backend "$BACKEND" \
    --nullpii-backend "$NULLPII_BE" \
    --openai-backend cuda \
    --tools nullpii,openai,gliner,presidio,deberta,piiranha,regex,ensemble \
    --datasets all \
    --confusion \
    --parallel-tools "$PARALLEL" \
    $EXTRA_FLAGS \
    --out-dir "$OUT_DIR" \
    --checkpoint-dir "$OUT_DIR/checkpoints" \
    --pool-size "$POOL_SIZE" --threads-each 4 \
    --gliner-threshold 0.8 \
    2>&1 | tee "$OUT_DIR/run.log"

echo "[bench] done → $OUT_DIR"
