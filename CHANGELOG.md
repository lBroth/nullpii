# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.4.0] — bench correctness + detection fixes

Started as gateway hardening from a Claude Code proxy integration
report. Two of the four filters that report motivated did not survive
measurement and were dropped; benchmarking them surfaced a defect in
the benchmark itself that had been mis-ranking every tool in the
published table. Public API surface unchanged.

### Behavior changes

- **Placeholder-escape PUA sentinels stripped before detection**
  (#43). User-authored `{{...}}` templates wrapped in PUA sentinels
  (`U+E000` / `U+E001`) used to be tagged as `private_person` by GLiNER
  when `any-ascii` left the codepoints in the normalized text. Vault
  substitution then corrupted the user's `{{...}}` into
  `{{PII_PRIVATE_PERSON_*}}...{{`. Now stripped in
  `normalizeForDetection` via the existing `ZERO_WIDTH_CHARS` set.
- **`private_geolocation` gated on coordinate shape.** The schema
  defines the label as a coordinate — all three recognizers that own it
  match lat/lon literals, and `core:geo-latlon-decimal` range-validates.
  The GLiNER head is prompted with the label zero-shot and never trained
  on it, so it was applying it to place names, regions and postcodes:
  only **7.6%** of its emissions on `ai4privacy-300k-heldout` were
  coordinate-shaped, the rest `Deutschland`, `Sachsen`, `52396`. Every
  gold span of the class is a lat/lon pair, so the gate removes false
  positives without touching a conforming true positive — measured
  **−2,317 FP, ±0 TP**, precision 0.129 → 0.902, recall unchanged. Runs
  before cross-label dedupe, so the model's competing `private_address`
  candidate survives the overlap instead of losing it to a label it
  should never have won (+83 recovered TP: `private_ip` +60,
  `private_address` +11, `private_vehicle_id` +7, `private_mac` +5).
- **Public-URL allowlist on by default** (#45). URLs targeting
  `PUBLIC_URL_HOSTS` (github / gitlab / docs.python.org / anthropic /
  openai / huggingface / wikipedia / mdn / stackoverflow / cloud
  vendor docs / standards bodies — full set in `src/url-filter.ts`)
  are dropped from `private_url` output. Subdomain match
  (`docs.python.org` covered by `python.org`); `www.` stripped. Opt
  out with `new NullPii({ urlAllowlist: 'none' })`.

  An allowlisted URL is dropped **only when it carries no other PII
  span**. `core:url` matches `[^\s<>"]+`, so PII glued to a URL is
  swallowed into the URL span and containment-elimination then drops
  the inner span regardless of score; dropping the outer span would
  have emitted the nested secret as plaintext behind a 20-character
  allowlisted prefix (`https://github.com/a,AKIA…`). Fail-safe by
  construction: a reference URL embedding anything identifying reverts
  to whole-URL redaction. Also refuses to judge a span carrying more
  than one scheme (`core:url` does not stop at `,`), and matches on
  `hostname` rather than `host` so a non-default port no longer
  silently disables the allowlist.

### Dropped before release

- **Template syntax mask** (#44) — **closed, not shipped.** #43 already
  fixes the motivating case: ten template-variable probes on `main`,
  including the two this feature cited, produce zero tagged spans, and
  the regression test in `test/nullpii.test.ts` passes without it. The
  implementation also made `MAX_INPUT_BYTES`-sized input quadratic
  (69.7 s on 1 MB, against ~70 ms for the whole rest of the pipeline),
  and unbalanced delimiters suppressed redaction in ordinary text — a C
  array initializer and a one-character typo both leaked real emails.
- **`private_date` threshold 0.85** (#46) — **closed, not shipped.** It
  does not reach its own target: gateway boilerplate dates score
  0.993–1.000, so an 0.85 cut removes none of them. The score tracks
  span-boundary confidence, not PII relevance — a birth date inside a
  two-date span scores 0.574 and a neutral one scores 0.609 — so no cut
  point separates them. Measured cost was **419 true positives dropped
  to remove 453 false ones** (1.08 : 1), with `private_date` F1 going
  *down* 0.004. What it did remove was boundary fragments (`'62'`, a
  bare `'1938'` split off `March 17, 1938`), not the copyright footers
  it was aimed at.

### Bench

The benchmark's ai4privacy and isotonic loaders resolved unknown
upstream labels through `dict.get()`, which returns `None` both for
"deliberately excluded" and for "never seen". Gold was deleted with no
signal — **56.4%** on `ai4privacy-300k-heldout`, ~11% on the isotonic
`-heldout` rows. Because `macro_f1` skips zero-support classes,
predictions on a class whose gold had been deleted cost nothing, so the
bug hid recall *and* inflated precision. All 25 recovered labels are
aliases of keys already in the maps; mapping and exclusion are now
distinct and an unknown label raises.

This moves every tool, not just `nullpii` — on `ai4privacy-300k-heldout`
it reorders 8 of 9 (`piiranha` +0.2347, `gliner-pii-large-v1` +0.1801,
`gliner-onnx-pii-fp32` +0.1423, `nullpii` −0.0519, `presidio` −0.1746).
The published v0.3.0 column is therefore **not comparable** to the
v0.4.0 column; the middle column restates v0.3.0 on the corrected
metric, and only the last delta is a product improvement.

| Metric | v0.3.0 as published | v0.3.0 re-scored | v0.4.0 | Δ (product) |
|---|---:|---:|---:|---:|
| OOD-7 macro F1 | 0.7784 | 0.8043 | **0.8290** | **+0.0247** |
| `nullpii-bench` F1 | 0.4228 | 0.4228 | **0.4519** | **+0.0291** |
| Cold start (M5 Pro CPU) | ~756 ms | — | not re-measured | — |

`presidio-synthetic` moves by exactly `+0.0000` — it carries no
`private_geolocation` gold and none of its 89 URLs are allowlisted,
which makes it the negative control for both behavior changes.

The 11 canonical rows the gold fix did not touch still carry v0.3.0
numbers; the published table is not fully regenerated yet.

### Config additions

- `NullPiiConfig.urlAllowlist?: 'none'` — opt out of public-URL allowlist.

### Internal

- `src/geo-filter.ts` — `isCoordinateShaped`, `dropNonCoordinateGeolocation`. Range and null-island rejection defer to the existing `latLonPairInRange`.
- `src/url-filter.ts` — `PUBLIC_URL_HOSTS`, `isPublicUrl`, `dropCleanPublicUrlSpans`.
- `src/placeholder-escape.ts` — sentinel chars now exported individually as `PLACEHOLDER_SENTINEL_LEFT` / `PLACEHOLDER_SENTINEL_RIGHT` for reuse in `normalize.ts`. Source uses `''` / `''` escape syntax instead of raw PUA (grep-friendly, no mojibake on GitHub mobile).
- `packages/eval/scripts/ood_macro.py` — single definition of the OOD-7 set, computed from any `matrix.json`. The root README enumerated 7 datasets and `packages/eval/datasets/README.md` said 5, a 0.0128 discrepancy that would have silently blocked any regression gate. Exits non-zero if a cell is missing or `CRASHED`.
- `packages/eval/pyproject.toml` — the wheel force-included the whole `datasets/` directory, so any file dropped there was redistributed. Now a per-file allowlist with the upstream licence annotated per line.

### Known issues

- Partially-overlapping spans corrupt the output and break the restore
  round-trip. `x https://github.com/users/john.doe@acme.com y` yields
  `private_url[2,44]` and `private_email[27,46]` — IoU 0.39, below the
  dedupe threshold, so both survive and overwrite each other during
  vault substitution; the email span also ends past the end of the
  string. Pre-existing in 0.3.0, not introduced here.

### Test plan

- 300 unit + integration tests passing (was 271 on v0.3.0).
- New tests: `test/geo-filter.test.ts` (10 — coordinate shapes, the place names and postcodes the head mislabels, IPv4 not reading as a pair, range and null-island rejection), `test/url-filter-nested.test.ts` (10 — nested-secret retention, concatenated URLs, non-default ports, near-miss hosts), `test/url-filter.test.ts` (7), plus integration cases in `test/nullpii.test.ts`.
- `test/url-filter.test.ts`'s span fixture was corrected: it parked every span at offset 0, which under a containment-aware drop rule reads as "this URL has PII nested inside it".

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
