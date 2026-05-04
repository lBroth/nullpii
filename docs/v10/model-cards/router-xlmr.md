---
license: apache-2.0
language:
  - en
  - de
  - fr
  - es
  - it
  - multilingual
base_model:
  - urchade/gliner_multi_pii-v1
  - FacebookAI/xlm-roberta-base
library_name: gliner
tags:
  - pii
  - privacy
  - ner
  - lora
  - router
  - llm-safety
  - gdpr
  - pii-redaction
  - multilingual
pipeline_tag: token-classification
---

# nullpii v10 — Router (xlm-roberta classifier, high-F1 alt)

> **Status**: release-candidate (RC). Numerical evaluation cells are placeholders (`TBD-BENCH`) pending the unified release bench. See [draft index](README.md) for context.

## TL;DR

Same v10 LoRA backbone as [`router-embedding`](router-embedding.md), but routing is performed by a fine-tuned `xlm-roberta-base` 4-way classifier head instead of cosine similarity to prototype vectors. Higher-precision routing on classes that share lexical surface (e.g. legal-flavoured medical text, dev-paste with prose). **Higher storage cost** (~1.4 GB total vs ~430 MB for the embedding router).

| Property | Value |
|---|---|
| Base model | `urchade/gliner_multi_pii-v1` (mDeBERTa-v3-base + GLiNER head, ~278M params) |
| Router classifier | `FacebookAI/xlm-roberta-base` 4-way fine-tune (~1.1 GB) |
| Adapters | 4 LoRA (devops, legal, medical-experimental, narrative) — **`enterprise` route NOT included** |
| Output schema | 8-class (same as embedding router) |
| Languages | en, de, fr, es, it (LoRA + xlm-roberta covers 100+) |
| Latency (CPU) | TBD-BENCH |

## Difference from `router-embedding`

| Aspect | embedding router | xlmr router |
|---|---|---|
| Routing mechanism | distiluse cosine similarity to 5 prototypes | xlm-roberta classifier head, 4-way softmax |
| Storage | ~430 MB | ~1.4 GB |
| `enterprise` adapter | included (gated, margin 0.10) | **not used** |
| Discrimination on lexically-similar classes | weak (prototype overlap) | strong (discriminative training) |
| F1 on `nullpii-bench` (early bench, pre-audit) | 0.726 | 0.610 |
| F1 on PII-native multilingual avg | 0.625 | 0.615 |

When to choose which:
- **embedding router**: storage-constrained deployments, multilingual breadth (50+ via embedder), enterprise-shaped US-business workloads.
- **xlmr router**: high-F1 priority on real-PII benches (ai4privacy, presidio-synthetic, oasst-dev-planted), where xlmr's discriminative routing wins ≥0.05 over the embedding router (early bench shows xlmr +0.08 on oasst-dev-planted, +0.02 on ai4privacy).

## Intended use / Out-of-scope use / Limitations

Identical to [`router-embedding`](router-embedding.md). Same base + adapters + 8-class schema + Article 9 invisibility + CJK / RTL / Indic blind spot.

## Training data composition

- **Adapters**: same 4 LoRA training corpora as the embedding router (devops / legal / medical-experimental / narrative). Enterprise adapter is NOT loaded by this router.
- **Classifier head** (xlm-roberta 4-way): training set is the union of the 4 per-domain training corpora, labelled by source-corpus origin. Class-balanced sampling, BF16 cosine LR, 3 epochs.

See [`router-embedding.md`](router-embedding.md) and [`README.md`](README.md) for full per-adapter dataset breakdown and train-vs-eval overlap matrix.

## Evaluation (TBD-BENCH)

Same methodology as embedding router. Numbers fill post-unified-bench.

## How to use

Reference implementation: `packages/eval/scripts/bench_full.py` tool def `nullpii-v10-router-xlmr`. Same merged-LoRA ONNX export blocker for npm shipping as embedding router.

## Citation

> nullpii contributors (2026). *nullpii v10 — Router (xlm-roberta classifier head, high-F1 alt).* https://huggingface.co/lBroth/nullpii-v10-router-xlmr
