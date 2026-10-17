# @lbroth/nullpii-gateway

Self-hosted HTTP gateway that sanitizes PII out of LLM prompts before
forwarding to Anthropic Claude or to an OpenAI-compatible API, and
restores the placeholders in the response. Drop-in: clients change
`baseURL` and nothing else.

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
sanitises the request body before forwarding. `POST /v1/chat/completions` takes the OpenAI Chat Completions format, streaming included: see [OpenAI-compatible route](#openai-compatible-route).

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

With `stream: true`, text deltas are restored as they stream, holding back only a placeholder split across deltas. Tool input (`input_json_delta`) is held per content block and sent once, restored, just before its `content_block_stop`: the assembled JSON is parsed and its string values restored, so a value holding a quote or a newline stays valid JSON. A client that disconnects mid-stream cancels the upstream call, so Anthropic stops generating (and billing) the rest of the reply.

## OpenAI-compatible route

`POST /v1/chat/completions` takes the OpenAI Chat Completions format, so the OpenAI SDKs, and any client that lets you set an OpenAI base URL, can go through the gateway. It works like the Messages route: one vault session per request, sanitize, forward to `NULLPII_OPENAI_UPSTREAM`, restore the JSON response or the SSE stream, destroy the session.

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
export OPENAI_API_KEY=sk-…   # reaches the upstream as the Authorization header
```

```ts
import OpenAI from 'openai';

// Reads OPENAI_API_KEY; OPENAI_BASE_URL also works instead of baseURL.
const client = new OpenAI({ baseURL: 'http://127.0.0.1:8787/v1' });
```

The gateway appends `/v1/chat/completions` to `NULLPII_OPENAI_UPSTREAM`, so set it without `/v1`: `https://api.openai.com` (the default), `http://localhost:11434` for Ollama, `https://openrouter.ai/api` for OpenRouter. The client headers forwarded upstream are `Authorization`, `OpenAI-Organization`, `OpenAI-Project`, `OpenAI-Beta`, `User-Agent` and `x-stainless-*`.

**Scanned** before the request leaves:

- message `content`, as a string or as `text` and `refusal` parts, for every role, `tool` results included;
- a message's participant `name` (not the function name of a deprecated `function` message) and an assistant `refusal`;
- `tool_calls[].function.arguments`: parsed as JSON, every string value sanitized, then re-serialized (arguments that are not valid JSON are sanitized as plain text, and arguments with nothing to mask are forwarded byte for byte); a custom tool call's `input`; the deprecated `function_call.arguments`;
- the `description` of each tool (`function` or `custom`) and of each deprecated `functions[]` entry;
- `prediction.content`;
- a file part's `filename`, which can name a person (`CV of …`).

**Not scanned:** `image_url`, `input_audio` and `file` parts are forwarded untouched, apart from a file's `filename`, and counted as "not scanned" in the log and the console summary. Tool names, parameter JSON schemas, `response_format`, and the identifiers a client chooses to send (`user`, `safety_identifier`, `metadata`, `prompt_cache_key`) are forwarded as they are.

**Restored** in the response: each choice's `content`, `refusal`, `tool_calls[].function.arguments` (the string values of the parsed JSON, so a restored value holding a quote stays valid JSON), a custom tool call's `input`, and `function_call.arguments`. With `stream: true`, `delta.content` and `delta.refusal` are restored as they stream, and only a placeholder split across chunks is held back until it is complete. Tool-call arguments are held per call and sent restored, in one piece, with the chunk that carries the choice's `finish_reason` (or just before `data: [DONE]` if that never comes); each call's `id` and function name still arrive at once. Not restored: `logprobs` tokens, audio transcripts and streamed custom tool-call input keep their placeholders. In the `command` of a shell tool (`Bash`, `bash`, `shell`), a value goes back only where it is safe: see [Security](#security).

When something was masked, the gateway appends `LLM_PRESERVATION_HINT` as a last `system` message: appended, never prepended, so the upstream prompt cache keeps the conversation prefix. `NULLPII_DISABLE_HINT=1` turns it off, for example for an upstream whose chat template accepts a system message only at the start.

Upstream errors pass through with their status and body, plus `retry-after`, `retry-after-ms`, `x-should-retry`, `x-request-id` and `x-ratelimit-*`. A failed upstream call returns 502 with `{ "error": { "type": "nullpii_upstream_error", "message": "…" } }`. A client that disconnects mid-stream cancels the upstream call.

## Config

All via env vars. No file config in this preview.

| Var | Default | Purpose |
|-----|---------|---------|
| `NULLPII_HOST` | `127.0.0.1` | Bind host |
| `NULLPII_PORT` | `8787` | Bind port |
| `NULLPII_UPSTREAM` | `https://api.anthropic.com` | Upstream for `/v1/messages` (Anthropic Messages API) |
| `NULLPII_OPENAI_UPSTREAM` | `https://api.openai.com` | Upstream for `/v1/chat/completions`: an OpenAI-compatible base URL without `/v1`, which the gateway appends. A value ending in `/v1` is refused at startup. |
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
| `POST /v1/sidecar/sessions/:key/restore` | `{ value, fields?, shell? }` | `{ value, replacements, replacementsByLabel, unknownPlaceholders, foreignPlaceholders }`, plus `shellKeptMasked` with `shell` |
| `DELETE /v1/sidecar/sessions/:key` | — | 204, or 404 if unknown |

- **`key`** is chosen by the caller (`[A-Za-z0-9._-]`, up to 128 characters), for example the agent's conversation id. It is not a secret: the token is the gate.
- **`value`**: every string leaf is processed. Object keys, numbers and booleans pass through.
- **`fields`** restores only those top-level keys of an object. Use it to put real values back into the arguments a tool writes to disk, while every other argument keeps its placeholders.
- **`shell: true`** marks the value as a shell tool's input (an object, else 400 `shell_requires_object_value`). Its top-level `command`, when restored, follows the gateway's [shell rule](#security): a placeholder gets its value back only when the value is safe where it stands, with heredocs, nested interpreters (`bash -c`, `eval`, `ssh`, `python -c`, `… | sh`, `awk`, `sed`) and quoting taken into account. Every other restored field gets its values back as usual. `shellKeptMasked` lists the distinct placeholders left masked in `command`: placeholders, never values, so the caller can tell the user what was held back. Without `shell` the restore is unchanged and the field is absent. The request log carries the count only (`unsafeShell`).
- **Sessions** expire after `NULLPII_VAULT_TTL_MS` without a call, and their vault entries are dropped with them. A placeholder from an expired session no longer restores and is counted in `unknownPlaceholders`. All sessions are dropped when the server stops.
- **Limits:**
  - requests and responses are capped at 4 MiB (413 `response_too_large` for the latter); placeholders are longer than most of the values they replace, so a response can exceed the cap even when its request did not;
  - a single string over 1,000,000 characters fails with 413 `text_too_long`, so split it.
- **Refused before the token check:** a `Host` other than `127.0.0.1`, `localhost` or `[::1]` (DNS rebinding), and any request with an `Origin` header (a browser).
- **Responses carry counts, never masked values.** Logs carry counts only.
- **Repeated values are served from a cache.** A `sanitize` request whose value the session has already masked gets the same response without running the model (header `x-nullpii-cache: hit`). Coding agents re-read the same files often. The cache keeps only masked output, at most 512 responses or 8 MiB per session, and is dropped with its session. The answer is identical to a fresh run because the vault mints one placeholder per value.
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

## Security

**Shell commands keep unsafe values masked.** A masked value comes from data the model could not read, such as a file an agent opened, so it can hold anything, shell syntax included. When the gateway puts real values back into a tool call that a shell runs (Anthropic `Bash`; `Bash`, `bash` or `shell` on the OpenAI route, as a function or a custom tool), each placeholder in the `command` is restored only when its value is safe where the placeholder stands. The first row that applies decides:

| Where the placeholder stands | Restored only when the value |
|---|---|
| anywhere in a command that hands code to another interpreter: `bash -c` (also `-lc`), `sh`/`zsh`/`dash`/`ksh`/`fish -c`, `eval`, `ssh`, `su -c`, `python`/`node`/`perl`/`ruby`/`php`/`deno`/`bun` with `-c` or `-e`, a pipe into one of them (`… \| sh`), `awk`, `sed` | matches `^[A-Za-z0-9@%+=:,./_-]+$` |
| in the body of a heredoc read by `cat` or `tee`, with a quoted delimiter (`<<'EOF'`, `<<"EOF"`, `<<\EOF`, also `<<-`) | has no newline |
| in the body of a heredoc read by `cat` or `tee`, with a bare delimiter (`<<EOF`) | the double-quote rule; inside a `$(…)` in the body, the unquoted rule |
| in the body of any other heredoc (`python3 - <<'EOF'`), of one piped on, or of one without its closing line | matches `^[A-Za-z0-9@%+=:,./_-]+$` |
| unquoted, or inside `$(…)` or backticks, even within double quotes | matches `^[A-Za-z0-9@%+=:,./_-]+$` |
| inside single quotes | has no `'` and no newline |
| inside double quotes | has none of `"`, `$`, `` ` ``, `\`, `!`, and no newline |

Otherwise the placeholder stays as written, and the command works on the placeholder text, which is harmless: in `echo {{PII_SECRET_0_…}}` it stays, in `echo '{{PII_SECRET_0_…}}'` the real value goes back. Names still come back in Claude Code's usual commit form, `git commit -m "$(cat <<'EOF' … EOF)"`. Heredoc bodies are skipped when the quoting is read, so an apostrophe in a body does not open a quote for the rest of the command, and `<<` counts only in shell code, not inside quotes or as the here-string `<<<`. The same rule applies to JSON responses and to streams. Placeholders kept this way are counted as `unsafeShellPlaceholders` in the request log and shown in the console summary, as a count only. The tool call's other fields, and every other tool (`Write` content, for example), are restored as usual. A shell tool's input that is not valid JSON keeps all of its placeholders.

The interpreter list is best effort: a program it does not name that runs its quoted argument as code (for example `psql -c` or `mysql -e`, which run SQL) is covered by the quoting rules only.

## Privacy

- Vault stays in-process. No persistence.
- Counts + label histograms are logged per request; **PII values
  never appear in logs**, enforced at the type level by `LogFields` in
  the `nullpii` core.
- No telemetry / phone-home.

License: Apache-2.0.
