# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [Unreleased] — v10 release-candidate (2026-05-04)

> Pre-release work in progress. Numbers and HuggingFace artifacts will land after the unified release bench completes. See [`docs/v10/V10_PLAN.md`](docs/v10/V10_PLAN.md) for gating criteria.

### Architecture

- **v10 LoRA-per-domain adapters** on `urchade/gliner_multi_pii-v1` (~278M base + 5 LoRA, ~3.4 MB each). Domains: `devops`, `legal`, `medical-experimental`, `narrative` (general), `enterprise` (Nemotron-aug).
- **Two release-candidate routers**:
  - `nullpii-v10-router-embedding`: distiluse multilingual sentence-transformer + 5 prototype vectors with cosine routing + enterprise gate (margin 0.10). ~430 MB total.
  - `nullpii-v10-router-xlmr`: xlm-roberta classifier head over 4 domains. ~1.4 GB total.
- **Adversarial preprocessor** at adapter input (`_normalize_for_detection`): NFKC + unidecode + zero-width strip + HTML entity decode + URL `%XX` decode + spaced-PII despace. Span offsets remap back to original text.
- 8-class output retained (`private_person`, `private_email`, `private_phone`, `private_address`, `private_date`, `private_url`, `account_number`, `secret`). LoRA training on 55-class Nemotron labels remapped 37→8 at inference.

### Eval

- `packages/eval/scripts/bench_full.py` purged to release surface: 2 nullpii routers + 9 bare baselines (`presidio`, `gliner-onnx-pii-fp32`, `piiranha`, `deberta`, `scrubadub`, `nemotron-pii-raw`, `openai`, `openai-bioes`, `openai-official`) + 3 opt-in cloud rows.
- Strict bare-mode contract: no competitor row wraps nullpii post-processing (`boundary_refined`, `never_pii_filter`, `url_filter`, `regex_pack`, chunking).
- 19-dataset PII-native canonical bench surface (see `docs/v10/V10_PLAN.md` "Release gating"). Excluded: wikiann (PER/LOC, not PII), adversarial-decoys (zero gold), composite nullpii-adversarial.
- New external baselines: `argilla-pii` (29→8 label map), `nemotron-pii-test` (Nvidia's own test split).
- `DatasetSpec.total_n` + `n / total_n` columns in `matrix.csv` for transparent cap visibility.

### Audit fixes (2026-05-04)

- F09: phone patterns context-anchored (`tel|telefono|phone|cell|cellulare|mobile` prefix) — drops CC/SSN false positives.
- F20: IDN email pattern reverted to ASCII-only after Unicode `\w` produced 336 FP / 500 matches on `nullpii-bench`.
- F10–F19: legal / medical / DE / IT recognizers added (Italian tax code MTTSRG41M22H501F → `account_number`, German legal vocab in router, Italian medical terms in router).
- See `docs/v10/AUDIT_2026-05-04.md` for the full report.

### Pending (release gating)

- 🔴 Unified release bench across 19 datasets × 11 tools.
- 🔴 README rewrite with v10 numbers post-bench.
- 🟡 HuggingFace push: `lBroth/nullpii-v10-router-{embedding,xlmr}` + `lBroth/nullpii-v10-{devops,legal,medical-experimental,narrative,enterprise}-lora`. Model card drafts in [`docs/v10/model-cards/`](docs/v10/model-cards/) (pre-bench placeholders).
- 🔴 Merged-LoRA ONNX export for npm shipping.

### Library (npm package)

- TypeScript ESM library (`nullpii` on npm) with `sanitize` / `restore` + reversible in-memory vault.
- Base model: [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (multilingual GLiNER, mDeBERTa-v3-base + GLiNER head, ~278M params). The npm runtime ships the GLiNER backbone via the `onnx-community/gliner_multi_pii-v1` ONNX export.
- Backends: `cpu`, `mps`, `cuda` (subpath exports, tree-shakable). Variants: `fp32`, `int4`, `auto` (default `int4`).
- CLI: `nullpii scan|sanitize|restore|models|prefetch|doctor|benchmark`.
- Recognizer packs: 74 patterns bundled in `src/defaults.ts` `DEFAULT_RECOGNIZERS` (parity with Python `DEFAULT_REGEX_PATTERNS`) plus per-recognizer validators (Luhn, IBAN-97, CPF mod-11, Italian Codice Fiscale, BTC base58check) wired via `Recognizer.validate`.
- npm runtime SHIPS the GLiNER base + recognizer pack + `_normalize_for_detection` preprocessor + `filterNeverPii` post-pass + reversible vault. The full v10 router stack (5 LoRA adapters + embedding/xlmr router) currently runs in the Python eval kit only; merged-LoRA ONNX export to wire the routers into the npm runtime is on the roadmap.

[Unreleased]: https://github.com/lBroth/nullpii/compare/HEAD...HEAD
