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

### Red-team disclosures

- `TUNE-ENTGATE-01` (enterprise gate margin tuned on `nullpii-bench`) + `LEAK-NEMO-ENTERPRISE-01` (enterprise adapter trained on Nemotron train split, `nemotron-pii-test` is in-distribution generalisation, not OOD) — disclosed in README + COMPETITIVE_ANALYSIS.
- `CLAIM-VERIFIER-01` documents that competitor F1 claims (Presidio 0.85+, piiranha 0.99) are not reproducible with standard methodology — see `packages/eval/scripts/verify_claims.py`.

### Honest framing

This is a night-hobby experiment, not a production-ready PII tool, not a research paper, not a commercial product. For real GDPR-grade PII redaction use **Microsoft Presidio**. nullpii is interesting for the engineering rigor + adversarial preprocessor, not for being state-of-the-art on F1.
