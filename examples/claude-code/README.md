# Claude Code through the nullpii gateway

Point Claude Code (or any Anthropic SDK client) at a local
`nullpii-gateway` container. Prompts are PII-sanitized before they
leave your machine; placeholders are restored in the response. Apache-
2.0, self-hosted, no telemetry.

## Quickstart

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

### Alternative: persist via Claude Code settings

Skip the `export`s by writing the same vars into Claude Code's
settings file. They're picked up on every `claude` invocation.

Project-local (per-repo) — `.claude/settings.local.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "http://localhost:8787",
    "ANTHROPIC_API_KEY": "sk-ant-…"
  }
}
```

User-global — `~/.claude/settings.json` uses the same shape;
project-local wins on conflict. Add `.claude/settings.local.json`
to `.gitignore` if you keep the API key inline.

The gateway sees the raw prompt, runs GLiNER locally, replaces
`John Doe` and `john@acme.io` with placeholders, forwards the
sanitized text to `api.anthropic.com`, and restores the placeholders
in the streamed response before Claude Code prints it. The SSE
restorer (`RestoreStream`, exported from the `nullpii` core) buffers
placeholders that straddle delta boundaries so the client never sees
a half-written `{{PII_…` token mid-stream — see the
[`RestoreStream` section in the root README](../../README.md) for
direct API use.

## What gets sanitized

The model recognizes 12 categories: person, email, phone, address,
date, URL, IP, MAC, passport, driver license, vehicle ID, geolocation,
plus account number (incl. IBAN / credit card / SSN / MRN) and
"secret" (AWS / GitHub / OpenAI / Anthropic / 30+ API keys, JWT,
base64-wrapped PII). Recognizer packs catch structurally-valid
tokens (IBAN mod-97, Luhn, VIN ISO 3779, lat/lon ranges, etc). See
the root [`README.md`](../../README.md) for the full label table.

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

## Air-gapped / pinned-checkpoint variant (mount a host model)

For air-gapped hosts or when you want to pin a specific model revision
on disk, use the local-model compose variant instead of the default
HuggingFace download path:

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
  `VaultStore` (Redis HA) is something I'd write next if the project survives that long — no commitment, hobby project.

## Limitations

- **Anthropic only.** OpenAI compat (`/v1/chat/completions`) is
  not in v0.3. For other backends, use the core `nullpii` library
  directly — see the root README.
- **No auth on the gateway itself.** Put your own mTLS / API-key
  layer in front (typical enterprise pattern). The gateway speaks
  plain HTTP because operators add the TLS termination they trust.
- **Vault TTL is per-request** — each `/v1/messages` round-trip mints
  a fresh session and destroys it at the end. Inter-turn conversation
  context lives entirely in the client.

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Container stuck in `health: starting` for > 2 min | Applies to the **default** `docker-compose.yml` only (`start_period: 120s` covers the cold HF download). Tail logs and check HF reachability. The local-model variant uses `start_period: 30s` because the model is already on disk; if it's stuck there, the volume mount or `NULLPII_MODEL_DIR` path is wrong. |
| `502 nullpii_upstream_error` | Gateway couldn't reach `api.anthropic.com`. Check `NULLPII_UPSTREAM` and outbound DNS. |
| Claude Code prints placeholders instead of names | The LLM moved a placeholder across token boundaries in a way the streaming restorer can't reassemble. File a bug with a redacted repro — these are usually fixable. |
| `unknownPlaceholders > 0` in logs | The LLM made up a placeholder. Usually fine (Claude is told via `LLM_PRESERVATION_HINT` to keep them, but occasionally fabricates). |
