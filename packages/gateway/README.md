# @lbroth/nullpii-gateway

A self-hosted HTTP gateway. It masks personal data in LLM requests before it forwards them to Anthropic or to an OpenAI-compatible API, and it puts the real values back in the response. Clients change their `baseURL` and nothing else.

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

**0.5, preview.** `POST /v1/messages` works end to end, with and without streaming (`stream: true`). When streaming, the gateway reads the upstream SSE frames, holds back a `{{...}}` placeholder that is split across two deltas (`RestoreStream`), and sends the restored `content_block_delta` events on. The standard Anthropic SDK reads them as usual. `POST /v1/messages/count_tokens` masks the request body before it forwards it. `POST /v1/chat/completions` takes the OpenAI Chat Completions format, streaming included: see [OpenAI-compatible route](#openai-compatible-route).

## Run

### Docker (recommended)

Each release publishes the image to the GitHub Container Registry as `ghcr.io/lbroth/nullpii-gateway`, for linux/amd64 and linux/arm64. It runs the CPU backend.

| Tag | Image |
|---|---|
| `0.5.0` | that release |
| `0.5` | the newest `0.5.x` release |
| `latest` | the newest release |
| `edge` | the last build of `main`, unreleased |
| `sha-<commit>` | the build of that commit |

Pin a minor line (`0.5`) or an exact version: before 1.0, a minor release can break compatibility. To run exactly the image you reviewed, pin its digest (`ghcr.io/lbroth/nullpii-gateway@sha256:…`).

```bash
# Run it, reachable from this machine only
docker run --rm -p 127.0.0.1:8787:8787 \
  -v nullpii-cache:/home/node/.cache/nullpii \
  ghcr.io/lbroth/nullpii-gateway:0.5
```

To build the image yourself, from a clone of the repository (the build context is the repository root):

```bash
docker build -t nullpii-gateway:local -f packages/gateway/Dockerfile .
docker run --rm -p 127.0.0.1:8787:8787 \
  -v nullpii-cache:/home/node/.cache/nullpii \
  nullpii-gateway:local
```

The gateway has no authentication of its own. Anyone who can reach its port can send requests through it with your upstream credentials. Inside the container it listens on all interfaces, so publish the port on `127.0.0.1` as above, not with a bare `-p 8787:8787`. The image runs as the unprivileged `node` user. Its model cache is `/home/node/.cache/nullpii`.

The model is not in the image. The first request that needs it downloads it (about 1.2 GB) into the cache volume and waits. To download it first, run the nullpii CLI that the image carries, on the same volume:

```bash
docker run --rm -v nullpii-cache:/home/node/.cache/nullpii \
  ghcr.io/lbroth/nullpii-gateway:0.5 node bin/nullpii.mjs prefetch --backend cpu
```

The image's health check calls `/health`. It answers as soon as the server listens; it does not wait for the model.

A worked `docker-compose.yml` and a Claude Code walk-through are in [`examples/claude-code/`](https://github.com/lBroth/nullpii/tree/main/examples/claude-code).

### Standalone via `npx` (no clone)

Without a clone or Docker, install the gateway from npm with its two peer dependencies, `nullpii` (the detection library) and `onnxruntime-node` (the runtime for the model), and run the binary:

```bash
# install once; listing the peers also puts the `nullpii` CLI on your PATH
npm install -g nullpii onnxruntime-node @lbroth/nullpii-gateway
nullpii-gateway

# or without a global install
npx -p nullpii -p onnxruntime-node -p @lbroth/nullpii-gateway nullpii-gateway
```

On Linux x64 without an NVIDIA GPU, run the install with `ONNXRUNTIME_NODE_INSTALL=skip` in its environment. Otherwise the install script of `onnxruntime-node` downloads its CUDA libraries from NuGet (the `cuda12` package, which links the CUDA 13 runtime). The CPU backend does not use them: its runtime ships in the npm package.

Settings come from environment variables and the policy file, never from the command line. `nullpii-gateway` with no argument starts the server. `--version` (`-v`) and `--help` (`-h`) answer without starting it. Anything else on the command line, or more than one option, exits with status 2 and starts nothing. These exit with status 1 and one line on standard error: a port already taken, an address that cannot be bound, a bad variable or policy file, or a missing build or peer.

The gateway holds no API key. It forwards the `x-api-key` or `authorization` header your client sends (an API key, or a Claude subscription login). Download the model once with `npx nullpii prefetch`, so the first request does not wait for about 1.2 GB, or point `NULLPII_MODEL_DIR` at a model directory you put there yourself.

### From source (dev mode, hot reload)

`tsx watch` runs a TypeScript entry point. The model loads only on the first `sanitize()` call, so each restart takes about 100 ms, and the first request after each restart pays the model load.

```bash
# from the repo root
NULLPII_MODEL_DIR=/abs/path/to/local/gliner-onnx \
NULLPII_LOG_LEVEL=debug \
npm run gateway:dev

# or, from the gateway package
NULLPII_MODEL_DIR=/abs/path/to/local/gliner-onnx \
npm run dev
```

An edit under `packages/gateway/src/**` or the root `src/**` (the `nullpii` core, through `tsconfig.dev.json`) restarts it. Download the model once (`npx nullpii prefetch`) so a restart does not download it again. The first request after a restart still loads the model, which took 1.7 to 2.2 seconds in our measurements.

### From source (production)

```bash
# from the gateway package after `npm install` + `npm run build`
NULLPII_MODEL_DIR=/path/to/local/gliner-onnx \
NULLPII_UPSTREAM=https://api.anthropic.com \
NULLPII_PORT=8787 \
node bin/nullpii-gateway.mjs
```

It listens on `127.0.0.1` by default. Set `NULLPII_HOST` to another interface only behind a reverse proxy that checks who is calling.

Anthropic SDK setup (Node):

```ts
import Anthropic from '@anthropic-ai/sdk';

const client = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
  baseURL: 'http://nullpii-gateway:8787',
});
```

The gateway masks the request, forwards it to `NULLPII_UPSTREAM`, and restores the placeholders in the response. The vault session lasts only for that round trip. The gateway destroys it before it answers the client.

**Scanned** before the request leaves:

- `system` and every message's content: text, documents with a text or content source, search results, citations, tool results, and any block type the gateway does not know yet (every field but `type`, ids, names, signatures, media types, `cache_control`, and the encrypted payloads of server-tool results, which the upstream verifies);
- tool calls in the history (`tool_use`, `server_tool_use`, `mcp_tool_use`): every string value of their `input`, and its object keys, since a tool can key data by a name or an email;
- every tool definition (client tools, server tools such as web search, MCP toolsets): its `input_schema`'s `description`, `title` and `$comment` texts and `enum`, `const`, `default` and `examples` values, at any depth, and every string value of its other fields except `name`, `type`, `cache_control`, `allowed_domains`, `blocked_domains`, `allowed_callers`, `model` and `mcp_server_name`. That covers the `description`, `input_examples`, web search's `user_location` and any field the gateway does not know yet. Property names and keywords stay as written, because the model needs them to call the tool, and so do the keys of `input_examples`, which are those property names. A masked `user_location.country` or `timezone` is no longer a valid code, and the upstream may refuse the request;
- the structured-output spec, `output_config.format` (and the deprecated `output_format`): its `description` and its `schema`, as for `input_schema`;
- `metadata` values (`user_id` is often an email) and `stop_sequences`.

If an `enum` or `const` value is masked, the model answers with the placeholder. It is restored in the reply text and in the input of a tool in `restoreTools`. The input of any other tool keeps it masked (see Restored, below).

**Not scanned:** the payload of images and documents sent as base64, URL or file reference (counted as "not scanned"; a document's other fields, such as its `title`, are scanned), `thinking` blocks (signed by the upstream, and generated from masked input anyway), the tool-definition fields named above (what the API and the model match a tool by, and the web tools' domain filters, which the upstream applies as written), the URL query string (`?beta=true`), and every other top-level field, forwarded as the client sent it: protocol (`model`, sampling parameters, `tool_choice`, `thinking`, `output_config` apart from its `format`, `context_management`, `container`, and fields the gateway does not know) and `mcp_servers`, whose URLs and credentials are meant for the upstream.

**Restored** in the response: `content[].text`, and the input of a client tool call (`tool_use`) to a tool in `restoreTools` (string values, and object keys that hold a placeholder). Every other tool call keeps its placeholders: a tool outside `restoreTools`, and server and MCP tool calls (`server_tool_use`, `mcp_tool_use`), which the upstream runs, whatever their name. The request log counts them in `heldForToolPlaceholders`.

With `stream: true`, text deltas are restored as they stream. Only text after an unclosed `{{` (or a trailing `{`), up to 256 characters, is held back until it is complete. Tool input (`input_json_delta`) is held per content block and sent once, restored by the same rule as a JSON reply; the tool is read from the block's `content_block_start`. The string values of the parsed JSON are restored, so a value with a quote or a newline stays valid JSON. [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md#restoring-values-into-commands) ("Streamed tool calls") says when the gateway sends it, and when a stream keeps tool input masked. A client that disconnects mid-stream cancels the upstream call, so Anthropic stops generating (and billing) the rest of the reply.

## OpenAI-compatible route

`POST /v1/chat/completions` takes the OpenAI Chat Completions format. The OpenAI SDKs, and any client that speaks Chat Completions and lets you set an OpenAI base URL, can go through the gateway. The Responses API is not served, so a client that speaks only that, such as the Codex CLI (which refuses `wire_api = "chat"`), cannot use the gateway. The route works like the Messages route: one vault session per request; mask; forward to `NULLPII_OPENAI_UPSTREAM`; restore the JSON response or the SSE stream; destroy the session.

```bash
export OPENAI_BASE_URL=http://127.0.0.1:8787/v1
export OPENAI_API_KEY=sk-…   # reaches the upstream as the Authorization header
```

```ts
import OpenAI from 'openai';

// Reads OPENAI_API_KEY; OPENAI_BASE_URL also works instead of baseURL.
const client = new OpenAI({ baseURL: 'http://127.0.0.1:8787/v1' });
```

The gateway adds `/v1/chat/completions` to `NULLPII_OPENAI_UPSTREAM`, so set it without `/v1`: `https://api.openai.com` (the default), `http://127.0.0.1:11434` for Ollama, `https://openrouter.ai/api` for OpenRouter. It forwards these client headers: `Authorization`, `OpenAI-Organization`, `OpenAI-Project`, `OpenAI-Beta`, `User-Agent` and `x-stainless-*`.

**Scanned** before the request leaves:

- message `content`, as a string or as `text` and `refusal` parts, for every role, `tool` results included;
- a message's participant `name` (not the function name of a deprecated `function` message) and an assistant `refusal`;
- `tool_calls[].function.arguments`: parsed as JSON, every string value sanitized, then re-serialized (arguments that are not valid JSON are sanitized as plain text, and arguments with nothing to mask are forwarded byte for byte); a custom tool call's `input`; the deprecated `function_call.arguments`;
- the `description` of each tool (`function` or `custom`) and of each deprecated `functions[]` entry, and the `parameters` schema of each: its `description`, `title` and `$comment` texts and `enum`, `const`, `default` and `examples` values, at any depth (property names and keywords stay);
- `response_format.json_schema`: its `description`, and its `schema` as above;
- `prediction.content`;
- a file part's `filename`, which can name a person (`CV of …`);
- `user` and `safety_identifier` (often an email), `metadata` values, `stop`, and `web_search_options.user_location`.

**Not scanned:** `image_url`, `input_audio` and `file` parts are forwarded untouched, apart from a file's `filename`, and counted as "not scanned" in the log and the console summary. Tool names, a custom tool's `format` (a grammar, which must stay valid syntax), the URL query string, protocol fields (`model`, sampling parameters, `tool_choice`, `logit_bias`), `prompt_cache_key` and every other top-level field are forwarded as they are.

**Restored** in the response: each choice's `content` and `refusal`, and, for a tool in `restoreTools`, `tool_calls[].function.arguments` (the string values of the parsed JSON, so a restored value holding a quote stays valid JSON; SECURITY.md covers arguments that do not parse), a custom tool call's `input`, and `function_call.arguments`; a call to any other tool keeps its placeholders. With `stream: true`, `delta.content` and `delta.refusal` are restored as they stream, and only text from an unclosed `{{` (or a trailing `{`), up to 256 characters, is held back until it is complete. Tool-call arguments and custom tool-call input are held per call and sent in one piece, restored by the same rule, near the end of the stream, together with the choice's `finish_reason`; each call's `id` and tool name still arrive at once. When the gateway sends them, and the cases in which a stream keeps tool input masked (a stream with more than one choice, for example), are in [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md#restoring-values-into-commands) ("Streamed tool calls"). A client that reads a call's arguments as soon as the next call starts sees them empty until then: openai-node's `chat.completions.stream()` with `strict` tools and parallel tool calls fails on that, so use `stream: false` or tools without `strict` there. Not restored: `logprobs` tokens and audio transcripts keep their placeholders. A shell tool's call (`Bash`, `bash`, `shell`, `PowerShell`, `exec_command`, `shell_command`, `write_stdin`) keeps every placeholder: see [Security](#security).

When something was masked, the gateway adds `LLM_PRESERVATION_HINT` as the last `system` message. It adds it at the end, never at the start, so it does not shift the conversation. Placeholders carry a random prefix per request, so an upstream prompt cache cannot reuse a prefix past the first masked value. `NULLPII_DISABLE_HINT=1` turns the hint off, for example for an upstream whose chat template accepts a system message only at the start.

Upstream errors pass through with their status and body, plus `retry-after`, `retry-after-ms`, `x-should-retry`, `x-request-id` and `x-ratelimit-*`. If the upstream call fails, the gateway returns 502 with `{ "error": { "type": "nullpii_upstream_error", "message": "…" } }`. A client that disconnects mid-stream cancels the upstream call.

## Config

What gets masked comes from the shared policy file. Everything else is set with environment variables.

**Policy file.** The gateway reads `$NULLPII_CONFIG`, or else `~/.config/nullpii/config.json` (or `$XDG_CONFIG_HOME/nullpii/config.json`) if it exists. The CLI, the library and the Claude Code mod use the same file. The gateway reads it at startup. An edit by hand applies after a restart. A change sent through the sidecar (`PUT /v1/sidecar/policy`, which the mod's `/pii` uses) applies at once. `nullpii config` checks the file and prints it.

```json
{
  "disabledCategories": ["private_organization", "private_occupation"],
  "urlAllowlist": { "hosts": { "*.github.com": "host" } },
  "restoreTools": ["Read", "Edit", "MultiEdit", "Write", "NotebookEdit", "Grep", "Glob", "apply_patch"]
}
```

| Key | Effect |
|---|---|
| `disabledCategories` | Categories that are not masked. Default: dates, companies, jobs, honorifics, demographic and sensitive attributes (`DEFAULT_DISABLED_CATEGORIES`); `[]` masks every category. |
| `categories` | The mode of each category named: `mask`, `ask` (masked; the Claude Code mod asks about a value in your own prompt, see its README) or `off` (readable). It overrides `disabledCategories` for the categories it names. |
| `categoryThresholds`, `threshold` | Confidence cuts in `[0, 1]`, per category or for all. Lower masks more. |
| `urlAllowlist` | `"none"` masks every URL. `{ hosts, replaceDefaults }` sets, per host (`docs.python.org`, or `*.github.com` for a domain and its subdomains), how much of a clean URL stays readable: `full`, `host` or `mask`. |
| `restoreTools` | Tools whose arguments get real values back. It replaces the default list (`DEFAULT_RESTORE_TOOLS`: the file tools that run on this machine). Any other tool keeps the placeholders. |

An unknown key, category, host or release stops the gateway at startup, with the reason. So does an environment variable outside its documented values: an integer that is not a whole number in its range (`30m`, `1e6` and `0` are refused, not read as something else), a `NULLPII_DISABLE_HINT` other than `0` or `1`, or an upstream that is not a base URL as described below. The error names the variable. It never repeats the sidecar token. It repeats an upstream URL only once it is known to carry no credentials or query string.

**Environment variables.**

| Var | Default | Purpose |
|-----|---------|---------|
| `NULLPII_CONFIG` | (default location) | Path of the policy file. If set, the file must exist. |
| `NULLPII_HOST` | `127.0.0.1` | Bind host |
| `NULLPII_PORT` | `8787` | Bind port, 1 to 65535 |
| `NULLPII_UPSTREAM` | `https://api.anthropic.com` | Upstream for `/v1/messages` (Anthropic Messages API): a base URL without `/v1`, which the gateway appends. `https:`, or `http:` on the literal `127.0.0.1` or `[::1]` only. |
| `NULLPII_OPENAI_UPSTREAM` | `https://api.openai.com` | Upstream for `/v1/chat/completions`: an OpenAI-compatible base URL without `/v1`, which the gateway appends. `https:`, or `http:` on the literal `127.0.0.1` or `[::1]` only. |
| `NULLPII_VAULT_TTL_MS` | `1800000` | Idle TTL of a sidecar session, at least 1000. The Messages proxy keeps one session per request and destroys it at the end. |
| `NULLPII_SIDECAR_TOKEN` | (off) | Enables the [sidecar API](#sidecar-api). Bearer token, at least 32 characters. |
| `NULLPII_SIDECAR_MAX_SESSIONS` | `64` | Concurrent sidecar sessions, at least 1. One more fails with 429. |
| `NULLPII_SIDECAR_SHUTDOWN` | `off` | `on` adds `POST /v1/sidecar/shutdown`, which stops a gateway that no caller may still count on (see the route). Set by the Claude Code mod on the sidecar it starts, so a newer mod can replace it; leave it off for a gateway you run yourself or in Docker. |
| `NULLPII_MODEL_DIR` | (auto-fetch) | Local GLiNER ONNX dir |
| `NULLPII_BACKEND` | `cpu` | `cpu` / `mps` / `cuda` / `auto` |
| `NULLPII_LOG_LEVEL` | `info` | Fastify log level |
| `NULLPII_BODY_LIMIT_BYTES` | `10485760` | Request body cap (10 MB), at least 1 |
| `NULLPII_LOG_TRAFFIC` | (off) | Set to `wire` to dump to stdout, for debugging, the request body as forwarded, its headers (auth headers as their last 6 characters and length) and the raw upstream response before restore, 64 KB per dump. They hold placeholders where nullpii found personal data, and everything else as it was sent or written: values it missed, fields it does not scan (images, documents, `mcp_servers` and their credentials) and the model's output. Keep these dumps local. |
| `NULLPII_DISABLE_HINT` | `0` | `1` suppresses the `LLM_PRESERVATION_HINT` system-prompt injection; `0` keeps it. Useful when an upstream proxy / cache rejects the modified system prompt; leave unset in normal operation. |

Both upstreams must be `http:` or `https:` base URLs, without credentials (`user:password@`; the gateway forwards the client's own auth headers), a query string, a fragment or a trailing `/v1`. Anything else is refused at startup. Trailing slashes are dropped.

## Sidecar API

Sanitize and restore in a session, for local callers that keep one vault session across many calls, such as an editor or a coding-agent extension. It is off unless `NULLPII_SIDECAR_TOKEN` is set.

```bash
export NULLPII_SIDECAR_TOKEN=$(openssl rand -hex 32)
nullpii-gateway
```

Before it sends the token, a caller can check that the process on the port is this sidecar. `POST /v1/sidecar/challenge` with `{ nonce }` (32 random bytes, lower-case hex) answers `{ proof }`: the HMAC-SHA256 of `nullpii-sidecar-challenge-v1\n` followed by the nonce, keyed by the token. The call needs no token. So a process that took the port while the gateway was down learns nothing from it, and cannot answer it. The Claude Code mod checks before every request.

Every other request needs `Authorization: Bearer $NULLPII_SIDECAR_TOKEN`. Every call on a session also needs that session's secret, `x-nullpii-session-secret`, which the `PUT` that creates the session returns once.

| Method and path | Body | Response |
|---|---|---|
| `POST /v1/sidecar/challenge` | `{ nonce }` | `{ proof }`; no token needed |
| `GET /v1/sidecar/status` | — | `{ status, sessions, gatewayVersion, nullpiiVersion, backend, model, features, policy }`, `features` being `{ shutdown }`: whether this gateway has the shutdown route, which a caller reads before using it, as an older one has no `features` at all. `policy` being `{ version, file, loaded, config, categories, disabledCategories, restoreTools }`: a version that changes with the policy (the same for the same policy, across restarts), the file's contents, the mode of every category (`mask`, `ask`, `off`), the categories left readable and the tools that get values, as in effect |
| `PUT /v1/sidecar/policy` | `{ config }` | `{ status, policy }`: `config` (a policy file's contents, at most 64 KiB) is validated, written to the policy file (mode 0600) and applied at once, to the engine and the restore tools of every route; cached sanitize responses are dropped. 400 `invalid_policy` changes nothing. |
| `PUT /v1/sidecar/sessions/:key` | — | 201 `{ status: "created", secret }` for a new session. For an open one: 200 `{ status: "exists" }` with its secret, 409 `session_exists` without it. 429 when `NULLPII_SIDECAR_MAX_SESSIONS` are open. Optional `x-nullpii-supersedes: <base>`, the key itself or the part before a `.<suffix>` of it (anything else is 400 `invalid_supersedes`): once this PUT creates the session, the caller has left the other keys under that base (see the session key below). 503 `{ error: "sidecar_closing" }` once the shutdown route has answered 202, until the process ends: a session opened then would die with it. |
| `POST /v1/sidecar/sessions/:key/sanitize` | `{ value }`: a string or any JSON | `{ value, captured, capturedByLabel, modelUnscannedWords }` |
| `POST /v1/sidecar/sessions/:key/restore` | `{ value, fields?, tool? }` | `{ value, replacements, replacementsByLabel, unknownPlaceholders, foreignPlaceholders }`, plus `shellKeptMasked` for a shell tool and `heldForTool` for a tool outside `restoreTools` |
| `DELETE /v1/sidecar/sessions/:key` | — | 204, or 404 if unknown |
| `POST /v1/sidecar/shutdown` | — | Only with `NULLPII_SIDECAR_SHUTDOWN=on` (404 otherwise). 202 `{ status: "closing" }` and the process exits like on SIGTERM; a second call answers 202 again and stops nothing a second time. It answers 409 and nothing happens while a caller may still count on the process: `{ error: "sessions_active", sessions }` while any session is open; `{ error: "starting" }` while the model is still downloading or loading; `{ error: "not_used_yet" }` before any session has opened, unless the start-up failed; `{ error: "sessions_unclosed" }` once a session ended by its idle TTL and its caller has neither opened nor closed it again since (a window left idle looks just like that). |

A call on an unknown session answers 404 `session_not_found`. A missing or wrong secret answers 403 `bad_session_secret`. The bearer token alone can replace the policy, so a caller that holds real values should send the policy version it last saw in `x-nullpii-policy-version`. A `sanitize`, `restore` or `PUT /v1/sidecar/policy` whose version is not the current one answers 412 `{ error: "policy_changed", version }` and does nothing. So does a `sanitize` that sent the header if the policy was replaced while it ran, even if it was then put back; its answer is not cached either. This way the caller learns of a change it did not make before it masks, restores or overwrites under it.

- **`key`** is chosen by the caller (`[A-Za-z0-9._-]`, up to 128 characters), for example the agent's conversation id. It is not a secret.
- **The session secret** (32 random bytes, base64url) is given out only when the session is created, and the gateway keeps only its hash. Keep it in memory. It is what separates sessions. A process with the bearer token but not the secret, such as any command started from a shell that exported `NULLPII_SIDECAR_TOKEN`, cannot read or restore another caller's values, close its session, or take it over by opening it again. It can replace the policy, which is why the policy version above exists. A caller that lost the secret opens a session under a new key, `<base>.<suffix>`, and names the base in `x-nullpii-supersedes`: the other keys under that base then count as left by it. A live one stays open, its values untouched and its secret still needed, until its idle TTL ends it; that end is then not remembered as a caller that may come back (`sessions_unclosed` on the shutdown route), unless its owner made a call on it in the meantime, which undoes the supersede. A remembered expired key under that base is forgotten at once.
- **`value`**: every string is processed, object keys included (`sanitize` masks a key that holds personal data; `restore` puts it back). Numbers and booleans pass through.
- **`fields`** restores only those top-level keys of an object. Use it to put real values back into the arguments a tool writes to disk, while every other argument keeps its placeholders.
- **`tool`** names the tool whose input the value is (an object, else 400 `tool_requires_object_value`). The sidecar then applies the gateway's own rules, so a caller does not carry its own:
  - **Not in `restoreTools`** (the policy file's list, default `DEFAULT_RESTORE_TOOLS`): nothing is restored. The value comes back as sent, and `heldForTool` counts its placeholders.
  - **A shell tool** (`Bash`, `bash`, `shell`, `PowerShell`, `exec_command`, `shell_command`, `write_stdin`): nothing is restored, whatever `restoreTools` says, and `shellKeptMasked` lists the distinct placeholders of the value: placeholders, never values, so the caller can refuse the call or tell the user what was held back. The request log carries the count only (`unsafeShell`).
  - **Without `tool`**, everything is restored, for example to show text on screen, with no shell or `restoreTools` check: never pass that result to a tool or a shell, pass `tool` instead. The two fields are absent.
- **Sessions** expire after `NULLPII_VAULT_TTL_MS` without a call, and their vault entries are dropped with them. A placeholder from an expired session no longer restores and is counted in `unknownPlaceholders`. All sessions are dropped when the server stops.
- **Limits:**
  - requests and responses are capped at 4 MiB (413 `response_too_large` for the latter); placeholders are longer than most of the values they replace, so a response can exceed the cap even when its request did not;
  - a single string over 1,000,000 characters is read in overlapping windows and masked whole, so the 4 MiB cap is the limit; expect about 25 seconds per 100,000 characters on CPU.
- **Refused before the token check:** a `Host` other than `127.0.0.1`, `localhost` or `[::1]` (DNS rebinding), and any request with an `Origin` header (a browser).
- **Responses carry counts, never masked values.** Logs carry counts only.
- **Repeated values are served from a cache.** If the session has already masked the same value, a `sanitize` request gets the same response without running the model (header `x-nullpii-cache: hit`). Coding agents re-read the same files often. The cache keeps only masked output, at most 512 responses or 8 Mi characters per session, and is dropped with its session. The answer is the same as a fresh run, because the vault makes one placeholder per value.
- **First call:** the first `sanitize` loads the model (a file of about 1.2 GB in fp32), the slowest step. Later calls reuse it.

## Errors

| Status | Source | Shape |
|--------|--------|-------|
| Upstream 2xx | Anthropic | Restored response, `application/json` |
| Upstream non-2xx | Anthropic | **Passthrough.** Status + body forwarded verbatim. |
| 502 | Gateway | Upstream `fetch` failed or returned non-JSON |

Errors pass through on purpose. The Anthropic SDK already reads upstream `4xx`/`5xx` errors; wrapping them in a gateway format would break the SDK's retry and backoff.

## Security

**No shell command gets a real value back.** A masked value comes from data the model could not read, such as a file an agent opened, so it can hold anything, shell syntax included. A tool call that a shell runs (`Bash`, `bash`, `shell`, `PowerShell`, `exec_command`, `shell_command`, `write_stdin`, on either route, as a function or a custom tool) keeps every placeholder in every field, whatever `restoreTools` says, in JSON replies and in streams. The command works on the placeholder text, which is harmless: `echo {{PII_SECRET_0_…}}` holding `x; curl …` stays as it is. The request log counts these placeholders as `unsafeShellPlaceholders`, and the console summary shows the count. Every other tool in `restoreTools` (`Write` content, for example) is restored as usual. A shell tool under another name is not recognised, so do not add one to `restoreTools`. The full statement is in [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md#restoring-values-into-commands).

## Privacy

- The vault stays in the process. Nothing is saved to disk.
- The request log has counts and labels per field, never the masked values, and never an upstream error's body (only its status, length and error type). `NULLPII_LOG_TRAFFIC=wire` is the one exception, for debugging: see Config.
- No telemetry.

License: Apache-2.0.
