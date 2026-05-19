# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.3.0] — first public release

Initial Apache-2.0 public release of `nullpii` (npm) + `@nullpii/gateway`.

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
- Multi-arch Docker (`linux/amd64`, `linux/arm64`).
- Claude Code quickstart in `examples/claude-code/`.

### Bench harness

- 16-dataset matrix (`packages/eval/`). Public competitors: Piiranha,
  DeBERTa-PII, GLiNER native (ONNX FP32 + `gliner-pii-large-v1`),
  Nemotron-PII, OpenAI privacy-filter, Presidio, AWS Comprehend,
  GCP DLP, Azure PII. Bench uses 12-class macro-F1 with sklearn-standard
  zero-support exclusion — symmetric across every tool.
- Independent gold rule for `nullpii-bench`: re-annotation scripts use
  regex-only (no `nullpii` import), so the gold is not biased toward
  the system under test.

### Security

- Detection fully local; no network socket after the first model
  download (HF Hub only — air-gappable via `modelDir` /
  `NULLPII_MODEL_DIR`).
- Vault never serialised. Debug logs carry counts + short ids only.
