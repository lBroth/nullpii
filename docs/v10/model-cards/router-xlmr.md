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

> **Status (2026-05-05)**: **alternative** to the default `router-embedding`. Per release gating, NOT the shipping pipeline — F1 aggregate within ±0.02 of the embedding router, but storage cost is 3.3× (1.4 GB vs 430 MB). Available for users who specifically need xlmr's strong wins on real-PII structured datasets (ai4privacy, isotonic, oasst-dev-planted, tab-echr).

## TL;DR

Same v10 LoRA backbone as [`router-embedding`](router-embedding.md), but routing is performed by a fine-tuned `xlm-roberta-base` 4-way classifier head instead of cosine similarity to prototype vectors. Higher-precision routing on classes that share lexical surface (e.g. legal-flavoured medical text, dev-paste with prose). **Higher storage cost** (~1.4 GB total vs ~430 MB for the embedding router).

| Property | Value |
|---|---|
| Base model | `urchade/gliner_multi_pii-v1` (mDeBERTa-v3-base + GLiNER head, ~278M params) |
| Router classifier | `FacebookAI/xlm-roberta-base` 4-way fine-tune (~1.1 GB) |
| Adapters | 4 LoRA (devops, legal, medical-experimental, narrative) — **`enterprise` route NOT included** |
| Output schema | 8-class (same as embedding router) |
| Languages | en, de, fr, es, it (LoRA + xlm-roberta covers 100+) |
| Latency (CPU) | Mac M-series, default caps; 5090 GPU p50/p95 pass pending |
| Macro F1 aggregate | **0.7076** across 27 head-to-head datasets |

## Difference from `router-embedding`

| Aspect | embedding router | xlmr router |
|---|---|---|
| Routing mechanism | distiluse cosine similarity to 5 prototypes | xlm-roberta classifier head, 4-way softmax |
| Storage | ~430 MB | ~1.4 GB |
| `enterprise` adapter | included (gated, margin 0.10) | **not used** |
| Discrimination on lexically-similar classes | weak (prototype overlap) | strong (discriminative training) |
| F1 on `nullpii-bench` (unified release bench) | **0.7280** | 0.6096 |
| F1 macro aggregate (27 datasets) | **0.7172** | 0.7076 |
| Wins (head-to-head, 27 datasets) | 4 | **21** |

When to choose which:
- **embedding router**: storage-constrained deployments, multilingual breadth (50+ via embedder), enterprise-shaped US-business workloads.
- **xlmr router**: high-F1 priority on real-PII benches (ai4privacy, presidio-synthetic, oasst-dev-planted), where xlmr's discriminative routing wins ≥0.05 over the embedding router (early bench shows xlmr +0.08 on oasst-dev-planted, +0.02 on ai4privacy).

## Intended use / Out-of-scope use / Limitations

Identical to [`router-embedding`](router-embedding.md). Same base + adapters + 8-class schema + Article 9 invisibility + CJK / RTL / Indic blind spot.

## Training data composition

- **Adapters**: same 4 LoRA training corpora as the embedding router (devops / legal / medical-experimental / narrative). Enterprise adapter is NOT loaded by this router.
- **Classifier head** (xlm-roberta 4-way): training set is the union of the 4 per-domain training corpora, labelled by source-corpus origin. Class-balanced sampling, BF16 cosine LR, 3 epochs.

See [`router-embedding.md`](router-embedding.md) and [`README.md`](README.md) for full per-adapter dataset breakdown and train-vs-eval overlap matrix.

## Evaluation

Mac M-series CPU, single seed, macro F1 IoU ≥ 0.5. Same 27-dataset surface as the embedding router.

### Per-dataset F1

| Dataset | F1 | Δ vs distiluse |
|---|:---:|:---:|
| `nullpii-bench` | 0.6096 | −0.118 |
| `tab-echr` | **0.9217** | +0.036 |
| `oasst-dev-planted` | **0.5744** | +0.082 |
| `presidio-synthetic` | 0.7073 | +0.017 |
| `argilla-pii` | 0.6105 | +0.010 |
| `nemotron-pii-test` | 0.5934 | −0.167 |
| `ai4privacy-300k` | **0.6137** | +0.080 |
| `ai4privacy-300k-heldout-v10` | 0.5296 | +0.001 |
| `ai4privacy-400k` | 0.5633 | +0.008 |
| `isotonic-en` / `de` / `fr` / `it` | 0.8879 / 0.8855 / 0.8779 / 0.8783 | +0.010 / +0.011 / +0.018 / +0.014 |
| `isotonic-en-heldout-v10` / `de-heldout` / `fr-heldout` | 0.8813 / 0.8843 / 0.8765 | +0.014 / +0.010 / +0.015 |
| `adversarial-typo` | 0.7163 | −0.224 |
| `adversarial-unicode` | 0.7162 | −0.220 |
| `adversarial-whitespace` | **0.5185** | +0.125 |
| `adversarial-encoding` | 0.1216 | tied |
| `adversarial-code` | 1.0000 | tied |
| `adversarial-textattack` | 0.6928 | +0.003 |
| `textattack-{homo,swap,delete,insert,sub}` | 0.66 / 0.72 / 0.72 / 0.66 / 0.66 | tied to +0.005 |

**Aggregate**: macro F1 = **0.7076** across 27 datasets. Wins 21/27 with smaller margins; loses 4 with larger ones (nullpii-bench, nemotron-pii-test, adversarial-typo, adversarial-unicode).

Full bench artifacts: `packages/eval/results/bench-v10-release-local/matrix.{json,csv}`.

## How to use

Reference implementation: `packages/eval/scripts/bench_full.py` tool def `nullpii-v10-router-xlmr`. Same merged-LoRA ONNX export blocker for npm shipping as embedding router.

## Citation

> nullpii contributors (2026). *nullpii v10 — Router (xlm-roberta classifier head, high-F1 alt).* https://huggingface.co/lBroth/nullpii-v10-router-xlmr
