# Claude Code through the nullpii gateway

Point Claude Code (or any Anthropic SDK client) at a local
`nullpii-gateway` container. Prompts are PII-sanitized before they
leave your machine; placeholders are restored in the response. Apache-
2.0, self-hosted, no telemetry.

## Quickstart

> **Pre-v0.2 release caveat.** The HuggingFace repo (`lBroth/nullpii`)
> is still private — the default compose file returns
> `401 NULLPII_MODEL_NOT_FOUND` on the first `/v1/messages` until the
> model is published. To test end-to-end before release, use the
> `docker-compose.local-model.yml` variant which mounts a host model
> dir into the container. See [Pre-release demo](#pre-release-demo-mount-a-host-model)
> below.

```bash
# 1. Boot the gateway (first run: ~1.2 GB GLiNER model download)
docker compose -f examples/claude-code/docker-compose.yml up -d

# 2. Wait for it to be healthy
docker compose -f examples/claude-code/docker-compose.yml ps
# STATUS should show "healthy" (takes ~30-90s after image build / boot)

# 3. Smoke test
curl -fsS http://localhost:8787/health
# {"status":"ok"}

# 4. Point Claude Code at it
export ANTHROPIC_BASE_URL=http://localhost:8787
export ANTHROPIC_API_KEY=sk-ant-…   # your real key, passed through

# 5. Run Claude Code normally
claude "summarise the email I just wrote to John Doe at john@acme.io"
```

The gateway sees the raw prompt, runs GLiNER locally, replaces
`John Doe` and `john@acme.io` with placeholders, forwards the
sanitized text to `api.anthropic.com`, and restores the placeholders
in the streamed response before Claude Code prints it.

## What gets sanitized

The model recognizes 9 categories: person, email, phone, address,
account number (incl. IBAN / credit card), SSN, IP, MAC, "secret"
(AWS keys etc). Recognizer packs catch structurally-valid tokens
(IBAN mod-97, Luhn, IP, base64-wrapped PII). See the root
[`README.md`](../../README.md) for the full label list and the
benchmark numbers.

## Verify the redaction is working

Tail the gateway log while Claude Code is running:

```bash
docker compose -f examples/claude-code/docker-compose.yml logs -f gateway
```

Each `/v1/messages` request emits one structured log line per response
(`anthropic.messages.restored` for non-streaming,
`anthropic.messages.streamed` for SSE). The line carries the
substitution histogram — **counts only, never the PII values**:

```json
{
  "level": 30,
  "msg": "anthropic.messages.streamed",
  "replacements": 3,
  "replacementsByLabel": { "private_person": 1, "private_email": 1, "private_address": 1 },
  "unknownPlaceholders": 0,
  "foreignPlaceholders": 0
}
```

`unknownPlaceholders > 0` means the LLM hallucinated a placeholder
the vault doesn't know about. `foreignPlaceholders > 0` means a
placeholder from a different session leaked into this one. Both are
expected to be `0` on a healthy stream.

## Pre-release demo (mount a host model)

Until the HF repo `lBroth/nullpii` is published, the default compose
file can't fetch the model. Use the local-model variant:

```bash
# 1. Prefetch the model on a host with network access. Drops files
#    into the default cache path.
NULLPII_MODEL_DIR=~/.cache/nullpii/models/lBroth/nullpii/main \
  npx nullpii prefetch

# 2. Point the compose at that directory and boot
export MODEL_DIR_HOST=~/.cache/nullpii/models/lBroth/nullpii/main
docker compose -f examples/claude-code/docker-compose.local-model.yml up -d

# 3. Same setup as the quickstart from here on
export ANTHROPIC_BASE_URL=http://localhost:8787
export ANTHROPIC_API_KEY=sk-ant-…
claude "summarise email to John at john@acme.io"
```

The directory must contain `model.onnx`, `tokenizer.json`,
`gliner_config.json`, `tokenizer_config.json`. It's mounted read-only.

## Going further

- **Use a host-mounted model cache** so the model survives a
  `docker compose down`:
  ```yaml
  volumes:
    - ./nullpii-model-cache:/root/.cache/nullpii
  ```
- **Air-gapped deployment / pre-release.** Pre-fetch the model on a
  connected machine (`npx nullpii prefetch` from the repo root with
  `NULLPII_MODEL_DIR=…` set), then mount it into the container:
  ```yaml
  environment:
    NULLPII_MODEL_DIR: /models/gliner
  volumes:
    - /abs/path/to/local/gliner-onnx:/models/gliner:ro
  ```
- **Higher throughput.** Switch to a GPU host with the CUDA backend:
  `NULLPII_BACKEND=cuda` plus the matching `onnxruntime-node` build.
  See the root [README §Backends](../../README.md).
- **Multi-replica.** The current in-memory vault assumes
  sticky-session load balancing — every conversation's response must
  return to the replica that sanitized the request. A pluggable
  `VaultStore` (Redis HA) is on the v0.2 roadmap (PLAN §3).

## Limitations of this preview

- **Anthropic only.** OpenAI compat (`/v1/chat/completions`) is
  intentionally out of this PR; tracked as PLAN §1 next step.
- **No auth on the gateway itself.** Put your own mTLS / API-key
  layer in front (typical enterprise pattern). The gateway speaks
  plain HTTP because operators add the TLS termination they trust.
- **Vault TTL is per-request** — each `/v1/messages` round-trip mints
  a fresh session and destroys it at the end. Inter-turn conversation
  context lives entirely in the client.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Container stuck in `health: starting` for > 2 min | Model download is slow. Tail logs; check HF reachability. |
| `502 nullpii_upstream_error` | Gateway couldn't reach `api.anthropic.com`. Check `NULLPII_UPSTREAM` and outbound DNS. |
| Claude Code prints placeholders instead of names | The LLM moved a placeholder across token boundaries in a way the streaming restorer can't reassemble. File a bug with a redacted repro — these are usually fixable. |
| `unknownPlaceholders > 0` in logs | The LLM made up a placeholder. Usually fine (Claude is told via `LLM_PRESERVATION_HINT` to keep them, but occasionally fabricates). |
