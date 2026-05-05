# Changelog

Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
Versioning: [SemVer](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-05-05

First public release. Local PII sanitization with reversible vault.

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
- Tool surface — bare-mode third-party baselines (no nullpii post-processing leak): **Microsoft Presidio**, **NVIDIA Nemotron-PII**, `iiiorg/piiranha`, **Microsoft DeBERTa**-v3 community fine-tune, GLiNER ONNX FP32 (`gliner-onnx-pii-fp32`), `gliner-pii-large-v1`. Per-tool numbers in `packages/eval/published-bench/matrix.csv`.

### Model artifacts

- HuggingFace Hub: [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) (~6 GB FP32 — 5 merged-LoRA ONNX shards + distiluse encoder + tokenizer + prototypes JSON). First call to `sanitize()` downloads everything to `~/.cache/nullpii/`.
- Raw LoRA weights ([`lBroth/nullpii-adapters`](https://huggingface.co/lBroth/nullpii-adapters), ~17 MB) — upstream of the merged repo, used by the release pipeline.
- Apache 2.0 throughout. Built on `urchade/gliner_multi_pii-v1` (Zaratiana et al., NAACL 2024). Per-domain LoRA training data composition + recipe documented on the HF model card.

### Red-team disclosures

- 3 in-distribution bench rows disclosed (`nullpii-bench`, `tab-echr`, `nemotron-pii-test`) — adapters trained on slices of those datasets, F1 reported with ⚠ memorisation flag in the per-row table.
- `CLAIM-VERIFIER-01` documents that competitor F1 claims (Presidio 0.85+, piiranha 0.99) are not reproducible with standard methodology — see `packages/eval/scripts/verify_claims.py`.

### Honest framing

Night-hobby experiment, not a production-ready PII tool, not a research paper, not a commercial product. Interesting for the engineering rigor + adversarial preprocessor, not for being state-of-the-art on F1.
