---
license: apache-2.0
language:
  - en
  - de
  - fr
base_model: urchade/gliner_multi_pii-v1
library_name: peft
tags:
  - pii
  - lora
  - adapter
  - legal
  - llm-safety
  - gdpr
pipeline_tag: token-classification
---

# nullpii v10 — `legal` adapter (LoRA)

> Pre-release draft. See [`README.md`](README.md) for context and train-vs-eval overlap matrix.

## TL;DR

LoRA adapter (~3.4 MB safetensors) on `urchade/gliner_multi_pii-v1`. Specialised for legal-text PII: court rulings, contracts, regulatory filings, depositions. Heavy on PERSON / DATETIME / LOC categories with structural patterns ("Article X", "the Court", "Defendant", etc.).

## Intended use

- Pre-LLM redaction of legal documents in compliance, e-discovery, contract analysis, legal research workflows.
- Locale: trained on EU jurisprudence (TAB ECHR — European Court of Human Rights). Strongest on en / de / fr.

## Out-of-scope

- US / common-law jurisdictions: not validated. EU-civil-law structural patterns dominate the training corpus.
- Asian / non-EU jurisdictions: untrained.
- Statutory text (laws / regulations): the training corpus is case-law-heavy; statute language differs structurally.

## Training data

| Source | Rows | License | Notes |
|---|---:|---|---|
| TAB ECHR train (chunked ≤200 tok) | 5k | CC BY 4.0 | ACL 2022 Pilán et al. — third-party legal-PII gold standard |
| `ai4privacy/pii-masking-300k` rows 0–5k | 5k | CC BY 4.0 | Structured PII templates |
| Common Crawl legal-filtered | ~8k | ODC-BY | Filtered by legal vocabulary (`the Court`, `Article`, `Defendant`) |

Total: ~18k records.

**Eval overlap caveat**: TAB ECHR test split is in the v10 release bench (`tab-echr` row). The train and test splits are disjoint, but performance on `tab-echr` is therefore in-distribution generalisation, not OOD. Third-party legal corpora (HUDOC, EDGAR-redacted) are scoped for v11 to disprove TAB-only memorisation.

## Training procedure

LoRA r=16, alpha=32. BF16, AdamW, 2 epochs early-stopped. Common training recipe for v10 adapters; see [`../TRAINING.md`](../TRAINING.md).

## Evaluation

This LoRA adapter is loaded by the [`nullpii-v10-router-embedding`](router-embedding.md) and (where applicable) [`nullpii-v10-router-xlmr`](router-xlmr.md) routers — it is not intended to be used standalone. End-to-end F1 numbers are reported per-router on those cards. Aggregate macro F1 of the shipping pipeline (router-embedding) across 27 datasets: **0.7172**.

Per-domain isolated benchmarks (LoRA adapter alone, bypassing the router) are out-of-scope for the v10 release; they would require separate tool defs in `bench_full.py` and a re-run. Routing-aware evaluation (which dataset routes to which adapter) is the production-relevant signal and is what the router cards report.

Full bench artifacts: `packages/eval/results/bench-v10-release-local/matrix.{json,csv}`.


## Limitations

- **TAB-only memorisation risk** — see Eval overlap caveat. Third-party legal benches needed.
- **No US case-law training** — common-law caption / cite formats not represented.
- **Article 9 GDPR**: legal text often references medical / political / criminal-record content as factual elements. The 8-class schema does not flag these as Art. 9 sensitive — false-negative rate on Art. 9 categorical content is structurally 100%.

## License

Apache 2.0. Compatible with TAB CC BY 4.0 attribution requirement; cite Pilán et al. (ACL 2022) when redistributing TAB-derived weights.
