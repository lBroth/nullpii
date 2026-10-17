# @lbroth/nullpii-gateway

Self-hosted HTTP gateway that sanitizes PII out of LLM prompts before
forwarding to Anthropic Claude, and restores the placeholders in the
response. Drop-in: clients change `baseURL` and nothing else.

```
[client SDK] ──baseURL=http://nullpii-gateway:8787──▶ [nullpii-gateway]
                                                              │
                                            sanitize(prompt) → vault
                                                              │
                                                              ▼
                                                  [api.anthropic.com]
                                                              │
                                                              ▼
                                            restore(response) ← vault
                                                              │
[client SDK] ◀─────────────restored response──────────────────┘
```

## Status

**v0.0.3 — preview.** `POST /v1/messages` works end-to-end, both
non-streaming and streaming (`stream: true`). For streaming, the
gateway parses upstream SSE frames, buffers `{{...}}` placeholders that
straddle delta boundaries via `RestoreStream`, then re-emits restored
`content_block_delta` events downstream — drop-in for the standard
Anthropic SDK streaming reader. `POST /v1/messages/count_tokens`
sanitises the request body before forwarding. OpenAI compat
(`/v1/chat/completions`) is not in this release.

## Run

### Docker (recommended)

```bash
# Build the image (slim variant — model fetched on first boot, ~926 MB image)
docker build -t nullpii/gateway:slim -f packages/gateway/Dockerfile .

# Run it
docker run --rm -p 8787:8787 \
  -v nullpii-cache:/root/.cache/nullpii \
  nullpii/gateway:slim
```

A worked `docker-compose.yml` plus a Claude Code integration walk-through
lives at [`examples/claude-code/`](https://github.com/lBroth/nullpii/tree/main/examples/claude-code).

### Standalone via `npx` (no clone)

If you don't want to clone the repo or run Docker, install both
packages from npm and run the gateway as a one-shot binary:

```bash
# install once
npm install -g nullpii @lbroth/nullpii-gateway

# run
NULLPII_MODEL_DIR=/path/to/gliner-onnx \
ANTHROPIC_API_KEY=sk-ant-…  # OR be logged into Claude Code subscription
  nullpii-gateway

# or without global install
npx -p nullpii -p @lbroth/nullpii-gateway nullpii-gateway
```

Pre-warm the GLiNER model once with `npx nullpii prefetch` so the
first request doesn't pay the ~1.2 GB download.

### From source (dev mode, hot reload)

`tsx watch` on a TS entrypoint; the ONNX engine inside `NullPii` is
lazy — the model only loads on the first `sanitize()` call, so every
respawn boots in ~100 ms and pays the model-load cost once on the
first request after each reload.

```bash
# from the repo root
NULLPII_MODEL_DIR=/abs/path/to/local/gliner-onnx \
NULLPII_LOG_LEVEL=debug \
npm run gateway:dev

# or, from the gateway package
NULLPII_MODEL_DIR=/abs/path/to/local/gliner-onnx \
npm run dev
```

Edits under `packages/gateway/src/**` or the root `src/**` (the
`nullpii` core, aliased via `tsconfig.dev.json`) trigger a respawn.
Pre-cache the GLiNER model once (`npx nullpii prefetch`) so the
post-reload first-request latency stays sub-second.

### From source (production)

```bash
# from the gateway package after `npm install` + `npm run build`
NULLPII_MODEL_DIR=/path/to/local/gliner-onnx \
NULLPII_UPSTREAM=https://api.anthropic.com \
NULLPII_HOST=0.0.0.0 NULLPII_PORT=8787 \
node bin/nullpii-gateway.mjs
```

Anthropic SDK setup (Node):

```ts
import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
  baseURL: 'http://nullpii-gateway:8787',
});
```

The gateway sanitises every `text` content block in `system` and
`messages`, forwards to `NULLPII_UPSTREAM`, then restores placeholders
in the response `content[].text` blocks. The vault session lives only
for the duration of the round-trip and is destroyed before the gateway
replies to the client.

## Config

All via env vars. No file config in this preview.

| Var | Default | Purpose |
|-----|---------|---------|
| `NULLPII_HOST` | `127.0.0.1` | Bind host |
| `NULLPII_PORT` | `8787` | Bind port |
| `NULLPII_UPSTREAM` | `https://api.anthropic.com` | Upstream LLM provider |
| `NULLPII_VAULT_TTL_MS` | `1800000` | Idle TTL of a sidecar session. The Messages proxy keeps one session per request and destroys it at the end. |
| `NULLPII_SIDECAR_TOKEN` | (off) | Enables the [sidecar API](#sidecar-api). Bearer token, at least 32 characters. |
| `NULLPII_SIDECAR_MAX_SESSIONS` | `64` | Concurrent sidecar sessions. One more fails with 429. |
| `NULLPII_MODEL_DIR` | (auto-fetch) | Local GLiNER ONNX dir |
| `NULLPII_BACKEND` | `cpu` | `cpu` / `mps` / `cuda` / `auto` |
| `NULLPII_LOG_LEVEL` | `info` | Fastify log level |
| `NULLPII_BODY_LIMIT_BYTES` | `10485760` | Request body cap (10 MB) |
| `NULLPII_LOG_TRAFFIC` | (off) | Set to `wire` to dump the sanitized request body + raw upstream response (placeholder-bearing only — never real PII) to stdout for debugging. 64 KB cap per dump. |
| `NULLPII_DISABLE_HINT` | (off) | Debug-only. Set to `1` to suppress the `LLM_PRESERVATION_HINT` system-prompt injection. Useful when an upstream proxy / cache rejects the modified system prompt; leave unset in normal operation. |

## Sidecar API

Session-scoped sanitize and restore for local callers that keep one vault session across many calls, such as an editor or coding-agent extension. It is off unless `NULLPII_SIDECAR_TOKEN` is set.

```bash
export NULLPII_SIDECAR_TOKEN=$(openssl rand -hex 32)
nullpii-gateway
```

Every request needs `Authorization: Bearer $NULLPII_SIDECAR_TOKEN`.

| Method and path | Body | Response |
|---|---|---|
| `GET /v1/sidecar/status` | — | `{ status, sessions }` |
| `PUT /v1/sidecar/sessions/:key` | — | 201 created or 200 already open. 429 when `NULLPII_SIDECAR_MAX_SESSIONS` are open. |
| `POST /v1/sidecar/sessions/:key/sanitize` | `{ value }`: a string or any JSON | `{ value, captured, capturedByLabel }` |
| `POST /v1/sidecar/sessions/:key/restore` | `{ value, fields? }` | `{ value, replacements, replacementsByLabel, unknownPlaceholders, foreignPlaceholders }` |
| `DELETE /v1/sidecar/sessions/:key` | — | 204, or 404 if unknown |

- **`key`** is chosen by the caller (`[A-Za-z0-9._-]`, up to 128 characters), for example the agent's conversation id. It is not a secret: the token is the gate.
- **`value`**: every string leaf is processed. Object keys, numbers and booleans pass through.
- **`fields`** restores only those top-level keys of an object. Use it to put real values back into the arguments a tool writes to disk, while every other argument keeps its placeholders.
- **Sessions** expire after `NULLPII_VAULT_TTL_MS` without a call, and their vault entries are dropped with them. A placeholder from an expired session no longer restores and is counted in `unknownPlaceholders`. All sessions are dropped when the server stops.
- **Limits:**
  - requests and responses are capped at 4 MiB (413 `response_too_large` for the latter); placeholders are longer than most of the values they replace, so a response can exceed the cap even when its request did not;
  - a single string over 1,000,000 characters fails with 413 `text_too_long`, so split it.
- **Refused before the token check:** a `Host` other than `127.0.0.1`, `localhost` or `[::1]` (DNS rebinding), and any request with an `Origin` header (a browser).
- **Responses carry counts, never masked values.** Logs carry counts only.
- **First call:** the first `sanitize` loads the model: about 2 seconds when it is already cached.

## Errors

| Status | Source | Shape |
|--------|--------|-------|
| Upstream 2xx | Anthropic | Restored response, `application/json` |
| Upstream non-2xx | Anthropic | **Passthrough.** Status + body forwarded verbatim. |
| 502 | Gateway | Upstream `fetch` failed or returned non-JSON |

Pass-through is deliberate: the Anthropic SDK already knows how to
parse upstream `4xx`/`5xx` shapes; wrapping them in a gateway envelope
would break SDK-level retry + backoff heuristics.

## Privacy

- Vault stays in-process. No persistence.
- Counts + label histograms are logged per request; **PII values
  never appear in logs**, enforced at the type level by `LogFields` in
  the `nullpii` core.
- No telemetry / phone-home.

License: Apache-2.0.
