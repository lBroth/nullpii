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

The gateway has no authentication of its own: anyone who can reach its port can send requests through it with your upstream credentials. Inside the container it listens on all interfaces, so publish the port on `127.0.0.1` as above, not with a bare `-p 8787:8787`. The image runs as the unprivileged `node` user; its model cache is `/home/node/.cache/nullpii`.

The model is not in the image. The first request that needs it downloads it (about 1.2 GB) into the cache volume and waits for the download. To fetch it beforehand, run the nullpii CLI the image carries against the same volume:

```bash
docker run --rm -v nullpii-cache:/home/node/.cache/nullpii \
  ghcr.io/lbroth/nullpii-gateway:0.5 node bin/nullpii.mjs prefetch --backend cpu
```

The image's health check calls `/health`, which answers as soon as the server listens: it does not wait for the model.

A worked `docker-compose.yml` plus a Claude Code integration walk-through
lives at [`examples/claude-code/`](https://github.com/lBroth/nullpii/tree/main/examples/claude-code).

### Standalone via `npx` (no clone)

If you don't want to clone the repo or run Docker, install the gateway
from npm with its two peer dependencies, `nullpii` (the detection
library) and `onnxruntime-node` (the runtime it runs the model with),
and run it as a one-shot binary:

```bash
# install once; listing the peers also puts the `nullpii` CLI on your PATH
npm install -g nullpii onnxruntime-node @lbroth/nullpii-gateway
nullpii-gateway

# or without a global install
npx -p nullpii -p onnxruntime-node -p @lbroth/nullpii-gateway nullpii-gateway
```

On Linux x64 without an NVIDIA GPU, run the install with `ONNXRUNTIME_NODE_INSTALL=skip` in its environment: otherwise `onnxruntime-node`'s install script downloads its CUDA libraries from NuGet (the `cuda12` package, which links the CUDA 13 runtime), which the CPU backend does not use (its CPU runtime ships in the npm package).

Settings come from environment variables and the policy file, never from the command line: `nullpii-gateway` starts the server with no argument, `--version` (`-v`) and `--help` (`-h`) answer without starting it, and anything else on the command line, or more than one option, exits with status 2 and starts nothing. A port that is already taken, an address that cannot be bound, a bad variable or policy file, or a missing build or peer exits with status 1 and one line on standard error.

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
Pre-cache the GLiNER model once (`npx nullpii prefetch`) so a reload
does not download it again; the first request after a reload still
loads the model, which took 1.7 to 2.2 seconds in our measurements.

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

- `system` and every message's content: text, documents with a text or content source, search results, citations, tool results, and any block type the gateway does not know yet (every field but `type`, ids, names, signatures, media types, `cache_control`, and the encrypted payloads of server-tool results, which the upstream verifies);
- tool calls in the history (`tool_use`, `server_tool_use`, `mcp_tool_use`): every string value of their `input`, and its object keys, since a tool can key data by a name or an email;
- every tool definition (client tools, server tools such as web search, MCP toolsets): its `input_schema`'s `description`, `title` and `$comment` texts and `enum`, `const`, `default` and `examples` values, at any depth, and every string value of its other fields except `name`, `type`, `cache_control`, `allowed_domains`, `blocked_domains`, `allowed_callers`, `model` and `mcp_server_name`. That covers the `description`, `input_examples`, web search's `user_location` and any field the gateway does not know yet. Property names and keywords stay as written, because the model needs them to call the tool, and so do the keys of `input_examples`, which are those property names. A masked `user_location.country` or `timezone` is no longer a valid code, and the upstream may refuse the request;
- the structured-output spec, `output_config.format` (and the deprecated `output_format`): its `description` and its `schema`, as for `input_schema`;
- `metadata` values (`user_id` is often an email) and `stop_sequences`.

A masked `enum` or `const` value is what the model then answers with. It comes back restored in the reply text and in the input of a tool in `restoreTools`; the input of any other tool keeps it masked (see Restored, below).

**Not scanned:** the payload of images and documents sent as base64, URL or file reference (counted as "not scanned"; a document's other fields, such as its `title`, are scanned), `thinking` blocks (signed by the upstream, and generated from masked input anyway), the tool-definition fields named above (what the API and the model match a tool by, and the web tools' domain filters, which the upstream applies as written), the URL query string (`?beta=true`), and every other top-level field, forwarded as the client sent it: protocol (`model`, sampling parameters, `tool_choice`, `thinking`, `output_config` apart from its `format`, `context_management`, `container`, and fields the gateway does not know) and `mcp_servers`, whose URLs and credentials are meant for the upstream.

**Restored** in the response: `content[].text`, and the input of a client tool call (`tool_use`) to a tool in `restoreTools` (string values, and object keys that hold a placeholder). Every other tool call keeps its placeholders, counted in the request log's `heldForToolPlaceholders`: a tool outside `restoreTools`, and server and MCP tool calls (`server_tool_use`, `mcp_tool_use`), which the upstream runs, whatever their name.

With `stream: true`, text deltas are restored as they stream, holding back only a placeholder split across deltas. Tool input (`input_json_delta`) is held per content block and sent once, just before its `content_block_stop`, restored by the same rule as a JSON reply: the tool is read from the block's `content_block_start`, and input whose `content_block_start` never arrived keeps its placeholders. The assembled JSON is parsed and its string values restored, so a value holding a quote or a newline stays valid JSON. A client that disconnects mid-stream cancels the upstream call, so Anthropic stops generating (and billing) the rest of the reply.

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

The gateway appends `/v1/chat/completions` to `NULLPII_OPENAI_UPSTREAM`, so set it without `/v1`: `https://api.openai.com` (the default), `http://127.0.0.1:11434` for Ollama, `https://openrouter.ai/api` for OpenRouter. The client headers forwarded upstream are `Authorization`, `OpenAI-Organization`, `OpenAI-Project`, `OpenAI-Beta`, `User-Agent` and `x-stainless-*`.

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

**Restored** in the response: each choice's `content` and `refusal`, and, for a tool in `restoreTools`, `tool_calls[].function.arguments` (the string values of the parsed JSON, so a restored value holding a quote stays valid JSON), a custom tool call's `input`, and `function_call.arguments`; a call to any other tool keeps its placeholders. With `stream: true`, `delta.content` and `delta.refusal` are restored as they stream, and only text that is or could be the start of a placeholder (up to 256 characters) is held back until it is complete. Tool-call arguments and custom tool-call input are held per call and sent in one piece, restored by the same rule, with the chunk that carries the choice's `finish_reason` (or just before `data: [DONE]`, or at the end of a stream cut off, if that never comes); each call's `id` and tool name still arrive at once, and a call whose tool name never arrived keeps its placeholders. Not restored: `logprobs` tokens and audio transcripts keep their placeholders. In the command of a shell tool (`Bash`, `bash`, `shell`; Codex's `exec_command`, `shell_command` and `write_stdin`, and Claude Code's `PowerShell`, get no value, and no shell tool does when the gateway runs on Windows (SECURITY.md covers a gateway in Docker serving an agent on Windows)), a value goes back only where it is safe: see [Security](#security).

When something was masked, the gateway appends `LLM_PRESERVATION_HINT` as a last `system` message: appended, never prepended, so it does not shift the conversation. Placeholders carry a per-request random prefix, so an upstream prompt cache cannot reuse a prefix past the first masked value. `NULLPII_DISABLE_HINT=1` turns it off, for example for an upstream whose chat template accepts a system message only at the start.

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

An unknown key, category, host or release stops the gateway at startup with the reason. So does an environment variable outside its documented values: an integer that is not a whole number in its range (`30m`, `1e6` and `0` are refused rather than read as something else), a `NULLPII_DISABLE_HINT` other than `0` or `1`, or an upstream that is not a base URL as described below. The error names the variable. It never repeats the sidecar token, and repeats an upstream URL only once it is known to carry no credentials or query string.

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
| `NULLPII_MODEL_DIR` | (auto-fetch) | Local GLiNER ONNX dir |
| `NULLPII_BACKEND` | `cpu` | `cpu` / `mps` / `cuda` / `auto` |
| `NULLPII_LOG_LEVEL` | `info` | Fastify log level |
| `NULLPII_BODY_LIMIT_BYTES` | `10485760` | Request body cap (10 MB), at least 1 |
| `NULLPII_LOG_TRAFFIC` | (off) | Set to `wire` to dump to stdout, for debugging, the request body as forwarded, its headers (auth headers as their last 6 characters and length) and the raw upstream response before restore, 64 KB per dump. They hold placeholders where nullpii found personal data, and everything else as it was sent or written: values it missed, fields it does not scan (images, documents, `mcp_servers` and their credentials) and the model's output. Keep these dumps local. |
| `NULLPII_DISABLE_HINT` | `0` | `1` suppresses the `LLM_PRESERVATION_HINT` system-prompt injection; `0` keeps it. Useful when an upstream proxy / cache rejects the modified system prompt; leave unset in normal operation. |

Both upstreams must be `http:` or `https:` base URLs, without credentials (`user:password@`: the gateway forwards the client's own auth headers), a query string, a fragment or a trailing `/v1`; anything else is refused at startup. Trailing slashes are dropped.

## Sidecar API

Session-scoped sanitize and restore for local callers that keep one vault session across many calls, such as an editor or coding-agent extension. It is off unless `NULLPII_SIDECAR_TOKEN` is set.

```bash
export NULLPII_SIDECAR_TOKEN=$(openssl rand -hex 32)
nullpii-gateway
```

Before sending the token, a caller can check that the process on the port is this sidecar: `POST /v1/sidecar/challenge` with `{ nonce }` (32 random bytes, lower-case hex) answers `{ proof }`, the HMAC-SHA256 of `nullpii-sidecar-challenge-v1\n` followed by the nonce, keyed by the token. It needs no token, so a process that took the port while the gateway was down learns nothing from it, and cannot answer it. The Claude Code mod checks before every request.

Every other request needs `Authorization: Bearer $NULLPII_SIDECAR_TOKEN`. Every call on a session also needs that session's secret, `x-nullpii-session-secret`, which the `PUT` that creates the session returns once.

| Method and path | Body | Response |
|---|---|---|
| `POST /v1/sidecar/challenge` | `{ nonce }` | `{ proof }`; no token needed |
| `GET /v1/sidecar/status` | — | `{ status, sessions, policy }`, `policy` being `{ file, loaded, config, restoreTools }` |
| `PUT /v1/sidecar/sessions/:key` | — | 201 `{ status: "created", secret }` for a new session. For an open one: 200 `{ status: "exists" }` with its secret, 409 `session_exists` without it. 429 when `NULLPII_SIDECAR_MAX_SESSIONS` are open. |
| `POST /v1/sidecar/sessions/:key/sanitize` | `{ value }`: a string or any JSON | `{ value, captured, capturedByLabel, modelUnscannedWords }` |
| `POST /v1/sidecar/sessions/:key/restore` | `{ value, fields?, tool? }` | `{ value, replacements, replacementsByLabel, unknownPlaceholders, foreignPlaceholders }`, plus `shellKeptMasked` for a shell tool and `heldForTool` for a tool outside `restoreTools` |
| `DELETE /v1/sidecar/sessions/:key` | — | 204, or 404 if unknown |

Calls on an unknown session answer 404 `session_not_found`; a missing or wrong secret answers 403 `bad_session_secret`.

- **`key`** is chosen by the caller (`[A-Za-z0-9._-]`, up to 128 characters), for example the agent's conversation id. It is not a secret.
- **The session secret** (32 random bytes, base64url) is handed out only when the session is created, and the gateway keeps only its hash. Keep it in memory. It is what separates sessions: a process that has the bearer token but not the secret, such as any command started from a shell that exported `NULLPII_SIDECAR_TOKEN`, cannot read or restore another caller's values, close its session, or take it over by opening it again. A caller that lost the secret opens a session under a new key.
- **`value`**: every string is processed, object keys included (`sanitize` masks a key that holds personal data, `restore` puts it back). Numbers and booleans pass through.
- **`fields`** restores only those top-level keys of an object. Use it to put real values back into the arguments a tool writes to disk, while every other argument keeps its placeholders.
- **`tool`** names the tool whose input the value is (an object, else 400 `tool_requires_object_value`). The sidecar then applies the gateway's own rules, so a caller does not carry its own:
  - **Not in `restoreTools`** (the policy file's list, default `DEFAULT_RESTORE_TOOLS`): nothing is restored. The value comes back as sent, and `heldForTool` counts its placeholders.
  - **A shell tool** (`Bash`, `bash`, `shell`; Codex's `exec_command`, `shell_command` and `write_stdin`, and Claude Code's `PowerShell`, get no value, and no shell tool does when the gateway runs on Windows (SECURITY.md covers a gateway in Docker serving an agent on Windows)): the top-level command field, when restored, follows the [shell rule](#security): a placeholder gets its value back only in the body of a quoted heredoc that one of a few fixed commands writes out as data (such as `cat > notes.md <<'EOF'`, `cat <<'EOF'`, `git commit -F - <<'EOF'`; the full list is in SECURITY.md); never in a word of the command, and never in any other command. Of its other fields, only the descriptive `description` and `justification` get values back; any other (`workdir`, `cwd`, `env`, …) keeps its placeholders, since it can choose where or how the command runs. `shellKeptMasked` lists the distinct placeholders left masked in the command, in any other field it restores, or in a key of the input (every field for `exec_command`, `shell_command`, `write_stdin` and `PowerShell`, and for every shell tool on Windows; otherwise every field but `description`/`justification`): placeholders, never values, so the caller can tell the user what was held back. The request log carries the count only (`unsafeShell`).
  - **Without `tool`**, everything is restored, for example to show text on screen, with no shell rule and no `restoreTools` check: never pass that result to a tool or a shell, pass `tool` instead. The two fields are absent.
- **Sessions** expire after `NULLPII_VAULT_TTL_MS` without a call, and their vault entries are dropped with them. A placeholder from an expired session no longer restores and is counted in `unknownPlaceholders`. All sessions are dropped when the server stops.
- **Limits:**
  - requests and responses are capped at 4 MiB (413 `response_too_large` for the latter); placeholders are longer than most of the values they replace, so a response can exceed the cap even when its request did not;
  - a single string over 1,000,000 characters fails with 413 `text_too_long`, so split it.
- **Refused before the token check:** a `Host` other than `127.0.0.1`, `localhost` or `[::1]` (DNS rebinding), and any request with an `Origin` header (a browser).
- **Responses carry counts, never masked values.** Logs carry counts only.
- **Repeated values are served from a cache.** A `sanitize` request whose value the session has already masked gets the same response without running the model (header `x-nullpii-cache: hit`). Coding agents re-read the same files often. The cache keeps only masked output, at most 512 responses or 8 Mi characters per session, and is dropped with its session. The answer is identical to a fresh run because the vault mints one placeholder per value.
- **First call:** the first `sanitize` loads the model (a file of about 1.2 GB in fp32), its slowest step; later calls reuse it.

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

**Shell commands keep unsafe values masked.** A masked value comes from data the model could not read, such as a file an agent opened, so it can hold anything, shell syntax included. When the gateway puts real values back into a tool call that a shell runs (a tool named `Bash`, `bash` or `shell` and listed in `restoreTools`, on either route, and on the OpenAI route as a function or a custom tool; Codex's `exec_command`, `shell_command` and `write_stdin`, and Claude Code's `PowerShell`, get no value, and no shell tool does when the gateway runs on Windows (SECURITY.md covers a gateway in Docker serving an agent on Windows)), each placeholder in the `command` is restored only where the rules below allow:

- A value comes back only in the body of a quoted heredoc that one of a few fixed commands writes out as data. The command's first line is `cat > FILE <<'EOF'` (also `>>`, or `cat <<'EOF' > FILE`), where `FILE` is a document (`.md`, `.markdown`, `.csv`, `.tsv`, `.log`, `.rst`, with no hidden directory or file on its path, not in a `bin/`, `sbin/`, `etc/`, `LaunchAgents/` or `systemd/` directory, and absolute when the call sets a working directory; not `.txt`, which pip, CMake and pytest read as input); `cat <<'EOF'` (standard output); or `git commit -F - <<'EOF'` (also `-F-`, `--file=-`, `--file -`; the commit message; before `-F` only `-a`/`--all`, `-q`/`--quiet`, `-s`/`--signoff`, `--amend` or `-n`/`--no-verify`), optionally after any number of `git add …` and `mkdir …` commands, each followed by `&&`. The text follows, and the closing line is the last line of the command.
- Every other command, and every placeholder anywhere but in that text (an argument, a path, an option, the first line), keeps every placeholder: no reading of shell syntax is both complete and simple, so the rule does not try. Claude Code's usual commit form, `git commit -m "$(cat <<'EOF' … EOF)"`, gets no values; the Claude Code mod tells Claude to use `git commit -F -`.
- A value holds no line break, no other control character but tab, no `<<` and not the delimiter's name, and no line of the text starts with the delimiter; otherwise the placeholder stays. So `cat > notes.md <<'EOF'` and `git commit -F - <<'EOF'` get names with spaces and apostrophes back.
- A call that sets an `env` (any value but `{}`, `""` or `null`) keeps every placeholder in its command, and a command sent as an argv array gets values only in the `-c` script of a POSIX shell (`["bash", "-lc", "…"]`), read as above.

The full rule is in [SECURITY.md](https://github.com/lBroth/nullpii/blob/main/SECURITY.md#restoring-values-into-commands). Otherwise the placeholder stays as written, and the command works on the placeholder text, which is harmless: `echo {{PII_SECRET_0_…}}` holding `x; curl …` stays as it is, and so does `echo '{{PII_PRIVATE_PERSON_0_…}}'` holding `Mary Ann`. A command over 262,144 characters keeps every placeholder. The same rule applies to JSON responses and to streams. Placeholders kept this way are counted as `unsafeShellPlaceholders` in the request log and shown in the console summary, as a count only. The tool call's descriptive fields (`description`, `justification`), and every other tool in `restoreTools` (`Write` content, for example), are restored as usual. A shell tool's JSON input that does not parse keeps all of its placeholders, as does one that parses to anything but an object; a custom `Bash`, `bash` or `shell` tool's plain-text input is the command itself and gets the same rule; a custom `exec_command`, `shell_command`, `write_stdin` or `PowerShell` tool gets no value.

The list of forms in SECURITY.md is closed: a command that is not one of them gets nothing.

## Privacy

- Vault stays in-process. No persistence.
- Counts and label histograms are logged per request; the request log
  never carries the values that were masked (the gateway logs counts
  and labels only, field by field), nor an upstream error's body (its
  status, length and error type only). `NULLPII_LOG_TRAFFIC=wire` is
  the exception, for debugging: see Config.
- No telemetry / phone-home.

License: Apache-2.0.
