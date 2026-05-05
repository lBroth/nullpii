# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-05

First public release. Local PII sanitization for LLM prompts with reversible vault.

### Added

- npm runtime ships the full router stack: **Google distiluse** sentence encoder + 5 per-domain LoRA adapters (devops / legal / medical / narrative / enterprise) merged into the GLiNER backbone (`urchade/gliner_multi_pii-v1`, **Microsoft mDeBERTa-v3** base + GLiNER head). Cosine-similarity routing with an enterprise-route gate (margin ≥ 0.10).
- Adversarial preprocessor (`_normalize_for_detection`): NFKC + unidecode + zero-width strip + HTML entity / URL `%XX` decode + spaced-PII despace. Span offsets remap back to the original text.
- Recognizer pack (~70 patterns): URL / email / AWS / GitHub / Stripe / OpenAI / Anthropic keys / IBAN / SSN / CPF / Italian Codice Fiscale / Bitcoin (base58check-validated) / etc.
- TypeScript validators: Luhn (credit cards), IBAN mod-97, CPF mod-11×2, Italian CF check letter, BIP-13 base58check.
- Per-PUA-codepoint placeholder escape (``) — round-trip safe.
- 8-class output: `private_person`, `private_email`, `private_phone`, `private_address`, `private_date`, `private_url`, `account_number`, `secret`.
- CLI: `nullpii sanitize`, `nullpii restore`, `nullpii scan` (interactive + `--ndjson` long-running daemon for benchmarking).

### Bench (Mac CPU local)

- 27-dataset macro F1: **0.7172** (`packages/eval/published-bench/matrix.{json,csv}`).
- Honest held-out (non-adversarial) F1: **0.7008** — strips 9 leak-disclosed in-distribution rows.
- Adversarial preprocessor lift: typo 0.94 / unicode 0.94 / code 1.00 / encoding 0.12 (documented gap).
- Tool surface — third-party baselines wired but pending GPU pass: **Microsoft Presidio**, **NVIDIA Nemotron-PII**, `iiiorg/piiranha`, **Microsoft DeBERTa**-v3 community fine-tune, scrubadub, GLiNER family (`gliner-onnx-pii-fp32`, `gliner-x-*`, `gliner-pii-*`, `gliner2-*`, `modern-gliner-bi`, `gliner-multi-pii-domains`), **OpenAI** `openai/privacy-filter` in three usage modes (naive HF / BIOES / opf-Viterbi).

### Model artifacts

- HuggingFace Hub: [`lBroth/nullpii-v10-router-embedding`](https://huggingface.co/lBroth/nullpii-v10-router-embedding) (~6 GB FP32 — 5 merged-LoRA ONNX shards + distiluse encoder + tokenizer + prototypes JSON). First call to `sanitize()` downloads everything to `~/.cache/nullpii/`.
- Raw LoRA weights ([`lBroth/nullpii-v10-adapters`](https://huggingface.co/lBroth/nullpii-v10-adapters), ~17 MB) — upstream of the merged repo, used by the release pipeline.
- Apache 2.0 throughout. Built on `urchade/gliner_multi_pii-v1` (Zaratiana et al., NAACL 2024). Per-domain LoRA fine-tunes on `ai4privacy/pii-masking-300k`, `Isotonic/pii-masking-200k`, **NVIDIA Nemotron-PII**, TAB ECHR (Pilán et al., ACL 2022), MEDDOCAN (IBERLEF 2019).

### Audit transparency

- 25 source-level findings F01–F25 closed (regex hardening, input caps, validators, never-PII filter, adversarial preprocessor). See [`docs/v10/AUDIT_2026-05-04.md`](docs/v10/AUDIT_2026-05-04.md).
- Red-team review documented at `packages/eval/private/v10/RED_TEAM_AUDIT_2026-05-05.md` (internal). Disclosures in README + COMPETITIVE_ANALYSIS for `TUNE-ENTGATE-01` (gate margin tuned on `nullpii-bench`) + `LEAK-NEMO-ENTERPRISE-01` (enterprise adapter trained on Nemotron train split, `nemotron-pii-test` is in-distribution generalisation, not OOD).
- `CLAIM-VERIFIER-01` documents that competitor F1 claims (Presidio 0.85+, piiranha 0.99) are not reproducible with standard methodology — see `packages/eval/scripts/verify_claims.py`.

### Honest framing

This is a night-hobby experiment, not a production-ready PII tool, not a research paper, not a commercial product. For real GDPR-grade PII redaction use **Microsoft Presidio**. nullpii is interesting for the engineering rigor + audit transparency + adversarial preprocessor, not for being state-of-the-art on F1.

## [Pre-0.1.0] — v10 release-candidate (2026-05-04, internal)

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
