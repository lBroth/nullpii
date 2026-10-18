# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Changes from the measured A/B loop (`packages/eval/scripts/ab/PROTOCOL.md`, results in `LOG.md`). Each one passed the protocol's checks on the tuning set before it was kept.

### Added

- **Italian Partita IVA (VAT number)**, masked as `account_number` when it follows its keyword (`P.IVA`, `Partita IVA`, `VAT number`, …) or carries the `IT` prefix, and passes the office-code and check-digit tests. Bare 11-digit runs are left alone: a checksum alone passes about one random number in ten (#38). For a sole trader or a freelancer the number identifies a person.
- **Extended categories:** `private_organization`, `private_occupation`, `private_demographic`, `private_sensitive` and `private_title`. They are prompted and masked by default. Turn any category off with the new `disabledCategories` config option, for example `['private_organization', 'private_occupation']` to keep company names and job titles readable.

### Changed

- **Retrained detection model** (run H3b, `docs/WEIGHTS_PROVENANCE.md`). Same base model and size, trained on a larger corpus: a wider Nemotron-PII slice labelled for the extended categories, plus generated secrets, financial numbers, developer records and developer hard negatives.
  - **Report set:** macro char-F2 0.894 → 0.930. Recall rises from 0.922 to 0.977, so fewer characters leak; precision moves from 0.829 to 0.807.
  - **Speed:** unchanged (100k characters in 14.8 s against 14.7 s, M5 Pro CPU).
  - **Legal text is masked more:** court, prison and ministry names that contain a place name are now masked as addresses. Precision on TAB/ECHR falls from 0.932 to 0.840 at the same recall.
- **One placeholder per value** (#50). A value that recurs in a session reaches the model as the same token, so it can still tell the same person from someone else. Values are matched exactly, case included, so `restore()` stays byte-exact.
- **Recall-first thresholds.** The decode threshold drops to 0.05, with per-label cuts: date 0.125, email 0.075, IP and MAC 0.5. Fewer characters leak, at a small cost in over-masking.
- **Developer content is masked less:**
  - log-record timestamps;
  - pieces of subresource-integrity digests;
  - package-registry tarball URLs;
  - project-infrastructure hosts (badges, CI, package CDNs).
  - README badge rows: a span the model draws across two links (`[![build](https://img.shields.io/…)](https://travis-ci.org/…)`) is now judged one URL at a time, so public badge and CI links are left readable while a private URL next to them stays masked.
- **Geolocation:** a geolocation span that is not a coordinate is relabelled as an address instead of being dropped.

### Fixed

- `restore()` was not byte-exact when two detected spans overlapped. Overlapping spans are now merged before masking.
- On dense text, a window cut by the encoder's token budget hid its tail from the model. Windows now advance by what the encoder kept.
- An empty or whitespace-only input, or a window with zero words, crashed the model run.
- A recognizer deferred to any overlapping model span. It now defers only when the model span covers its whole match.
- A model span below its label's score threshold could silence or absorb another span before the threshold dropped it, leaving both unmasked. A MAC or IP address the model guessed as a date at a low score went out in the clear. Thresholds now run before deduplication and before recognizers defer to the model.
- Edge punctuation was trimmed off `secret` spans, leaving part of the credential unmasked.
- **Italian codice fiscale:** omocodic codes (digits replaced by the letters L–V, as the tax office does to tell apart two people) and codes written in lowercase were not recognized. Both are now. The validator also checks the day of birth, and rejects mixed case, which is a code identifier rather than a written code.

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
- **`private_geolocation` restricted to coordinates; place names
  relabelled `private_address`.** The schema defines the label as a
  coordinate — all three recognizers that own it match lat/lon literals,
  and `core:geo-latlon-decimal` range-validates. The GLiNER head is
  prompted with the label zero-shot and never trained on it, so it was
  applying it to place names, regions and postcodes: only **7.6%** of its
  emissions on `ai4privacy-300k-heldout` were coordinate-shaped, the rest
  `Holter Straße`, `Altrip`, `Sachsen`, `52396`. A non-coordinate
  `private_geolocation` span is now relabelled `private_address`, or
  dropped when it is a dotted quad so the `core:ipv4` recognizer labels
  it `private_ip`. Span-level this keeps the measured
  `private_geolocation` precision gain (0.129 → 0.902, recall unchanged)
  and the `private_ip` +60 TP.

  An earlier revision of this change *dropped* those spans. That scored
  well on label-matched span F1 but was a redaction regression: most of
  them sit on gold address PII (streets, postcodes, towns), and whenever
  no competing address candidate survived they reached the output
  unmasked. On label-agnostic char-level recall over the five tuning
  heldouts it cost 0.006–0.024 char-F2 per dataset (macro 0.8566 →
  0.8445). Relabelling recovers it (macro 0.8565, paired-bootstrap CI of
  the gain over dropping [+0.0109, +0.0130]) with no gold label losing
  more than 0.005 recall.
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

- `src/geo-filter.ts` — `isCoordinateShaped`, `resolveNonCoordinateGeolocation`. Range and null-island rejection defer to the existing `latLonPairInRange`.
- `src/url-filter.ts` — `PUBLIC_URL_HOSTS`, `isPublicUrl`, `dropCleanPublicUrlSpans`.
- `src/placeholder-escape.ts` — sentinel chars now exported individually as `PLACEHOLDER_SENTINEL_LEFT` / `PLACEHOLDER_SENTINEL_RIGHT` for reuse in `normalize.ts`. Source uses `''` / `''` escape syntax instead of raw PUA (grep-friendly, no mojibake on GitHub mobile).
- `packages/eval/scripts/ood_macro.py` — single definition of the OOD-7 set, computed from any `matrix.json`. The root README enumerated 7 datasets and `packages/eval/datasets/README.md` said 5, a 0.0128 discrepancy that would have silently blocked any regression gate. Exits non-zero if a cell is missing or `CRASHED`.
- `packages/eval/pyproject.toml` — the wheel force-included the whole `datasets/` directory, so any file dropped there was redistributed. Now a per-file allowlist with the upstream licence annotated per line.

### Detection defaults

- **Decode threshold 0.5 → 0.05; IP and MAC 0.5, dates 0.125, emails
  0.075.** Second step (iteration D3b, after the recognizer-deferral fix
  below removed the leak a lower threshold exposed): tuning-set macro
  char-F2 0.8918 → 0.9160 (CI of the gain [+0.0222, +0.0262]), recall
  +2.7 to +4.3 points, precision −0.9 to −1.3 points, no gold label loses
  recall, developer content masked 1.13% → 1.33%.
- **Decode threshold 0.5 → 0.2; IP and MAC keep 0.5.** (first step, D2) For redaction a
  missed character leaks, an extra one only costs context, so the
  threshold was selected on label-agnostic, recall-weighted char-F2 over
  the five tuning heldouts, under a fixed cap on extra masking of
  developer content (code, markdown, JSON). Tuning set: macro char-F2
  0.8565 → 0.8916 (paired-bootstrap CI of the gain [+0.0328, +0.0373]),
  every dataset up, no gold label loses recall, char-precision −0.007 to
  −0.010; developer content masked 4.78% → 5.09%. Callers who set
  `threshold` or `categoryThresholds` keep exactly their values; the new
  `DEFAULT_CATEGORY_THRESHOLDS` applies only when `categoryThresholds`
  is unset.

### Less over-masking on developer content

- **Package-registry tarball URLs are public.** `PUBLIC_URL_HOSTS`
  gains `npmjs.org` (the npm registry serves from `registry.npmjs.org`,
  not `npmjs.com`), `yarnpkg.com` and `pythonhosted.org`. A lockfile
  cites one such URL per dependency; on a 30k-char `package-lock.json`
  window 66 of them were masked. URL fragments the model emits inside a
  dropped public URL (`https:/`, `github.com`) now go with it instead of
  splitting the reference. Developer content masked: 5.09% → 1.68%;
  tuning-set recall unchanged.
- **Project-infrastructure URLs are public.** The allowlist gains the
  services READMEs link to: status badges (`shields.io`, `badgen.net`,
  `badge.fury.io`, …), CI and coverage (`travis-ci`, `circleci`,
  `appveyor`, `coveralls`, `codecov`), dependency and funding pages
  (`david-dm`, `snyk`, `tidelift`, `opencollective`), public package CDNs
  (`jsdelivr`, `unpkg`), `githubusercontent.com` (consistent with
  `github.com`), and `iana.org` / `apache.org` / `typescriptlang.org`.
  Personal websites stay masked. Claude-Code-traces tuning set
  char-precision 0.63 → 0.70, recall unchanged.
- **Log-record timestamps are not masked.** A timestamp that opens a
  log line and is followed by a log level (`2026-10-16T09:41:07Z INFO …`,
  `2026-10-16 09:41:07,123 - billing - WARNING - …`) dates the record,
  not a person, and an agent debugging a log needs it. The model labelled
  every one `private_date`. Deliberately narrow: a timestamp quoted in
  prose, a line-leading timestamp without a log level, and a bare date
  all stay masked (broader variants cost date recall on the benchmark
  gold, which treats timestamps in prose as personal data). On the
  Claude-Code-traces tuning set char-precision 0.44 → 0.63 with recall
  unchanged; tuning heldouts identical.
- **Subresource-integrity digests are not secrets.** Lockfile
  `"integrity": "sha512-…"` values are hashes of public tarballs; the
  model read pieces of the base64 as `secret` and masked them, about one
  per dependency. Spans lying entirely inside a `sha1|sha256|sha384|
  sha512-<base64>` token are dropped before dedupe (`src/public-digests.ts`);
  a span reaching past the digest is kept, and free-standing base64 is
  untouched. Developer content masked: 1.68% → 1.13%; tuning-set recall
  unchanged.

### Fixed

- **Overlapping spans no longer corrupt the restore round-trip.**
  Pre-existing in 0.3.0. `x https://github.com/users/john.doe@acme.com y`
  yielded `private_url[2,44]` and `private_email[27,46]` — IoU 0.39,
  below the dedupe threshold — so both survived and overwrote each other
  during vault substitution, and the email span ended past the end of
  the string: a 46-character input restored to 67. It is not only a
  constructed case: 1 of 926 documents in the A/B fingerprint corpus
  (`nullpii-bench` row 77, `private_person[23,30]` inside
  `private_email[25,41]`) hit it with real model output.
  `PiiVault.sanitize` now clamps spans to the text and merges any that
  share a character into their union, keeping the label and score of the
  highest-scoring member. The union is the fail-safe choice: no
  character an input span covered can reach the output. `spans` in the
  result is what was actually masked. The round-trip property test only
  ever generated disjoint spans, which is why this went unnoticed; it
  now also covers overlapping, nested, duplicated and out-of-range spans.

- **Dense text no longer hides words from the model.** Pre-existing in
  0.3.0. Windows are 140 words with a 30-word overlap, but the encoder
  also caps a window at 384 subwords, and on dense text (logs full of
  hashes, signed URLs and trace ids) a window was cut after a few dozen
  words. The next window started at a fixed stride, so everything
  between the cut and the next window never reached the model. On an
  access-log-shaped probe, 48.6% of words were never scanned and only
  30 of 81 owner names were fully masked; emails survived only because
  the regex pack caught them. Windows now advance by what the encoder
  actually kept (`forEachWindow` in `src/chunking.ts`), restarting 30
  words before the cut, so every word is scanned: 79 of 81 names fully
  masked on the same probe (the other two are partial model detections,
  not windowing). When no window is cut, the windows are exactly the old
  ones; on the A/B fingerprint corpus only the 2 documents with cut
  windows changed, and latency on Claude-Code-shaped input is unchanged
  within noise. `strictLength: true` still throws on any cut.

- **A low-confidence recognizer no longer goes silent on a partial
  model overlap.** Pre-existing in 0.3.0. Recognizers under 0.9
  confidence (IPv4/IPv6, domestic phones, some national IDs) deferred to
  any overlapping model span, so a short low-score model span on the
  first 4 characters of an IPv6 address silenced `core:ipv6-full` and
  left the other 35 in the clear. They now defer only when a model span
  covers the whole match; partial overlaps are resolved by the usual
  containment dedupe and the vault's union merge.

- **Empty input and over-long single words no longer crash `sanitize()`.**
  Pre-existing in 0.3.0, invisible to the mocked unit suite and to CI
  (the real-ONNX e2e job never runs). `sanitize('')` and whitespace-only
  input threw `Reshape node … /core/rnn/lstm/Reshape`, and so did any
  window whose only word exceeds the 384-subword budget (identifiers of
  hundreds of characters in minified bundles). A coding agent sees empty
  tool output constantly. A window with no word to classify now skips
  the model; the recognizer pack and the base64 detector still scan the
  whole text. Covered by a mocked test whose backend fails on zero words
  like the real one, and by two new real-ONNX e2e cases.

- **Boundary refine no longer trims punctuation off secrets.** It
  strips edge punctuation so `Mario Rossi,` masks as `Mario Rossi`, but
  on a secret that punctuation is part of the credential (`hunter2!`,
  `"P@ss;`) and was left unmasked. Secrets now lose only whitespace.

### Test plan

- 321 unit + integration tests passing (was 271 on v0.3.0); real-ONNX e2e 9/9.
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
