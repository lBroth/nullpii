# @nullpii/gateway

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

**v0.0.1 — preview.** Non-streaming `POST /v1/messages` works
end-to-end. Streaming (`stream: true`) refuses with HTTP 501 for now;
SSE wiring lands in a follow-up PR. OpenAI compat (`/v1/chat/completions`)
is not in this release.

## Run

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
| `NULLPII_BACKEND` | `cpu` | `cpu` / `cuda` / `coreml` |
| `NULLPII_LOG_LEVEL` | `info` | Fastify log level |
| `NULLPII_BODY_LIMIT_BYTES` | `10485760` | Request body cap (10 MB) |

## Errors

| Status | Source | Shape |
|--------|--------|-------|
| Upstream 2xx | Anthropic | Restored response, `application/json` |
| Upstream non-2xx | Anthropic | **Passthrough.** Status + body forwarded verbatim. |
| 501 | Gateway | `stream: true` not yet implemented |
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
