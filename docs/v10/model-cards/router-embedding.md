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
  - sentence-transformers/distiluse-base-multilingual-cased-v2
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

# nullpii v10 — Router (embedding-based, default release-candidate)

> **Status (2026-05-05)**: **shipping pipeline**. Unified release bench complete on Mac CPU (`packages/eval/published-bench/`). Mixed F1 0.7172 across 27 datasets; honest held-out (non-adversarial) F1 0.7008. The xlmr alt router has been moved out of public scope to `packages/eval/private/v10/large-candidate/` for a possible v0.2 "large" variant.

## TL;DR

Multilingual PII detection pipeline. A **Google distiluse** sentence-transformer (`sentence-transformers/distiluse-base-multilingual-cased-v2`, ~135 MB, 50+ languages) routes each input to one of five domain-specialised LoRA adapters layered on the GLiNER backbone `urchade/gliner_multi_pii-v1` (**Microsoft mDeBERTa-v3** base + GLiNER head, ~278 MB, 50+ languages). Outputs span-level PII annotations across 8 categories. Total artifact size: **~430 MB** (base + embedder + 5 LoRA adapters).

| Property | Value |
|---|---|
| Base model | `urchade/gliner_multi_pii-v1` (GLiNER head over **Microsoft mDeBERTa-v3** base, ~278M params) |
| Router embedder | **Google distiluse** `sentence-transformers/distiluse-base-multilingual-cased-v2` (~135 MB) |
| Adapters | 5 LoRA (devops, legal, medical, narrative, enterprise), ~3.4 MB each |
| Output schema | 8-class span: `private_person`, `private_email`, `private_phone`, `private_address`, `private_date`, `private_url`, `account_number`, `secret` |
| Languages (training) | en, de, fr, es, it (LoRA fine-tunes); 50+ via embedder routing |
| Latency (CPU) | Mac M-series, default caps, 27 datasets benched in ~1.5h wall total. Per-dataset throughput ranges 4–18 samp/s; 5090 GPU pass pending for p50/p95 publication |
| Macro F1 aggregate | **0.7172** across 27 head-to-head datasets |

## Intended use

- **Primary**: pre-LLM PII redaction in conversational, document, or developer-paste workloads. The library produces reversible placeholders that downstream LLMs see; original values are restored on the returned text via an in-memory vault.
- **Secondary**: standalone PII span tagger for offline batch redaction.
- **Geographic scope**: trained primarily on EU + Romance-language datasets (ai4privacy, Isotonic, TAB ECHR, MEDDOCAN). US-format coverage added via Nvidia Nemotron-PII augmentation in the `enterprise` route.

## Out-of-scope use

- **HIPAA-grade Protected Health Information (PHI) redaction** — the `medical` route is non-validated. Use only after i2b2 / MEDDOCAN benchmark validation completes (see [model card](adapter-medical.md) for status).
- **Article 9 GDPR special categories** (health, biometric, genetic, religious, political opinion, trade union membership, sexual orientation) — the 8-class schema does not represent these as distinct categories. False-negative rate on Art. 9 categorical content is structurally 100% by design. Do not rely on this model as the sole control for Art. 9 minimisation; pair with a categorical content classifier or an upstream filter.
- **Japanese / Chinese / Korean / Arabic / Hindi**: zero training data. Detection on CJK / RTL / Indic scripts is unreliable.
- **Air-gapped first-run installs**: model weights download from the HuggingFace Hub on first use. Plan an offline mirror for air-gapped deployments.

## How it works (routing)

1. Input text → distiluse embedder → 512-dim sentence embedding.
2. Cosine-similarity scored against 5 per-domain prototype vectors (one per LoRA adapter, computed as the mean training-corpus embedding for that domain).
3. Highest-similarity domain is selected — except for `enterprise`, which is **gated** (margin ≥ 0.10 vs runner-up required to win); without the margin, fallback is the runner-up. Rationale: the `enterprise` prototype proved over-attractive on dev-paste in pre-bench validation; the gate trades ~5% recall on enterprise-shaped inputs for routing stability.
4. Selected adapter (LoRA-merged on top of the GLiNER base) emits span predictions.

If routing fails or no adapter loads, fallback is the `narrative` adapter.

## Training data composition (per route)

| Route | Datasets | Size | License |
|---|---|---:|---|
| `devops` | dev-paste-synth (Faker-based, internal) + ai4privacy 0–5k + isotonic en/de/fr/it 0–5k | ~37k | Apache 2.0 (synth) / CC BY 4.0 (ai4) / Apache 2.0 (isotonic) |
| `legal` | TAB ECHR train (chunked ≤200 tok) + ai4privacy 0–5k + Common Crawl legal-filtered | ~18k | CC BY 4.0 (TAB) / CC BY 4.0 (ai4) / ODC-BY (CC) |
| `medical` | MEDDOCAN train (`GuiGel/meddocan`) + ai4privacy medical filter + Common Crawl medical-filtered | ~16k | CC BY 4.0 (MEDDOCAN) / CC BY 4.0 (ai4) / ODC-BY (CC) |
| `narrative` | Balanced ai4privacy + isotonic en/de/fr + cc-negative | ~17k | CC BY 4.0 / Apache 2.0 |
| `enterprise` | `nvidia/Nemotron-PII` train (10k rows, 55-class → 8-class remap) + Faker US-formats synth | ~15k | CC BY 4.0 (Nemotron) / Apache 2.0 (synth) |

**Train-vs-eval overlap** is documented in [`README.md` § dataset overlap matrix](README.md#train-vs-eval-dataset-overlap).

## Training procedure

Each LoRA adapter:
- LoRA config: `r=16`, `alpha=32`, target_modules `q_proj`, `k_proj`, `v_proj` of the inner mDeBERTa encoder (GLiNER head + RNN + span/prompt-rep frozen separately to prevent leakage).
- Trainable params: **~884k / ~290M = 0.3%** ("pure LoRA" contract).
- Optimizer: AdamW, BF16 cosine LR, weight decay 0.01.
- Epochs: 2–4 with early stopping on eval loss (per-domain corpus-dependent).
- Hardware: single 5090, ~50 minutes per adapter (fastest) to ~150 minutes (largest, devops).

See [`../TRAINING.md`](../TRAINING.md) for full step-by-step training trace + decision rationale.

## Evaluation

Mac M-series CPU, single seed, macro F1 at IoU ≥ 0.5, partial-match span scoring. 27 of 31 datasets benched — 4 require gated HuggingFace access (lmsys / enron / stackoverflow / thestack).

### Per-dataset F1

| Dataset | n | F1 | Notes |
|---|---:|:---:|---|
| `nullpii-bench` | 264 | **0.7280** | Project-bundled OOD gold standard |
| `tab-echr` | 127 | **0.8862** | EU legal (TAB ECHR test split, in-distribution-generalisation) |
| `oasst-dev-planted` | 15 | 0.4921 | Real chat text + planted PII |
| `presidio-synthetic` | 5k | 0.6907 | Faker synthetic (**Microsoft Presidio Evaluator**) |
| `argilla-pii` | 2k | 0.6002 | Third-party held-out (model-suggested labels — see Limitations) |
| `nemotron-pii-test` | 5k | **0.7602** | **NVIDIA Nemotron-PII** test split — ⚠ enterprise route trained on this — in-distribution |
| `ai4privacy-300k-heldout-v10` | 5k | 0.5283 | Held-out (offset 100k+) |
| `ai4privacy-300k` | 5k | 0.5336 | In-distribution-adjacent |
| `ai4privacy-400k` | 5k | 0.5554 | In-distribution-adjacent |
| `isotonic-en-heldout-v10` | 5k | 0.8671 | Held-out (offset 200k+) |
| `isotonic-de-heldout-v10` | 5k | 0.8746 | Held-out |
| `isotonic-fr-heldout-v10` | 5k | 0.8619 | Held-out |
| `isotonic-en` / `de` / `fr` / `it` | 5k each | 0.8783 / 0.8743 / 0.8600 / 0.8647 | Multilingual structured PII |
| `adversarial-typo` | 80 | **0.9400** | Char-swap |
| `adversarial-unicode` | 80 | **0.9358** | Cyrillic homoglyph + ZW |
| `adversarial-whitespace` | 80 | 0.3932 | Spaced PII |
| `adversarial-encoding` | 80 | 0.1216 | Base64 / URL / HTML-entity wrap |
| `adversarial-code` | 80 | **1.0000** | Credentials in comments |
| `adversarial-textattack` | 1.7k | 0.6900 | TextAttack mixed |
| `textattack-{homoglyph,charswap,chardelete,charinsert,charsub}` | 334 each | 0.66 / 0.72 / 0.72 / 0.66 / 0.66 | |

**Aggregate**: macro F1 across 27 datasets = **0.7172**.

### Held-out vs in-distribution split

| Subset | distiluse macro F1 |
|---|:---:|
| Held-out non-adversarial (n=7) | **0.7008** |
| Held-out incl adversarial (n=18) | 0.6897 |
| In-distribution / leak-disclosed (n=9: nullpii-bench, tab-echr, nemotron-pii-test, ai4privacy/isotonic offset-0) | 0.7712 |
| Mixed bench (n=27) | 0.7172 |

The honest OOD F1 is **0.70**. Mixed 0.7172 inflates by ~+0.07 from the leaked rows; those rows are documented as "in-distribution diagnostic" not OOD claims.

### Bare third-party baselines (pending GPU bench)

Bare-mode third-party baselines wired in `bench_full.py` for a later head-to-head matrix on a 5090 GPU pass: **Microsoft Presidio**, GLiNER (`urchade/gliner_multi_pii-v1`), `iiiorg/piiranha`, **Microsoft DeBERTa**-v3 fine-tune (`lakshyakh93/deberta_finetuned_pii`), scrubadub, **NVIDIA Nemotron-PII** (`nvidia/gliner-pii`), **OpenAI** `openai/privacy-filter` in three usage modes (naive HF / BIOES / opf-Viterbi).

Full bench artifacts: `packages/eval/published-bench/matrix.{json,csv}`.

## Limitations

- **Test-set tuning sensitivity (`TUNE-ENTGATE-01`)**: the enterprise-route gate value (`0.10`) was tuned on `nullpii-bench` AUDIT_A. A margin-sensitivity sweep `{0.0, 0.05, 0.10, 0.15}` is on the v11 roadmap and will publish a per-margin F1 range. A held-out routing-eval corpus (~500 docs, no overlap with `nullpii-bench`) is the proper resolution.
- **Nemotron train-test overlap on enterprise route (`LEAK-NEMO-ENTERPRISE-01`)**: the `enterprise` adapter was trained on **NVIDIA Nemotron-PII** (`nvidia/Nemotron-PII`) train split. The `nemotron-pii-test` cell is in-distribution generalisation, not OOD. A retrain on Faker-only US-formats is scheduled v11 — see [`adapter-enterprise.md`](adapter-enterprise.md) § Eval overlap.
- **Article 9 invisibility**: see Out-of-scope use.
- **Long-input chunking**: at 512-token boundaries via `chunk_chars=1400`, `overlap_chars=200`. Spans crossing chunk boundaries are merged via IoU dedupe — boundary-touching low-confidence spans may be dropped.
- **NVIDIA Nemotron contamination on `enterprise` route**: see Train-vs-eval overlap matrix. Treat `nemotron-pii-test` numbers as in-distribution.
- **CJK / RTL / Indic blind spot**: no training data; do not deploy.

## Ethical considerations

- **Training data demographics**: ai4privacy and Isotonic are Faker-templated, Western-name-biased. Persons-of-color names, non-Latin scripts, and non-Western address formats are under-represented. Empirical recall gap not yet quantified — will publish per-locale F1 in the bench.
- **PII categories outside scope**: see Out-of-scope use. The 8-class schema reflects the base GLiNER PII model's vocabulary; extending to Art. 9 sensitive categories is a v11 design decision.
- **Adversarial robustness**: the `_normalize_for_detection` preprocessor (NFKC + unidecode + zero-width strip + HTML entity / URL %XX decode + spaced-PII despace) handles common evasion patterns. Stronger attacks (TextAttack homoglyph + char-swap suite) are evaluated explicitly; expect 0.05–0.15 F1 degradation under adversarial perturbation.
- **Intended deployment**: pair with prompt-injection detection (e.g. Rebuff) and an upstream content classifier for Art. 9 categories. Standalone use is appropriate for non-regulated workloads only.

## How to use

```python
from gliner import GLiNER
# … router + adapter loading, see packages/eval/src/nullpii_eval/router.py

# (Reference implementation: packages/eval/scripts/bench_full.py
# tool def `nullpii-v10-router-embedding`.)
```

The npm library is migrating to the `onnx-community/gliner_multi_pii-v1` ONNX backbone (the same base the bench measures). Once the merged-LoRA ONNX export ships, the npm runtime will consume the full v10 router stack as well; until then the npm runtime ships the GLiNER base + recognizer pack + preprocessor without the per-domain LoRA layer.

## Citation

> nullpii contributors (2026). *nullpii v10 — Router (embedding-based, distiluse + 5 LoRA adapters on GLiNER multi PII v1).* https://huggingface.co/lBroth/nullpii-v10-router-embedding

## Acknowledgements

- Base model: [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (Zaratiana et al., NAACL 2024).
- Embedder: [`sentence-transformers/distiluse-base-multilingual-cased-v2`](https://huggingface.co/sentence-transformers/distiluse-base-multilingual-cased-v2) (Reimers & Gurevych).
- Training data: ai4privacy team, Isotonic team, TAB authors (Pilán et al., ACL 2022), MEDDOCAN organizers (IBERLEF 2019), Nvidia (Nemotron-PII).
- Synthetic data: Faker library.
