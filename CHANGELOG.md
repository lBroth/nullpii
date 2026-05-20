# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — first public release

Initial Apache-2.0 public release. Published packages:

- **`nullpii@0.3.0`** — core PII sanitization library (npm). GA: stable
  public API surface (`NullPii`, `sanitize`, `restore`, `wrapForLLM`,
  `RestoreStream`, recognizers).
- **`@nullpii/gateway@0.0.3`** — Anthropic Messages API drop-in proxy
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

### `@nullpii/gateway`

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
