---
license: apache-2.0
language:
  - en
  - de
  - fr
  - it
base_model: urchade/gliner_multi_pii-v1
library_name: peft
tags:
  - pii
  - lora
  - adapter
  - devops
  - secrets
  - llm-safety
pipeline_tag: token-classification
---

# nullpii v10 — `devops` adapter (LoRA)

> Pre-release draft. See [`README.md`](README.md) for context and train-vs-eval overlap matrix.

## TL;DR

LoRA adapter (~3.4 MB safetensors) on `urchade/gliner_multi_pii-v1`. Specialised for developer-paste workloads: code snippets, RFC bodies, PR descriptions, ticket comments — text where the dominant PII risk is leaked secrets (API keys, tokens, DB connection strings) alongside conventional names / emails / phones.

## Intended use

- Developer-tool PII redaction: IDE inline LLM, code review assistant, ticket / PR / chat ingestion.
- Pair with `nullpii` regex pack (cloud keys, GitHub PAT, AWS access keys, etc.) for production secret coverage. The LoRA captures conventional PII; the regex pack provides high-precision secret-pattern detection.

## Out-of-scope

- Healthcare / legal / financial document redaction → use `medical-experimental` / `legal` / `enterprise` adapters.
- Long structured forms (loan apps, medical records) → use `enterprise`.

## Training data

| Source | Rows | License | Notes |
|---|---:|---|---|
| `dev-paste-synth` (internal Faker-based) | ~20k | Apache 2.0 | Code-style, secret patterns, PR / ticket templates |
| `ai4privacy/pii-masking-300k` rows 0–5k | 5k | CC BY 4.0 | Narrative-leaning subset |
| `Isotonic/pii-masking-200k` en/de/fr/it 0–5k | 5k | Apache 2.0 | Multilingual |
| `cc-negative` filtered | ~7k | ODC-BY (Common Crawl) | Negative class — text without PII |

Total: ~37k records.

## Training procedure

LoRA r=16, alpha=32, target_modules `q_proj` `k_proj` `v_proj` (mDeBERTa inner encoder). 0.3% trainable (~884k params). BF16 cosine LR, AdamW, weight decay 0.01, 2 epochs early-stopped on eval loss. Trained on a 5090 in ~150 minutes (largest of the 5 corpora).

See [`../V10_JOURNAL.md`](../V10_JOURNAL.md) for the full training trace.

## Evaluation (TBD-BENCH)

Numerical cells fill post-unified-bench.

## Limitations

- **Common Crawl negative class is regex-filtered**, not human-curated. Some residual PII may leak through. Mitigation: `never_pii_filter` post-pass strips RFC1918 IPs, NANP fictional 555-01XX phones, RFC 6761 reserved domains.
- **Adversarial perturbations**: TextAttack homoglyph / charswap / etc. degrade F1 by 0.05–0.15 vs clean inputs.
- **Article 9 GDPR**: no representation. See router model cards.

## License

Apache 2.0.
