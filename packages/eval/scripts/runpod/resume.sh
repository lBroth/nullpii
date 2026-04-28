#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# rsync this repo (excluding node_modules, models, .venv) into pod
# /workspace/nullpii, run setup if first time, then resume the bench.
#
# Reads .runpod-state for SSH coords. Idempotent — call any time after
# launch.sh, after a crash, or after editing local code.
#
# Usage:
#   bash packages/eval/scripts/runpod/resume.sh                # full bench resume
#   bash packages/eval/scripts/runpod/resume.sh smoke          # smoke (10k cap)
#   bash packages/eval/scripts/runpod/resume.sh tail           # only tail logs

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
STATE="$REPO_ROOT/.runpod-state"
ENV_FILE="$REPO_ROOT/.env"

[ -f "$STATE" ] || { echo "missing $STATE — run launch.sh first" >&2; exit 1; }
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; source "$STATE"; source "$ENV_FILE"; set +a

MODE="${1:-full}"   # full | smoke | tail | shell

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p $SSH_PORT"
SCP_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -P $SSH_PORT"
SSH="ssh $SSH_OPTS $SSH_USER@$SSH_HOST"
RSYNC_SSH="ssh $SSH_OPTS"
REMOTE=/workspace/nullpii

case "$MODE" in
    tail)
        $SSH "tail -F /workspace/bench.log /workspace/setup.log 2>/dev/null"
        exit 0
        ;;
    shell)
        exec $SSH
        ;;
esac

echo "[resume] ensuring rsync on pod"
$SSH "command -v rsync >/dev/null 2>&1 || (apt-get update -qq && apt-get install -y -qq rsync) >/dev/null 2>&1"

echo "[resume] rsync $REPO_ROOT → $SSH_HOST:$REMOTE"
# -rltz instead of -a: drop ownership preservation (chown fails as
# non-root remote user/uid mismatch noise). Tolerate exit 23 (partial
# transfer with chown warnings — files DID transfer).
rsync -rltz --delete --no-owner --no-group --no-perms \
    --exclude node_modules --exclude .venv --exclude models \
    --exclude '*.onnx' --exclude '*.onnx_data*' --exclude dist --exclude build \
    --exclude packages/eval/results --exclude .git --exclude tmp \
    -e "$RSYNC_SSH" \
    "$REPO_ROOT/" "$SSH_USER@$SSH_HOST:$REMOTE/" || {
    rc=$?
    if [ "$rc" != "23" ] && [ "$rc" != "24" ]; then
        echo "[resume] rsync failed (rc=$rc)" >&2
        exit "$rc"
    fi
    echo "[resume] rsync warnings only (rc=$rc) — continuing"
}

# .env is gitignored — copy explicitly so HF_TOKEN / RUNPOD_API_KEY land.
$SSH "mkdir -p $REMOTE && chmod 700 $REMOTE"
scp $SCP_OPTS "$ENV_FILE" "$SSH_USER@$SSH_HOST:$REMOTE/.env"

echo "[resume] running setup-on-pod.sh (idempotent)"
$SSH "cd $REMOTE && bash packages/eval/scripts/runpod/setup-on-pod.sh 2>&1 | tee /workspace/setup.log"

echo "[resume] launching bench mode=$MODE"
$SSH "cd $REMOTE && nohup bash packages/eval/scripts/runpod/bench-on-pod.sh $MODE > /workspace/bench.log 2>&1 &"
echo "[resume] bench detached. tail with:"
echo "  bash packages/eval/scripts/runpod/resume.sh tail"
