---
license: apache-2.0
language:
  - es
  - en
base_model: urchade/gliner_multi_pii-v1
library_name: peft
tags:
  - pii
  - lora
  - adapter
  - medical
  - phi
  - experimental
  - llm-safety
pipeline_tag: token-classification
---

# nullpii v10 — `medical` adapter (LoRA)

> ⚠️ **EXPERIMENTAL — NOT FOR HIPAA / PRODUCTION HEALTHCARE USE** ⚠️
>
> The `-experimental` suffix is intentional and load-bearing. This adapter has NOT been validated against the i2b2 2014 deidentification challenge (DUA application pending at `portal.dbmi.hms.harvard.edu`) or against MEDDOCAN at the levels required for a HIPAA Safe Harbor / GDPR Art. 9 compliance claim. Do not deploy this adapter as the sole control over Protected Health Information (PHI) until those validations land.
>
> This restriction is reiterated in the runtime: selecting the `medical` profile in the nullpii CLI emits a startup warning identifying the non-validation status.

## TL;DR

LoRA adapter (~3.4 MB safetensors) on `urchade/gliner_multi_pii-v1`. Trained on Spanish + English clinical text. **Experimental status** until i2b2 + MEDDOCAN benchmark validation completes.

## Intended use

- **Permitted**: research, internal red-teaming, academic comparison studies, non-production sanitisation pipelines for synthetic medical text.
- **Permitted-with-caveat**: dual-redaction pipelines where this adapter is one of multiple controls and the final output is human-reviewed before LLM submission.

## Out-of-scope (HARD)

- HIPAA Safe Harbor 18-identifier redaction (45 CFR 164.514(b)(2)).
- HIPAA Limited Data Set redaction (45 CFR 164.514(e)).
- GDPR Art. 9 special categories (health) sole-control redaction.
- US / EU / UK regulated healthcare LLM workloads as the only PHI safeguard.

Use the future `medical` adapter (suffix to be removed after validation) for those workloads.

## Why "experimental"

| Validation | Status |
|---|---|
| MEDDOCAN test split bench | 🟡 In scope, not yet executed |
| i2b2 2014 deidentification challenge | 🔴 DUA approval pending |
| Per-class precision/recall on PHI-18 categories | 🔴 Not measured |
| Cross-locale validation (en clinical) | 🔴 Training is Spanish-heavy; en clinical not validated |
| HIPAA Safe Harbor 18 identifier coverage map | 🔴 Not produced |

The `medical` (non-experimental) variant ships once all five rows turn green.

## Training data

| Source | Rows | License | Notes |
|---|---:|---|---|
| MEDDOCAN train (`GuiGel/meddocan`) | 10k | CC BY 4.0 | Spanish clinical text, IBERLEF 2019 |
| `ai4privacy/pii-masking-300k` medical filter | 5k | CC BY 4.0 | English clinical-flavoured templates |
| Common Crawl medical-filtered | ~700 | ODC-BY | Clinical vocabulary filter |

Total: ~16k records.

**MEDDOCAN test split is held out** from this training and is scoped as a future bench addition.

## Training procedure

LoRA r=16, alpha=32, target `q_proj`/`k_proj`/`v_proj` of the inner mDeBERTa encoder. AdamW, BF16, 1e-4 cosine schedule, 100-step warmup, batch 8 (effective ×2 via grad accumulation), max-len 384, 2-4 epochs early-stopped. Single 5090 (32 GB), ~50-150 min per adapter.

## Evaluation

This LoRA adapter is loaded by the [`nullpii-v10-router-embedding`](router-embedding.md) shipping router — it is not intended to be used standalone. End-to-end F1 numbers are reported on that card. Aggregate macro F1 of the shipping pipeline (router-embedding) across 27 datasets: **0.7172**.

Per-domain isolated benchmarks (LoRA adapter alone, bypassing the router) are out-of-scope for the v10 release; they would require separate tool defs in `bench_full.py` and a re-run. Routing-aware evaluation (which dataset routes to which adapter) is the production-relevant signal and is what the router cards report.

Full bench artifacts: `packages/eval/published-bench/matrix.{json,csv}`.


## Limitations

- See Out-of-scope (HARD).
- Training corpus is Spanish-dominant; English clinical performance is structurally weaker.
- No multilingual clinical coverage beyond es / en (no de / fr / it / zh / ja clinical training data).

## License

Apache 2.0. Compatible with MEDDOCAN CC BY 4.0 attribution; cite IBERLEF 2019 organizers when redistributing weights.
