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
lives at [`examples/claude-code/`](../../examples/claude-code/).

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
| `NULLPII_VAULT_TTL_MS` | `1800000` | Session TTL (currently unused — destroyed per-request) |
| `NULLPII_MODEL_DIR` | (auto-fetch) | Local GLiNER ONNX dir |
| `NULLPII_BACKEND` | `cpu` | `cpu` / `mps` / `cuda` / `auto` |
| `NULLPII_LOG_LEVEL` | `info` | Fastify log level |
| `NULLPII_BODY_LIMIT_BYTES` | `10485760` | Request body cap (10 MB) |
| `NULLPII_LOG_TRAFFIC` | (off) | Set to `wire` to dump the sanitized request body + raw upstream response (placeholder-bearing only — never real PII) to stdout for debugging. 64 KB cap per dump. |
| `NULLPII_DISABLE_HINT` | (off) | Debug-only. Set to `1` to suppress the `LLM_PRESERVATION_HINT` system-prompt injection. Useful when an upstream proxy / cache rejects the modified system prompt; leave unset in normal operation. |

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
