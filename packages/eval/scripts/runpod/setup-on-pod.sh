#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Runs INSIDE the RunPod pod (via resume.sh). Idempotent: skips steps
# already done. First run installs apt deps + venv + GPU stack; later
# runs only sync python deps if requirements changed.
#
# Assumed image: runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04
# Working dir: /workspace/nullpii (cwd when called).

set -euo pipefail

MARK=/workspace/.setup-done
LOG_PREFIX="[setup-on-pod]"

echo "$LOG_PREFIX repo=$(pwd)"

if [ -f "$MARK" ]; then
    echo "$LOG_PREFIX already setup — skipping apt/venv/onnxruntime install"
else
    echo "$LOG_PREFIX apt deps…"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update -qq
    apt-get install -y -qq \
        build-essential gcc g++ git curl ca-certificates \
        python3.11-venv python3.11-dev \
        netcat-openbsd procps lsof rsync

    echo "$LOG_PREFIX installing Node 22…"
    if ! command -v node >/dev/null 2>&1; then
        curl -fsSL https://deb.nodesource.com/setup_22.x | bash -
        apt-get install -y -qq nodejs
    fi
    node --version

    echo "$LOG_PREFIX nvidia-smi:"
    nvidia-smi || true

    echo "$LOG_PREFIX python venv…"
    if [ ! -d /workspace/.venv ]; then
        python3.11 -m venv /workspace/.venv
    fi
    /workspace/.venv/bin/pip install --quiet --upgrade pip wheel

    echo "$LOG_PREFIX core deps + onnxruntime-gpu + competitors…"
    # Pin torch cu128 FIRST so subsequent installs (gliner pulls torch as
    # transitive dep) reuse it instead of installing the cu130 default
    # wheel that doesn't run on RunPod's CUDA 12.8 driver.
    /workspace/.venv/bin/pip install --quiet \
        torch --index-url https://download.pytorch.org/whl/cu128
    # Then install everything else. gliner pins transformers<5.2; we
    # immediately upgrade transformers to >=5.6 below for the
    # openai/privacy-filter custom architecture (gliner remains
    # functional in our actual call paths despite the pip warning).
    /workspace/.venv/bin/pip install --quiet \
        onnxruntime-gpu \
        gliner \
        presidio-analyzer presidio-anonymizer \
        datasets \
        rich numpy
    /workspace/.venv/bin/pip install --quiet 'transformers>=5.6'

    touch "$MARK"
fi

# eval-package install — required so `from nullpii_eval import ...`
# resolves without sys.path tricks. Failure here is fatal.
echo "$LOG_PREFIX install eval package (editable)…"
/workspace/.venv/bin/pip install --quiet -e packages/eval

# nullpii pool predictor spawns `node bin/nullpii.mjs serve` which loads
# dist/cli/index.js — need built dist. Strip package-lock.json to avoid
# private-registry resolved URLs leaking from the developer's machine.
echo "$LOG_PREFIX npm install + build (nullpii lib)…"
if [ ! -f dist/cli/index.js ]; then
    rm -f package-lock.json
    npm install --silent --registry https://registry.npmjs.org
    npm run build --silent
fi
[ -f dist/cli/index.js ] || { echo "$LOG_PREFIX npm build did not produce dist/cli/index.js" >&2; exit 1; }

# nullpii ONNX model: prefetch on first boot via HF. Path matches the
# eval framework's DEFAULT_MODEL_DIR (packages/convert/artifacts/model).
MODELS_DIR=/workspace/nullpii/packages/convert/artifacts/model
if [ ! -f "$MODELS_DIR/model_fp16.onnx" ] && [ ! -f "$MODELS_DIR/model.fp16.onnx" ]; then
    echo "$LOG_PREFIX downloading openai/privacy-filter ONNX (fp16)…"
    mkdir -p "$MODELS_DIR"
    /workspace/.venv/bin/python -c "
from huggingface_hub import snapshot_download
import os
snapshot_download(
    repo_id='openai/privacy-filter',
    # NB: '*fp16*.onnx_data*' (trailing wildcard) catches sharded
    # external-data files (model_fp16.onnx_data, _1, _2…). Without
    # the trailing star ONNX init fails on shard 1+.
    allow_patterns=['*.json', '*.txt', '*fp16*.onnx', '*fp16*.onnx_data*', 'tokenizer*'],
    local_dir='$MODELS_DIR',
    token=os.environ.get('HUGGING_FACE_HUB_TOKEN') or None,
)
"
fi

echo "$LOG_PREFIX done. python: $(/workspace/.venv/bin/python --version)"
echo "$LOG_PREFIX cuda visible: $(/workspace/.venv/bin/python -c 'import torch; print(torch.cuda.is_available(), torch.cuda.device_count())')"
