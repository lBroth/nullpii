# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

nullpii 0.5.0: a retrained model, a gateway and a Claude Code mod built for coding agents, one policy file for every surface, and a benchmark rebuilt on held-out data. 0.4.0 was prepared but never published; its changes are included here. Changes marked **Breaking** need code or configuration changes.

### Measured

On five public datasets chosen before any tool ran on them (`packages/eval/METHOD.md`), nullpii's macro char-F2 is 0.756, second of 15 open-source detectors behind rizzo-pii (0.770), with the highest recall of any tool's best-scoring configuration (0.960) and among the lowest precision; its margin over the other 13 rests on one dataset (clinical notes in Greek and German). Scored with the PIIMB leaderboard's method, its average F2 (0.851) is above the 35 listed tools.

### Breaking

- **The module-level `sanitize()` and `restore()` are removed.** They kept a cache of engines that was never released. Create an engine with `new NullPii(config)`, keep it, and call `dispose()` when done.
- **An engine used after `dispose()` throws `EngineDisposedError`.** `dispose()` waits for calls in flight and for an initialisation in progress.
- **`urlAllowlist` is a per-host policy:** `'none'`, or `{ hosts, replaceDefaults }` mapping each host (`docs.python.org`, or `*.github.com` for a domain and its subdomains) to `'full'`, `'host'` or `'mask'`. `PUBLIC_URL_HOSTS` is replaced by `DEFAULT_URL_RELEASES`. Customer consoles under a vendor domain (`console.aws.amazon.com`) are now masked, and a URL whose query carries a credential is never released.
- **`TextTooLongError` reports characters,** not bytes: the input cap (1,000,000) always counted `string.length`.
- **`ModelVariant` is `'fp32' | 'fp16' | 'auto'`.** `'int4'`, which was accepted and ignored, is gone; an unknown variant throws.
- **`PiiVault.sanitize` returns `MaskResult`;** `SanitizeResult` extends it with `modelUnscannedWords`.
- **CLI:** `nullpii models download` is removed (use `nullpii prefetch --backend --variant`); `nullpii sanitize` no longer takes `--session` or prints a session id.
- **Gateway:** real values go back only into the tools in `restoreTools` (by default the tools that run on this machine); web and MCP tools keep the placeholders. JSON replies and streams decide alike: Anthropic server and MCP tool calls (`server_tool_use`, `mcp_tool_use`) never get values back, whatever their name, nor does streamed tool input whose tool was never named; a streamed OpenAI custom tool call gets them like a non-streamed one. Environment variables are parsed strictly, and a value outside the documented ones stops the gateway at startup: integers must be whole and in range, `NULLPII_DISABLE_HINT` is `0` or `1` (`true` used to be ignored), and `NULLPII_UPSTREAM` and `NULLPII_OPENAI_UPSTREAM` must be `http:` or `https:` base URLs without credentials, query string, fragment or trailing `/v1`.
- **`onnxruntime-node` 1.30 or later** is required (peer `^1.30.0`): the version nullpii is measured with, and the first whose installer carries no known advisory.
- **Sidecar API:** `restore` takes `tool` instead of `shell`, and every call on a session needs the session's secret (`x-nullpii-session-secret`), returned once when it is created.

### Added

- **A retrained detection model** (`docs/WEIGHTS_PROVENANCE.md`): same base and size, trained only on licence-clean sources, covering secrets, financial and developer identifiers, and five extended categories. Published at a pinned revision whose files nullpii checks by SHA-256 (`ModelRef.sha256`).
- **Extended categories,** on by default: `private_organization`, `private_occupation`, `private_demographic`, `private_sensitive`, `private_title`. Turn any off with `disabledCategories`.
- **One policy file for every surface:** `~/.config/nullpii/config.json` (or `NULLPII_CONFIG`) sets `disabledCategories`, `categoryThresholds`, `threshold`, `urlAllowlist` and `restoreTools` for the library (`resolveConfigFile`, `toEngineConfig`, `configFilePath`), the CLI (`--config`, `nullpii config`), the gateway and the mod. Unknown keys are errors.
- **fp16 on CUDA:** `backend: 'cuda'` loads `model_fp16.onnx` when the model ships it (about 15% faster, recall unchanged).
- **Claude Code mod** (`packages/claude-code-mod`, preview): masks prompts, tool results, attachments and `CLAUDE.md` before Claude reads them, restores real values only into the tools the policy lists, draws the transcript with real values, shows what was masked above the prompt and in `/pii`, asks the user before a tool call it recognises as writing the policy file (best effort), and fails closed. Its `nullpii-policy` skill shows or changes the policy on request.
- **Gateway:** an OpenAI-compatible route (`/v1/chat/completions`), and a sidecar API (`/v1/sidecar/*`) with per-session vaults, an idle TTL, a session cap, a per-session cache of masked results, and the policy in `GET /v1/sidecar/status`.
- **`SanitizeResult.modelUnscannedWords`** counts words the model could not read (a single word longer than its input budget); the gateway reports them too.
- **Italian Partita IVA** next to its keyword or with the `IT` prefix, and omocodic and lowercase codici fiscali.
- **One placeholder per value** in a session, so the model can still tell one person from another.

### Changed

- **Recall first:** a lower decode threshold (0.05) with per-label cuts; fewer characters leak, at some cost in over-masking.
- **Less over-masking on developer content:** log-record timestamps, subresource-integrity digests, package-registry, CI and badge URLs, and code-host and documentation links stay readable; a span across two links is judged one URL at a time; only the URL token itself is ever released.
- **One address, one placeholder:** parts of an address split by the model are joined across short separators; a geolocation that is not a coordinate is masked as an address.
- **Gateway image:** runs as the unprivileged `node` user with production dependencies only, `LICENSE` and `NOTICE`, a base pinned by digest, and examples that publish the port on `127.0.0.1` only.
- **Eval kit:** competitors run as their authors ship them, at pinned revisions (`packages/eval/METHOD.md`); the bench file drops 1,617 rows derived from ai4privacy text, whose licence restricts commercial use.

### Fixed

- A window cut by the encoder's budget hid the rest of dense text from the model; windows now advance by what the encoder kept.
- Overlapping spans broke the byte-exact restore; they are merged before masking, and a kept span grows to cover what its duplicates covered.
- A low-scoring model span could silence a recognizer or another span before the threshold dropped it; thresholds now run first, and recognizers defer only to a model span that covers their whole match.
- Decoded `%XX` and HTML escapes mapped to the end of their sequence, leaving the first escaped character visible.
- Empty input, whitespace, and words longer than the model's budget crashed `sanitize()`.
- Punctuation was trimmed off `secret` spans; two cold calls each loaded an ONNX session; some recognizer patterns could backtrack quadratically on long input (all are bounded now).
- Gateway: a client disconnecting mid-stream did not cancel the upstream call; streams ignored backpressure; a failed request leaked its vault session; streamed tool input could come back as invalid JSON.
- Model download: a file is checked against its pinned hash before it replaces the cached copy.

### Security

- **Restoring into shell commands.** In a shell tool's `command` (`Bash`, `bash`, `shell`; string or argv array), a placeholder gets its value back only where the value cannot change what runs: quoting, heredocs, comments and nested interpreters are taken into account, and a command that sends data off the machine (`curl`, `ssh`, `git push`, …) gets no values at all. Best effort; see `SECURITY.md`.
- **Gateway requests are scanned whole:** every content block (documents, search results, citations, MCP blocks, unknown block types), `metadata`, tool schemas' descriptions and enums, tool-input object keys, and on the OpenAI route `user`, `metadata` and function parameters. Images and binary documents are counted as unscanned.
- **Gateway logs keep no part of an upstream error body:** an error can quote the request, unscanned fields included. Both routes log its status, length and identifier-shaped `type` / `code`; the Anthropic route used to log its first 500 characters.
- **Sidecar sessions need their own secret,** so a command that inherited the bearer token cannot read another session's values. The mod keeps the secret in memory and its token in a sensitive plugin option.
- **Release pipeline:** npm trusted publishing (no token in the repository), no dependency install scripts in publish jobs, release tags only from main, and image pushes only after tests.
- **Paths:** user-supplied paths are sandboxed with a separator-aware check, and model repository and revision names are validated.
- **Dependencies:** the gateway's fastify is 5.12.5, with its URI and router dependencies pinned to patched releases (advisories in 5.8: schema and header validation bypasses, request body replacement); `npm audit --omit=dev` reports nothing. Development tools (vitest, vite, cyclonedx) are on patched releases too.

## [0.3.0] — withdrawn

First public release (npm `nullpii@0.3.0` and `@lbroth/nullpii-gateway@0.0.3`, and the Hugging Face model it downloaded). Withdrawn with 0.5.0: its benchmark used test sets that overlapped the training distribution, and its package shipped a demo video. Use 0.5.0.
