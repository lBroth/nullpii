# nullpii v10 — training procedure

EU AI Act Art. 53(1)(a) + NIST AI RMF Map 5.2 transparency disclosure for the v10 LoRA adapters and routers. Covers training data, procedure, hyperparameters, hardware, and eval-loss trajectories. The full engineering journal (raw step-by-step trace + decision rationale) is internal.

## Base model

`urchade/gliner_multi_pii-v1` — GLiNER architecture (Zaratiana et al., NAACL 2024) with **Microsoft mDeBERTa-v3** base inner encoder + GLiNER head (RNN + span-rep + prompt-rep). ~278 M parameters total. Pre-trained on multilingual PII span detection across 50+ languages. Apache 2.0.

## LoRA contract

5 per-domain adapters trained independently, each ~3.4 MB safetensors:

| Adapter | Domain | Train rows | Eval loss (start → final) |
|---|---|---:|---|
| `devops` | dev-paste, code, secrets | ~37k | 5.10 → 2.94 |
| `legal` | EU jurisprudence | ~18k | 4.85 → 3.21 |
| `medical` | Spanish + English clinical | ~16k | 5.42 → 3.05 |
| `narrative` | multilingual prose (router fallback) | ~17k | 4.72 → 3.12 |
| `enterprise` | US-business structured (Nemotron-aug) | ~15k | 10.06 → 3.91 |

LoRA configuration (identical across all 5):

| Parameter | Value |
|---|---|
| `r` (rank) | 16 |
| `alpha` | 32 |
| Target modules | `q_proj`, `k_proj`, `v_proj` (mDeBERTa inner encoder only) |
| Trainable params | ~884 k / ~290 M = **0.3%** ("pure LoRA" contract) |
| Frozen | GLiNER head (RNN + span-rep + prompt-rep) explicitly frozen via `param.requires_grad = False` to prevent leakage |
| Dropout | 0.1 |

## Training procedure

| Item | Value |
|---|---|
| Optimizer | AdamW |
| Learning rate | 1e-4, BF16 cosine schedule |
| Weight decay | 0.01 |
| Warmup | 100 steps |
| Batch size | 8 (effective via gradient accumulation × 2) |
| Max sequence length | 384 tokens |
| Epochs | 2–4 (early stopping on eval loss, dataset-dependent) |
| Mixed precision | BF16 |
| Hardware | Single NVIDIA RTX 5090 (32 GB) |
| Wall time per adapter | ~50 min (smallest, `general`) → ~150 min (largest, `devops`) |
| Total compute | ~7 GPU-hours for the 5-adapter set |

Class-balanced sampling per adapter. The `entity_types` argument passed to `predict_entities` was pinned to nullpii's 8-class set during training (`enterprise` adapter is the exception — trained with the 55-class Nemotron prompt set, then remapped 37→8 at inference time).

Negative-class regularizer: each adapter saw ~6.25 k records from a Common Crawl filtered "no-PII" partition (cc-negative-25k.jsonl), pre-filtered by an upstream PII classifier to ensure the negative class is genuinely PII-free.

## Routing

Two routers are trained on top of the 5 LoRA adapters:

### `nullpii-v10-router-embedding` (default)

- **Embedder**: **Google distiluse** `sentence-transformers/distiluse-base-multilingual-cased-v2` (~135 MB, frozen, no fine-tuning).
- **Prototype vectors**: 5 × 512-dim, computed as the mean training-corpus embedding for each domain. Built once via `build_router_embeddings.py`; stored as `.npz`.
- **Routing**: cosine similarity between input embedding and each prototype; argmax wins. The `enterprise` route is **gated** at margin ≥ 0.10 vs runner-up.
- Total training cost: ~5 minutes (embedder inference over 5 corpora).

## Training data composition

| Adapter | Datasets (train rows) | Licenses |
|---|---|---|
| `devops` | dev-paste-synth (Faker, ~20k) + ai4privacy 0–5k + isotonic en/de/fr/it 0–5k + cc-neg | Apache 2.0 / CC BY 4.0 / Apache 2.0 / ODC-BY |
| `legal` | TAB ECHR train (5k chunks ≤200 tok) + ai4privacy 0–5k + Common Crawl legal-filtered (8k) | CC BY 4.0 / CC BY 4.0 / ODC-BY |
| `medical` | MEDDOCAN train (`GuiGel/meddocan`, 10k) + ai4privacy medical filter (5k) + CC medical-filtered | CC BY 4.0 / CC BY 4.0 / ODC-BY |
| `narrative` | ai4privacy balanced subset (~6k) + isotonic en/de/fr (~7k) + cc-neg | CC BY 4.0 / Apache 2.0 / ODC-BY |
| `enterprise` | `nvidia/Nemotron-PII` train (10k, 55-class → 8-class remap) + Faker `en_US` US-formats synth (5k) | CC BY 4.0 / Apache 2.0 |

### Data preparation

- Synthesis scripts (`generate_dev_paste_synth.py`, `build_us_formats_corpus.py`) are seeded (`random.Random(seed=42)`) for deterministic reproduction.
- Tokenisation: GLiNER tokenizer (mDeBERTa SentencePiece variant), max-length 384.
- Span alignment: char-offset to token-offset via `prepare_v10_corpora.py` `emit()` function — records with non-aligning gold spans are dropped (~1–3% of records per corpus).
- Label remapping for `enterprise`: 37 of Nemotron's 55 PII categories map cleanly to nullpii's 8 categories via `_NEMOTRON_TO_NULLPII8` (see `packages/eval/src/nullpii_eval/adapters.py`); the remaining 18 are unmapped and dropped at training time.

## Train-vs-eval overlap

Documented in [`model-cards/README.md`](model-cards/README.md#train-vs-eval-dataset-overlap). Key callouts:

- `enterprise` adapter trained on **NVIDIA Nemotron-PII** train split → bench on `nemotron-pii-test` is **in-distribution memorisation**, not OOD.
- `legal` adapter trained on TAB ECHR train split → bench on `tab-echr` test split is **in-distribution generalisation** (disjoint rows, same dataset distribution).
- `ai4privacy-300k-heldout-v10` (offset 100k+) and `isotonic-{en,de,fr}-heldout-v10` (offset 200k+) are the rows none of the v10 adapters saw.

## Reproducibility

- Bench harness (`packages/eval/scripts/bench_full.py`) is published.
- Synthetic data generators (`generate_*.py`, `build_*.py`) are published with deterministic seeds.
- LoRA training scripts (`train_lora.py`, `prepare_v10_corpora.py`, `build_router_embeddings.py`) are internal because they reference pod IDs and local paths; the recipe above is sufficient to re-implement on equivalent hardware.
- Trained weights are published on HuggingFace Hub (see [`model-cards/`](model-cards/)).

Total time-to-reproduce on a 5090: ~7 GPU-hours for the 5-adapter set plus ~5 minutes for the prototype embedder.

## Change log

- **2026-05-03 / 04** — initial v10 LoRA training (5 adapters) on 5090.
- **2026-05-04** — `enterprise` adapter added (Nemotron-aug, 10k rows + Faker US-formats 5k); router-embedding gate added (margin 0.10 on `enterprise`).
- **2026-05-04** — F09 phone-pattern context anchor + F20 IDN email pattern revert (audit fixes; do not affect adapter weights — apply at inference-time regex post-pass only). See [`AUDIT_2026-05-04.md`](AUDIT_2026-05-04.md).
