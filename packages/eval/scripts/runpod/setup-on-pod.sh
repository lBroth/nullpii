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
    /workspace/.venv/bin/pip install --quiet \
        onnxruntime-gpu \
        transformers torch \
        gliner \
        presidio-analyzer presidio-anonymizer \
        spacy \
        datasets \
        rich numpy

    /workspace/.venv/bin/python -m spacy download en_core_web_lg --quiet || true

    touch "$MARK"
fi

# Per-run extras (cheap if already installed).
echo "$LOG_PREFIX ensure eval-package python deps…"
if [ -f packages/eval/pyproject.toml ]; then
    /workspace/.venv/bin/pip install --quiet -e packages/eval || true
fi

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
    allow_patterns=['*.json', '*.txt', '*fp16*.onnx', '*fp16*.onnx_data', 'tokenizer*'],
    local_dir='$MODELS_DIR',
    token=os.environ.get('HUGGING_FACE_HUB_TOKEN') or None,
)
" || echo "$LOG_PREFIX (model download deferred — will retry inside bench)"
fi
# Cleanup wrong-path download from earlier setup runs.
rm -rf /workspace/nullpii/models/privacy-filter 2>/dev/null || true

# Symlink venv into eval package so quick scripts find it.
mkdir -p packages/eval/.venv-py/bin
ln -sf /workspace/.venv/bin/python packages/eval/.venv-py/bin/python
ln -sf /workspace/.venv/bin/python3 packages/eval/.venv-py/bin/python3

echo "$LOG_PREFIX done. python: $(/workspace/.venv/bin/python --version)"
echo "$LOG_PREFIX cuda visible: $(/workspace/.venv/bin/python -c 'import torch; print(torch.cuda.is_available(), torch.cuda.device_count())')"
