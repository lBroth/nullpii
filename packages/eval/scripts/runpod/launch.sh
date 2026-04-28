#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
#
# Spin up a 4090 spot pod via RunPod GraphQL API, register SSH, write
# pod state to .runpod-state (gitignored) so resume.sh / teardown.sh
# can find it later.
#
# Loads RUNPOD_API_KEY + tunables from <repo>/.env (gitignored).
#
# Usage:
#   bash packages/eval/scripts/runpod/launch.sh
#
# Output: pod_id + ssh command printed; .runpod-state written.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
STATE="$REPO_ROOT/.runpod-state"
ENV_FILE="$REPO_ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "missing $ENV_FILE — copy .env.example and fill RUNPOD_API_KEY" >&2
    exit 1
fi
# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a

: "${RUNPOD_API_KEY:?RUNPOD_API_KEY not set in .env}"
POD_NAME="${RUNPOD_POD_NAME:-nullpii-bench-5090}"
GPU_TYPE_ID="${RUNPOD_GPU_TYPE_ID:-NVIDIA GeForce RTX 5090}"
VOLUME_GB="${RUNPOD_VOLUME_GB:-75}"
CONTAINER_GB="${RUNPOD_CONTAINER_GB:-40}"
IMAGE="${RUNPOD_IMAGE:-runpod/pytorch:2.8.0-py3.11-cuda12.8.1-cudnn-devel-ubuntu22.04}"
# CloudType: SECURE = on-demand (no preemption); COMMUNITY = community
# cloud (cheaper, may include spot offerings).
CLOUD_TYPE="${RUNPOD_CLOUD_TYPE:-SECURE}"

API="https://api.runpod.io/graphql"
AUTH="Authorization: Bearer $RUNPOD_API_KEY"

# Inject the actual SSH pubkey (jq-free expansion).
PUBKEY_FILE=""
for f in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa.pub"; do
    [ -f "$f" ] && PUBKEY_FILE="$f" && break
done
if [ -z "$PUBKEY_FILE" ]; then
    echo "[launch] no SSH pubkey found in ~/.ssh/id_{ed25519,rsa}.pub" >&2
    echo "[launch] generate one: ssh-keygen -t ed25519 -N '' -f ~/.ssh/id_ed25519" >&2
    exit 2
fi
PUBKEY=$(tr -d '\n' < "$PUBKEY_FILE" | sed 's/"/\\"/g')

echo "[launch] requesting on-demand pod: gpu=$GPU_TYPE_ID cloud=$CLOUD_TYPE name=$POD_NAME image=$IMAGE"

# podFindAndDeployOnDemand = on-demand (no spot eviction). cloudType
# SECURE = guaranteed availability; COMMUNITY = cheaper but variable.
PAYLOAD=$(cat <<EOF
{"query":"mutation { podFindAndDeployOnDemand(input: { cloudType: $CLOUD_TYPE, gpuCount: 1, volumeInGb: $VOLUME_GB, containerDiskInGb: $CONTAINER_GB, minVcpuCount: 8, minMemoryInGb: 32, gpuTypeId: \"$GPU_TYPE_ID\", name: \"$POD_NAME\", imageName: \"$IMAGE\", dockerArgs: \"\", ports: \"22/tcp\", volumeMountPath: \"/workspace\", env: [{ key: \"PUBLIC_KEY\", value: \"$PUBKEY\" }] }) { id imageName machineId } }"}
EOF
)

RESP=$(curl -fsSL -X POST -H "$AUTH" -H "Content-Type: application/json" --data "$PAYLOAD" "$API")
echo "[launch] api response: $RESP"
POD_ID=$(printf '%s' "$RESP" | sed -n 's/.*"id":"\([^"]*\)".*/\1/p' | head -1)
if [ -z "$POD_ID" ]; then
    echo "[launch] failed to parse pod id from response" >&2
    echo "[launch] tip: check RunPod console for available 5090 inventory; try" >&2
    echo "[launch]   RUNPOD_CLOUD_TYPE=COMMUNITY  to widen search," >&2
    echo "[launch]   RUNPOD_GPU_TYPE_ID='NVIDIA GeForce RTX 4090'  to fall back to 4090." >&2
    exit 3
fi
echo "[launch] pod id: $POD_ID (on-demand, no preemption)"

# Poll for runtime + ssh port (RunPod assigns pod IP+port async after schedule).
echo "[launch] waiting for pod runtime…"
for i in $(seq 1 60); do
    Q='{"query":"query Pod($input: PodFilter!) { pod(input: $input) { id desiredStatus runtime { uptimeInSeconds ports { ip privatePort publicPort type isIpPublic } } } }","variables":{"input":{"podId":"'"$POD_ID"'"}}}'
    R=$(curl -fsSL -X POST -H "$AUTH" -H "Content-Type: application/json" --data "$Q" "$API" || true)
    # Pick the SSH mapping: privatePort=22 with public IP. Pod returns multiple
    # port entries (HTTP proxy + SSH) — must NOT take the first one blindly.
    SSH_BLOCK=$(printf '%s' "$R" | python3 -c "
import sys, json
d = json.load(sys.stdin)
ports = (d.get('data', {}).get('pod', {}).get('runtime') or {}).get('ports') or []
for p in ports:
    if p.get('privatePort') == 22 and p.get('isIpPublic'):
        print(p['ip'], p['publicPort'])
        break
" 2>/dev/null || true)
    IP=$(echo "$SSH_BLOCK" | awk '{print $1}')
    PORT=$(echo "$SSH_BLOCK" | awk '{print $2}')
    if [ -n "$IP" ] && [ -n "$PORT" ]; then
        echo "[launch] pod scheduled: $IP:$PORT (SSH)"
        break
    fi
    sleep 5
done

if [ -z "${IP:-}" ] || [ -z "${PORT:-}" ]; then
    echo "[launch] timeout waiting for pod scheduling" >&2
    exit 4
fi

cat > "$STATE" <<EOF
POD_ID=$POD_ID
SSH_HOST=$IP
SSH_PORT=$PORT
SSH_USER=root
LAUNCHED_AT=$(date -u +%FT%TZ)
EOF
echo "[launch] state written → $STATE"
echo
echo "next steps:"
echo "  ssh -p $PORT -i $PUBKEY_FILE root@$IP                              # interactive"
echo "  bash packages/eval/scripts/runpod/resume.sh                        # rsync repo + run setup + start bench"
echo "  bash packages/eval/scripts/runpod/teardown.sh                      # kill pod"
