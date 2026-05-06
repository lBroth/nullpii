# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-06

First public release. Local PII sanitization with reversible vault.

### Added

- npm runtime ships the full router stack: **Google distiluse** sentence encoder + 5 per-domain LoRA adapters (devops / legal / medical / narrative / enterprise) merged into the GLiNER backbone (`urchade/gliner_multi_pii-v1`, **Microsoft mDeBERTa-v3** base + GLiNER head). Cosine-similarity routing with an enterprise-route gate (margin ≥ 0.10).
- Adversarial preprocessor (`_normalize_for_detection`): NFKC + unidecode + zero-width strip + HTML entity / URL `%XX` decode + spaced-PII despace. Span offsets remap back to the original text.
- Recognizer pack (~70 patterns): URL / email / AWS / GitHub / Stripe / OpenAI / Anthropic keys / IBAN / SSN / CPF / Italian Codice Fiscale / Bitcoin (base58check-validated) / etc.
- TypeScript validators: Luhn (credit cards), IBAN mod-97, CPF mod-11×2, Italian CF check letter, BIP-13 base58check.
- Per-PUA-codepoint placeholder escape (``) — round-trip safe.
- 8-class output: `private_person`, `private_email`, `private_phone`, `private_address`, `private_date`, `private_url`, `account_number`, `secret`.
- CLI: `nullpii sanitize`, `nullpii restore`, `nullpii scan` (`--ndjson` for batch detection).

### Bench (MacBook Pro · Apple M5 Pro · 48 GB · macOS 26.4 · CPU backend, 10-dataset canonical surface)

Macro F1, IoU ≥ 0.5 partial-match span scoring. **`nullpii` wins 9 of 10 datasets** vs 6 bare third-party baselines (Microsoft Presidio, NVIDIA Nemotron-PII, piiranha, Microsoft DeBERTa-v3, GLiNER ONNX FP32, `gliner-pii-large-v1`). Per-tool matrix at `packages/eval/published-bench/matrix.csv`.

- **Mixed F1 0.8054 (10 datasets)** vs next-best baseline `gliner-pii-large-v1` 0.5762 (+0.23).
- **Held-out OOD (4) — F1 0.7166.** Honest non-adversarial generalisation claim. `presidio-synthetic`, `ai4privacy-300k-heldout`, `isotonic-{en,de}-heldout`.
- **Adversarial preprocessor (3) — F1 0.9409.** ⚠ Self-authored — synthetic perturbations generated internally; lift comes from `_normalize_for_detection` targeting the perturbation classes we generated. Regression test for the preprocessor, not a generalisation claim. typo 0.89 / unicode 0.94 / code 1.00.
- **In-distribution diagnostic (3) — F1 0.7884.** Memorisation, not generalisation — adapters trained on slices. `nullpii-bench` 0.73 / `tab-echr` 0.92 / `nemotron-pii-test` 0.72.

### Latency (MacBook Pro · Apple M5 Pro · 48 GB · CPU backend, n=50/size)

| Input size | p50 | p95 | p99 |
|---|---:|---:|---:|
| 100 chars | 81 ms | 87 ms | 91 ms |
| 1 000 chars | 230 ms | 251 ms | 259 ms |
| 10 000 chars | 2.15 s | 2.25 s | 2.83 s |

### Model artifacts

- HuggingFace Hub: [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) (~6 GB FP32 — 5 merged-LoRA ONNX shards + distiluse encoder + tokenizer + prototypes JSON). First call to `sanitize()` downloads everything to `~/.cache/nullpii/`.
- Raw LoRA weights ([`lBroth/nullpii-adapters`](https://huggingface.co/lBroth/nullpii-adapters), ~17 MB) — upstream of the merged repo, used by the release pipeline.
- Apache 2.0 throughout. Built on `urchade/gliner_multi_pii-v1` (Zaratiana et al., NAACL 2024). Per-domain LoRA training data composition + recipe documented on the HF model card.

### Red-team disclosures

- 3 in-distribution bench rows disclosed (`nullpii-bench`, `tab-echr`, `nemotron-pii-test`) — adapters trained on slices of those datasets, F1 reported with ⚠ memorisation flag in the per-row table.
- `CLAIM-VERIFIER-01` documents that competitor F1 claims (Presidio 0.85+, piiranha 0.99) are not reproducible with standard methodology — see `packages/eval/scripts/verify_claims.py`.

### Honest framing

Night-hobby experiment, not a production-ready PII tool, not a research paper, not a commercial product. Interesting for the engineering rigor + adversarial preprocessor, not for being state-of-the-art on F1.
