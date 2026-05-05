---
license: apache-2.0
language:
  - en
base_model: urchade/gliner_multi_pii-v1
library_name: peft
tags:
  - pii
  - lora
  - adapter
  - enterprise
  - us-formats
  - llm-safety
  - finance
  - insurance
pipeline_tag: token-classification
---

# nullpii v10 — `enterprise` adapter (LoRA, Nemotron-aug)

> Pre-release draft. See [`README.md`](README.md) for context and train-vs-eval overlap matrix.

## TL;DR

LoRA adapter (~3.4 MB safetensors) on `urchade/gliner_multi_pii-v1`. Specialised for US-business-shaped structured records: loan applications, insurance forms, employee records, healthcare-form-light, financial statements. Trained on `nvidia/Nemotron-PII` (10k rows) plus US-formats Faker synthesis.

## Intended use

- Structured US-business document redaction: forms, applications, records, filings.
- Coverage of US-specific patterns: SSN (`XXX-XX-XXXX`), NANP phone formats (`(XXX) XXX-XXXX`, `+1-XXX-XXX-XXXX`), ZIP+4, GPS coordinates, US street addresses.
- 55-class label-rich training (Nemotron schema) remapped to nullpii's 8-class for output. Granular training-time labels (`first_name`, `last_name`, `ssn`, `medical_record_number`, `health_plan_beneficiary_number`, `swift_bic`, `cvv`, etc.) give the encoder finer-grained representations.

## Out-of-scope

- **Non-US locale**: trained on US-only Nemotron-PII + Faker `en_US`. EU / UK / Asia format coverage handled by other adapters.
- **HIPAA Protected Health Information** as the sole control: see `medical-experimental` adapter card.
- **Conversational / dev-paste**: routing should select `narrative` or `devops`; this adapter under-performs on prose.

## Routing gate

The router (`nullpii-v10-router-embedding`) **gates** the enterprise route at margin ≥ 0.10 vs the runner-up. The enterprise prototype proved over-attractive on dev-paste in pre-bench validation (15% misroute rate without gate). The gate trades ~5% recall on enterprise-shaped inputs for routing stability across mixed workloads.

The xlm-roberta router does NOT include the enterprise route.

## Training data

| Source | Rows | License | Notes |
|---|---:|---|---|
| `nvidia/Nemotron-PII` train split | 10k | CC BY 4.0 | NeMo Data Designer, persona-grounded synthesis, 55 PII categories, 30 industries, US locale |
| `us-formats` (Faker `en_US` synth) | 5k | Apache 2.0 | US phone / SSN / ZIP / address / credit-card / GPS variants |

Total: ~15k records.

### ⚠️ Eval overlap with `nemotron-pii-test`

The v10 release bench includes `nemotron-pii-test` (Nvidia's own test split, 5k cap). This adapter was trained on the Nemotron train split (10k rows). **Performance on the Nemotron test split is in-distribution generalisation, not OOD.** We publish the number for transparency but treat it as a memorisation data-point.

The defensible enterprise OOD signal is `argilla-pii` (third-party, no overlap) and `nullpii-bench` enterprise-shaped subset (project-bundled, no overlap).

## Training procedure

LoRA r=16, alpha=32. BF16, AdamW. Trained with `use_expanded_prompts=True` at inference time — input prompt set is the 40+ semantic Nemotron labels rather than the 8 nullpii labels, with output remap to 8-class. See [`../TRAINING.md`](../TRAINING.md) for the full recipe.

Train loss: 10.06 → eval loss: 4.31 → 3.91 over 2 epochs.

## Evaluation

This LoRA adapter is loaded by the [`nullpii-v10-router-embedding`](router-embedding.md) and (where applicable) [`nullpii-v10-router-xlmr`](router-xlmr.md) routers — it is not intended to be used standalone. End-to-end F1 numbers are reported per-router on those cards. Aggregate macro F1 of the shipping pipeline (router-embedding) across 27 datasets: **0.7172**.

Per-domain isolated benchmarks (LoRA adapter alone, bypassing the router) are out-of-scope for the v10 release; they would require separate tool defs in `bench_full.py` and a re-run. Routing-aware evaluation (which dataset routes to which adapter) is the production-relevant signal and is what the router cards report.

Full bench artifacts: `packages/eval/results/bench-v10-release-local/matrix.{json,csv}`.


## Limitations

- **In-distribution memorisation on Nemotron test** — see Eval overlap callout.
- **US-only locale**.
- **Nemotron's 30 industries**: training data is industry-imbalanced. Under-represented industries (insurance, real estate, manufacturing) may have weaker recall.
- **Article 9 GDPR**: not represented.

## License

Apache 2.0. Compatible with Nemotron-PII CC BY 4.0 attribution; cite NVIDIA when redistributing weights derived from this adapter.

## Acknowledgements

- NVIDIA Nemotron-PII team for the synthetic dataset and persona-grounded synthesis methodology.
- Faker library for the US-formats supplementary corpus.
