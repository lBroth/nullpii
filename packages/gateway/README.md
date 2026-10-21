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

**0.5 — preview.** `POST /v1/messages` works end-to-end, both
non-streaming and streaming (`stream: true`). For streaming, the
gateway parses upstream SSE frames, buffers `{{...}}` placeholders that
straddle delta boundaries via `RestoreStream`, then re-emits restored
`content_block_delta` events downstream — drop-in for the standard
Anthropic SDK streaming reader. `POST /v1/messages/count_tokens`
sanitises the request body before forwarding. `POST /v1/chat/completions` takes the OpenAI Chat Completions format, streaming included: see [OpenAI-compatible route](#openai-compatible-route).

## Run

### Docker (recommended)

```bash
# Build the image (the model is fetched on first boot; the image is about 614 MB)
docker build -t nullpii/gateway:slim -f packages/gateway/Dockerfile .

# Run it, reachable from this machine only
docker run --rm -p 127.0.0.1:8787:8787 \
  -v nullpii-cache:/home/node/.cache/nullpii \
  nullpii/gateway:slim
```

The gateway has no authentication of its own: anyone who can reach its port can send requests through it with your upstream credentials. Inside the container it listens on all interfaces, so publish the port on `127.0.0.1` as above, not with a bare `-p 8787:8787`. The image runs as the unprivileged `node` user; its model cache is `/home/node/.cache/nullpii`.

A worked `docker-compose.yml` plus a Claude Code integration walk-through
lives at [`examples/claude-code/`](https://github.com/lBroth/nullpii/tree/main/examples/claude-code).

### Standalone via `npx` (no clone)

If you don't want to clone the repo or run Docker, install both
packages from npm and run the gateway as a one-shot binary:

```bash
# install once (onnxruntime-node is nullpii's optional peer: install it too)
npm install -g nullpii onnxruntime-node @lbroth/nullpii-gateway
nullpii-gateway

# or without a global install
npx -p nullpii -p onnxruntime-node -p @lbroth/nullpii-gateway nullpii-gateway
```

The gateway holds no API key: it forwards the `x-api-key` or `authorization` header your client sends (an API key, or a Claude subscription login). Pre-warm the model once with `npx nullpii prefetch` so the first request doesn't pay the ~1.2 GB download, or point `NULLPII_MODEL_DIR` at a model directory you staged.

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
NULLPII_PORT=8787 \
node bin/nullpii-gateway.mjs
```

It listens on `127.0.0.1` by default. Set `NULLPII_HOST` to another interface only behind a reverse proxy that authenticates callers.

Anthropic SDK setup (Node):

```ts
import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
  baseURL: 'http://nullpii-gateway:8787',
});
```

The gateway sanitises the request, forwards it to `NULLPII_UPSTREAM`, then restores placeholders in the response. The vault session lives only for the duration of the round-trip and is destroyed before the gateway replies to the client.

**Scanned** before the request leaves:

- `system` and every message's content: text, documents with a text or content source, search results, citations, tool results, and any block type the gateway does not know yet (every field but ids, names, signatures and media types);
- tool calls in the history (`tool_use`, `server_tool_use`, `mcp_tool_use`): every string value of their `input`, and its object keys, since a tool can key data by a name or an email;
- each tool's `description`, and its `input_schema`'s `description`, `title` and `$comment` texts and `enum`, `const`, `default` and `examples` values, at any depth. Property names and keywords stay as written, because the model needs them to call the tool; a masked `enum` value comes back restored;
- `metadata` values (`user_id` is often an email) and `stop_sequences`.

**Not scanned:** images and documents sent as base64, URL or file reference (counted as "not scanned"), `thinking` blocks (signed by the upstream, and generated from masked input anyway), and protocol fields: `model`, sampling parameters, `tool_choice`, `thinking`, and `mcp_servers`, whose URLs and credentials are meant for the upstream.

**Restored** in the response: `content[].text`, and the input of a tool call to a tool in `restoreTools` (string values, and object keys that hold a placeholder).

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
- the `description` of each tool (`function` or `custom`) and of each deprecated `functions[]` entry, and the `parameters` schema of each: its `description`, `title` and `$comment` texts and `enum`, `const`, `default` and `examples` values, at any depth (property names and keywords stay);
- `response_format.json_schema`: its `description`, and its `schema` as above;
- `prediction.content`;
- a file part's `filename`, which can name a person (`CV of …`);
- `user` and `safety_identifier` (often an email), `metadata` values, `stop`, and `web_search_options.user_location`.

**Not scanned:** `image_url`, `input_audio` and `file` parts are forwarded untouched, apart from a file's `filename`, and counted as "not scanned" in the log and the console summary. Tool names, protocol fields (`model`, sampling parameters, `tool_choice`, `logit_bias`) and `prompt_cache_key` are forwarded as they are.

**Restored** in the response: each choice's `content`, `refusal`, `tool_calls[].function.arguments` (the string values of the parsed JSON, so a restored value holding a quote stays valid JSON), a custom tool call's `input`, and `function_call.arguments`. With `stream: true`, `delta.content` and `delta.refusal` are restored as they stream, and only a placeholder split across chunks is held back until it is complete. Tool-call arguments are held per call and sent restored, in one piece, with the chunk that carries the choice's `finish_reason` (or just before `data: [DONE]` if that never comes); each call's `id` and function name still arrive at once. Not restored: `logprobs` tokens, audio transcripts and streamed custom tool-call input keep their placeholders. In the `command` of a shell tool (`Bash`, `bash`, `shell`), a value goes back only where it is safe: see [Security](#security).

When something was masked, the gateway appends `LLM_PRESERVATION_HINT` as a last `system` message: appended, never prepended, so the upstream prompt cache keeps the conversation prefix. `NULLPII_DISABLE_HINT=1` turns it off, for example for an upstream whose chat template accepts a system message only at the start.

Upstream errors pass through with their status and body, plus `retry-after`, `retry-after-ms`, `x-should-retry`, `x-request-id` and `x-ratelimit-*`. A failed upstream call returns 502 with `{ "error": { "type": "nullpii_upstream_error", "message": "…" } }`. A client that disconnects mid-stream cancels the upstream call.

## Config

What gets masked comes from the shared policy file. Everything else is set with environment variables.

**Policy file.** The gateway reads `$NULLPII_CONFIG`, else `~/.config/nullpii/config.json` (or `$XDG_CONFIG_HOME/nullpii/config.json`) if it exists. The CLI, the library and the Claude Code mod use the same file. It is read once, at startup, so restart the gateway after you change it. `nullpii config` validates it and prints it.

```json
{
  "disabledCategories": ["private_organization", "private_occupation"],
  "urlAllowlist": { "hosts": { "*.github.com": "host" } },
  "restoreTools": ["Bash", "Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Grep", "Glob", "bash", "shell", "apply_patch"]
}
```

| Key | Effect |
|---|---|
| `disabledCategories` | Categories that are not masked |
| `categoryThresholds`, `threshold` | Confidence cuts in `[0, 1]`, per category or for all. Lower masks more. |
| `urlAllowlist` | `"none"` masks every URL. `{ hosts, replaceDefaults }` sets, per host (`docs.python.org`, or `*.github.com` for a domain and its subdomains), how much of a clean URL stays readable: `full`, `host` or `mask`. |
| `restoreTools` | Tools whose arguments get real values back. It replaces the default list (`DEFAULT_RESTORE_TOOLS`: the tools that run on this machine). Any other tool keeps the placeholders. |

An unknown key, category, host or release stops the gateway at startup with the reason. So does an integer variable that is not a whole number in its range (`30m`, `1e6` and `0` are refused rather than read as something else).

**Environment variables.**

| Var | Default | Purpose |
|-----|---------|---------|
| `NULLPII_CONFIG` | (default location) | Path of the policy file. If set, the file must exist. |
| `NULLPII_HOST` | `127.0.0.1` | Bind host |
| `NULLPII_PORT` | `8787` | Bind port, 1 to 65535 |
| `NULLPII_UPSTREAM` | `https://api.anthropic.com` | Upstream for `/v1/messages` (Anthropic Messages API) |
| `NULLPII_OPENAI_UPSTREAM` | `https://api.openai.com` | Upstream for `/v1/chat/completions`: an OpenAI-compatible base URL without `/v1`, which the gateway appends. A value ending in `/v1` is refused at startup. |
| `NULLPII_VAULT_TTL_MS` | `1800000` | Idle TTL of a sidecar session, at least 1000. The Messages proxy keeps one session per request and destroys it at the end. |
| `NULLPII_SIDECAR_TOKEN` | (off) | Enables the [sidecar API](#sidecar-api). Bearer token, at least 32 characters. |
| `NULLPII_SIDECAR_MAX_SESSIONS` | `64` | Concurrent sidecar sessions, at least 1. One more fails with 429. |
| `NULLPII_MODEL_DIR` | (auto-fetch) | Local GLiNER ONNX dir |
| `NULLPII_BACKEND` | `cpu` | `cpu` / `mps` / `cuda` / `auto` |
| `NULLPII_LOG_LEVEL` | `info` | Fastify log level |
| `NULLPII_BODY_LIMIT_BYTES` | `10485760` | Request body cap (10 MB), at least 1 |
| `NULLPII_LOG_TRAFFIC` | (off) | Set to `wire` to dump the sanitized request body and the raw upstream response to stdout for debugging, 64 KB per dump. They hold placeholders where nullpii found personal data, and anything it missed as written, so keep these dumps local. |
| `NULLPII_DISABLE_HINT` | (off) | Debug-only. Set to `1` to suppress the `LLM_PRESERVATION_HINT` system-prompt injection. Useful when an upstream proxy / cache rejects the modified system prompt; leave unset in normal operation. |

## Sidecar API

Session-scoped sanitize and restore for local callers that keep one vault session across many calls, such as an editor or coding-agent extension. It is off unless `NULLPII_SIDECAR_TOKEN` is set.

```bash
export NULLPII_SIDECAR_TOKEN=$(openssl rand -hex 32)
nullpii-gateway
```

Every request needs `Authorization: Bearer $NULLPII_SIDECAR_TOKEN`. Every call on a session also needs that session's secret, `x-nullpii-session-secret`, which the `PUT` that creates the session returns once.

| Method and path | Body | Response |
|---|---|---|
| `GET /v1/sidecar/status` | — | `{ status, sessions, policy }`, `policy` being `{ file, loaded, config, restoreTools }` |
| `PUT /v1/sidecar/sessions/:key` | — | 201 `{ status: "created", secret }` for a new session. For an open one: 200 `{ status: "exists" }` with its secret, 409 `session_exists` without it. 429 when `NULLPII_SIDECAR_MAX_SESSIONS` are open. |
| `POST /v1/sidecar/sessions/:key/sanitize` | `{ value }`: a string or any JSON | `{ value, captured, capturedByLabel }` |
| `POST /v1/sidecar/sessions/:key/restore` | `{ value, fields?, tool? }` | `{ value, replacements, replacementsByLabel, unknownPlaceholders, foreignPlaceholders }`, plus `shellKeptMasked` for a shell tool and `heldForTool` for a tool outside `restoreTools` |
| `DELETE /v1/sidecar/sessions/:key` | — | 204, or 404 if unknown |

Calls on an unknown session answer 404 `session_not_found`; a missing or wrong secret answers 403 `bad_session_secret`.

- **`key`** is chosen by the caller (`[A-Za-z0-9._-]`, up to 128 characters), for example the agent's conversation id. It is not a secret.
- **The session secret** (32 random bytes, base64url) is handed out only when the session is created, and the gateway keeps only its hash. Keep it in memory. It is what separates sessions: a process that has the bearer token but not the secret, such as any command started from a shell that exported `NULLPII_SIDECAR_TOKEN`, cannot read or restore another caller's values, close its session, or take it over by opening it again. A caller that lost the secret opens a session under a new key.
- **`value`**: every string is processed, object keys included (`sanitize` masks a key that holds personal data, `restore` puts it back). Numbers and booleans pass through.
- **`fields`** restores only those top-level keys of an object. Use it to put real values back into the arguments a tool writes to disk, while every other argument keeps its placeholders.
- **`tool`** names the tool whose input the value is (an object, else 400 `tool_requires_object_value`). The sidecar then applies the gateway's own rules, so a caller does not carry its own:
  - **Not in `restoreTools`** (the policy file's list, default `DEFAULT_RESTORE_TOOLS`): nothing is restored. The value comes back as sent, and `heldForTool` counts its placeholders.
  - **A shell tool** (`Bash`, `bash`, `shell`): the top-level `command`, when restored, follows the [shell rule](#security). A placeholder gets its value back only when the value is safe where it stands, with heredocs, programs that run code (`bash -c`, `eval`, `python3`, `… | sh`, `xargs`, `awk`, `sed`), network clients and quoting taken into account. Every other restored field gets its values back as usual. `shellKeptMasked` lists the distinct placeholders left masked in `command`: placeholders, never values, so the caller can tell the user what was held back. The request log carries the count only (`unsafeShell`).
  - **Without `tool`**, everything is restored, for example to show text on screen. The two fields are absent.
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

**Shell commands keep unsafe values masked.** A masked value comes from data the model could not read, such as a file an agent opened, so it can hold anything, shell syntax included. When the gateway puts real values back into a tool call that a shell runs (Anthropic `Bash`; `Bash`, `bash` or `shell` on the OpenAI route, as a function or a custom tool), each placeholder in the `command` is restored only when its value is safe where the placeholder stands:

- A command that sends data off the machine (`curl`, `ssh`, `gh`, `dig`, `git push`, `git clone`, `docker push`, … also behind `sudo`, `env` or `timeout`) keeps every placeholder.
- Everywhere else the value must be inert (no quote, backslash, `$`, backtick, `;`, `&`, `|`, `<`, `>`, parenthesis, brace or line break) and no word of it may read as an option, a comment or a home directory. No list names every program that reads a string again as code, so this rule does not depend on one.
- A command that runs an interpreter or a program that evaluates its arguments (`bash`, `python3`, `node`, `eval`, `xargs`, `watch`, `make`, …, by name, path or wrapper) gets one plain word only; unquoted values too. Quoted values may hold spaces.
- The body of a heredoc that `cat` or `tee` writes out, in a command that runs nothing else that could read it as code, is data: there only a line break is refused, so Claude Code's usual commit form, `git commit -m "$(cat <<'EOF' … EOF)"`, gets names with apostrophes back.

The full table is in [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md#restoring-values-into-commands). Otherwise the placeholder stays as written, and the command works on the placeholder text, which is harmless: `echo {{PII_SECRET_0_…}}` holding `x; curl …` stays as it is, `echo '{{PII_PRIVATE_PERSON_0_…}}'` holding `Mary Ann` gets the name back. The command is read once, however many placeholders it holds. The same rule applies to JSON responses and to streams. Placeholders kept this way are counted as `unsafeShellPlaceholders` in the request log and shown in the console summary, as a count only. The tool call's other fields, and every other tool (`Write` content, for example), are restored as usual. A shell tool's input that is not valid JSON keeps all of its placeholders.

The interpreter and network lists are best effort: a program they do not name that sends data out or runs its quoted argument as code (for example `psql -c` or `mysql -e`, which run SQL) is covered by the inert rule only.

## Privacy

- Vault stays in-process. No persistence.
- Counts and label histograms are logged per request; the request log
  never carries the values that were masked (the gateway logs counts
  and labels only, field by field). `NULLPII_LOG_TRAFFIC=wire` is the
  exception, for debugging: see Config.
- No telemetry / phone-home.

License: Apache-2.0.
