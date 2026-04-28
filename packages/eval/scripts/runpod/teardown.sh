#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Pull remote results, then terminate the pod via RunPod GraphQL API.
# Clears .runpod-state on success.
#
# Usage:
#   bash packages/eval/scripts/runpod/teardown.sh                # pull + terminate
#   bash packages/eval/scripts/runpod/teardown.sh --keep-pod     # only pull
#   bash packages/eval/scripts/runpod/teardown.sh --no-pull      # only terminate

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
STATE="$REPO_ROOT/.runpod-state"
ENV_FILE="$REPO_ROOT/.env"

[ -f "$STATE" ] || { echo "no $STATE — nothing to tear down" >&2; exit 0; }
[ -f "$ENV_FILE" ] || { echo "missing $ENV_FILE" >&2; exit 1; }
# shellcheck disable=SC1090
set -a; source "$STATE"; source "$ENV_FILE"; set +a

KEEP_POD=0
PULL=1
for arg in "$@"; do
    case "$arg" in
        --keep-pod) KEEP_POD=1 ;;
        --no-pull)  PULL=0 ;;
    esac
done

SSH_OPTS="-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -p $SSH_PORT"
RSYNC_SSH="ssh $SSH_OPTS"
REMOTE=/workspace/nullpii

if [ "$PULL" = 1 ]; then
    echo "[teardown] pulling results: $SSH_HOST:$REMOTE/packages/eval/results → $REPO_ROOT/packages/eval/results"
    mkdir -p "$REPO_ROOT/packages/eval/results"
    rsync -az -e "$RSYNC_SSH" \
        "$SSH_USER@$SSH_HOST:$REMOTE/packages/eval/results/" \
        "$REPO_ROOT/packages/eval/results/" || \
        echo "[teardown] rsync failed (pod may already be gone) — continuing"
fi

if [ "$KEEP_POD" = 1 ]; then
    echo "[teardown] --keep-pod: leaving pod $POD_ID alive"
    exit 0
fi

API="https://api.runpod.io/graphql"
AUTH="Authorization: Bearer $RUNPOD_API_KEY"

echo "[teardown] terminating pod $POD_ID"
PAYLOAD='{"query":"mutation { podTerminate(input: { podId: \"'"$POD_ID"'\" }) }"}'
RESP=$(curl -fsSL -X POST -H "$AUTH" -H "Content-Type: application/json" --data "$PAYLOAD" "$API" || true)
echo "[teardown] api response: $RESP"

rm -f "$STATE"
echo "[teardown] cleared $STATE"
