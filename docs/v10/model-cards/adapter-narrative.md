---
license: apache-2.0
language:
  - en
  - de
  - fr
  - it
  - es
base_model: urchade/gliner_multi_pii-v1
library_name: peft
tags:
  - pii
  - lora
  - adapter
  - narrative
  - multilingual
  - llm-safety
pipeline_tag: token-classification
---

# nullpii v10 — `narrative` adapter (LoRA)

> Pre-release draft. See [`README.md`](README.md) for context and train-vs-eval overlap matrix.

## TL;DR

LoRA adapter (~3.4 MB safetensors) on `urchade/gliner_multi_pii-v1`. Specialised for prose / narrative text in 5 languages (en / de / fr / it / es). Used as the **router fallback** when no domain-specialised adapter wins the routing decision.

## Intended use

- General-purpose multilingual PII redaction in chat, email, support tickets, CRM notes, customer interactions.
- Router fallback: invoked by `nullpii-v10-router-{embedding,xlmr}` when no specialised adapter (devops / legal / medical-experimental / enterprise) matches.

## Out-of-scope

- Domain-specific document redaction → use the matching specialised adapter.
- Long structured forms → use `enterprise`.
- Clinical text → use `medical-experimental` (with its caveats).

## Training data

| Source | Rows | License | Notes |
|---|---:|---|---|
| `ai4privacy/pii-masking-300k` rows balanced subset | ~6k | CC BY 4.0 | Multi-locale, multi-class balanced |
| `Isotonic/pii-masking-200k` en/de/fr | ~7k | Apache 2.0 | Multilingual |
| `cc-negative` filtered | ~3k | ODC-BY (Common Crawl) | Negative class |

Total: ~17k records.

**v2 experimental variant** (`narrative-v2-experimental`, see `packages/eval/results/train/v10/adapters/narrative-v2-experimental/`) was an attempted dev-paste injection. Returned mixed results (+0.03 nullpii-bench, near-tied isotonic) and not adopted as v1 default. Documented for reference; not the production adapter.

## Training procedure

Same recipe as other v10 LoRA adapters. Train loss 4.72 → eval loss 3.49 → 3.12. See [`../TRAINING.md`](../TRAINING.md).

## Evaluation

This LoRA adapter is loaded by the [`nullpii-v10-router-embedding`](router-embedding.md) and (where applicable) [`nullpii-v10-router-xlmr`](router-xlmr.md) routers — it is not intended to be used standalone. End-to-end F1 numbers are reported per-router on those cards. Aggregate macro F1 of the shipping pipeline (router-embedding) across 27 datasets: **0.7172**.

Per-domain isolated benchmarks (LoRA adapter alone, bypassing the router) are out-of-scope for the v10 release; they would require separate tool defs in `bench_full.py` and a re-run. Routing-aware evaluation (which dataset routes to which adapter) is the production-relevant signal and is what the router cards report.

Full bench artifacts: `packages/eval/results/bench-v10-release-local/matrix.{json,csv}`.


## Limitations

- **No CJK / RTL / Indic training data**: same blind spot as the rest of v10.
- **Common Crawl negative class is regex-filtered**, not human-curated.
- **Article 9 GDPR**: not represented in the 8-class schema.

## License

Apache 2.0.
