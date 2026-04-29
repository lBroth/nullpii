---
license: apache-2.0
language:
  - en
  - de
  - fr
  - it
  - es
  - multilingual
tags:
  - pii-detection
  - token-classification
  - gliner
  - privacy
  - redaction
library_name: gliner
base_model: urchade/gliner_multi_pii-v1
pipeline_tag: token-classification
datasets:
  - ai4privacy/pii-masking-300k
  - Isotonic/pii-masking-200k
---

<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

[![CI](https://github.com/lBroth/nullpii/actions/workflows/ci.yml/badge.svg)](https://github.com/lBroth/nullpii/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/nullpii?color=cb3837)](https://www.npmjs.com/package/nullpii)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> **A study + reproducibility kit.** What does it cost — in F1, latency, and engineering — to replace the well-known `openai/privacy-filter` (1.5B, gpt-oss style) with a fine-tuned, much smaller `urchade/gliner_multi_pii-v1` (278M, older) on the same PII detection task?
>
> **TL;DR**: a 2-round fine-tune lifts GLiNER from 0.46–0.51 multilingual F1 to **0.93–0.97 (en/de/fr/it)** at ~14 ms/sample on a 5090 GPU and ~125 ms/sample on a Mac CPU. ONNX INT4 (`MatMulNBitsQuantizer`, 844 MB) keeps the F1 but only saves memory, not latency. ONNX CPU on Apple Silicon is ~25× faster than ONNX CPU on Linux x86 for this model. INT8 dynamic quant collapses (avoid).
>
> **The openai/privacy-filter caveat**: per its model card, inference is supposed to apply a constrained Viterbi BIOES decoder; the upstream `transformers` integration ships only per-token logits. Calling `transformers.pipeline()` with default `aggregation_strategy="simple"` therefore produces fragmented spans (`.com`, `+1-843-555-014` then `2`, `aitre`). That is **not the model's intended quality** — just naive HF usage. To get its real output you need either (a) the official [`opf` CLI](https://github.com/openai/privacy-filter), (b) nullpii's npm runtime which ships the constrained Viterbi, or (c) the small Python BIOES decoder in `packages/eval/scripts/bench_openai_decoders.py` that recovers most of the gap with no extra dependency.

## What's in this repo

Two deliverables and the experiment that produced them:

1. **npm library** — `nullpii` (this package). Sanitize / restore engine over `openai/privacy-filter` with the constrained Viterbi BIOES decoder + chunking + recognizer post-pass + reversible vault. CLI binary `nullpii sanitize|restore|scan|benchmark|...` plus a TS API (`sanitize()`, `restore()`, `NullPii` class).
2. **HuggingFace model** — [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii). GLiNER fine-tune in PT FP32, ONNX FP32 and ONNX INT4 variants. Use the standard `gliner.GLiNER.from_pretrained(...)` API.
3. **Reproducibility kit** — `packages/eval/` with the bench harness, dataset loaders (ai4privacy, Isotonic, project-bundled `nullpii-bench`, plant-and-detect Enron / StackOverflow / The-Stack), training scripts, and comparison results.

## Headline comparison

Multilingual F1, IoU ≥ 0.5. **Numbers update progressively as the overnight Mac CPU bench completes** — cells marked `N/D` are queued. Source: `packages/eval/results/openai_decoders.json` (openai-* rows, n=200 cap, fresh) + `packages/eval/results/train/variant_bench_v2.json` (nullpii-* rows, n=100 cap, preview).

| Dataset                  | baseline GLiNER | **nullpii PT FP32** | nullpii ONNX INT4 | openai (BIOES decoder) | openai (HF naive) |
| ------------------------ | --------------: | ------------------: | ----------------: | ---------------------: | ----------------: |
| isotonic-en              |          0.462¹ |              0.951¹ |        **0.961¹** |                  0.527 |             0.374 |
| isotonic-de              |          0.497¹ |              0.932¹ |        **0.939¹** |                  0.541 |             0.383 |
| isotonic-fr              |          0.471¹ |              0.947¹ |        **0.967¹** |                  0.538 |             0.375 |
| isotonic-it              |          0.509¹ |              0.938¹ |        **0.959¹** |                  0.537 |             0.371 |
| ai4privacy-300k          |          0.309¹ |              0.800¹ |        **0.864¹** |                  0.236 |             0.129 |
| nullpii-bench            |             N/D |                 N/D |               N/D |              **0.737** |             0.458 |
| dev-prompts-synth²       |          0.618¹ |              0.821¹ |             0.801¹ |                    N/D |               N/D |
| wikiann-es³              |             N/D |                 N/D |               N/D |                    N/D |               N/D |
| wikiann-zh³              |             N/D |                 N/D |               N/D |                    N/D |               N/D |
| wikiann-ja³              |             N/D |                 N/D |               N/D |                    N/D |               N/D |

¹ Preview-grade (n=100, single seed). Full-bench numbers (n=5000) land progressively as the Mac overnight run finishes. ² See "Dataset taxonomy" below — `dev-prompts-synth` is training-overlap. ³ WikiAnn is PER/LOC/ORG NER, not PII; `PER → private_person`, `LOC → private_address` is a loose schema match. Read the row as a non-Latin transfer signal (es/zh/ja), not an absolute F1.

### Dataset taxonomy

The bench mixes datasets the model **was trained on** with datasets it has **never seen**. Reading the rows requires keeping these straight.

- **`dev-prompts-synth` is ours, not public.** Generated in-process by `_generate_dev_prompts` in `packages/eval/src/nullpii_eval/public_datasets.py`: 10 hand-written templates (AWS key, phone, JWT, email, …), PII planted at known positions via `_DEV_PROMPT_SYNTH` faker functions, stable RNG seed `2026`, Apache 2.0. No HF download, zero IO.
- **Critical caveat**: round 2 of the fine-tune added 30k samples from this same generator to the training mix (it had to, because round 1 regressed on it). Benching on `dev-prompts-synth` therefore tests training-distribution recall, **not** generalization. Treat it as a regression check.
- **Generalization rows** (out-of-distribution, never-seen): `nullpii-bench`, `enron-planted`, `stackoverflow-planted`, `thestack-planted`, `wikiann-{es,zh,ja}`, `conll2003`. These are the rows that say something honest about the model's transfer.
- **Training-overlap rows**: `dev-prompts-synth`, `ai4privacy-300k` (training set), `isotonic-{en,de,fr,it}` (training set). Strong numbers here are necessary but not sufficient.

`COMPARISONS.md` carries the full multi-platform tables, the in-Python BIOES decoder used to recover most of the openai/privacy-filter quality without extra deps, and the qualitative comparison (`packages/eval/results/train/qualitative_compare.md`) over 30 real prompts (medical records, contracts, multilingual itineraries, GitHub issues from openai/privacy-filter, JP/CN/KR cases that surface known non-Latin gaps).

## Library mode (npm)

```ts
import { sanitize, restore } from 'nullpii';

const safe = await sanitize('Email John Smith at john@acme.com about his SSN 123-45-6789');
// safe.text = 'Email [[NULLPII:private_person:0]] at [[NULLPII:private_email:0]] about his [[NULLPII:secret:0]]'
// safe.session = opaque session id

// ... pass safe.text to any LLM ...
const reply = `Hello [[NULLPII:private_person:0]], we received your request.`;

const back = await restore(reply, safe.session);
// back = 'Hello John Smith, we received your request.'
```

Programmatic API (full control):

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });

const { sessionId, sanitized, spans } = await np.sanitize(
  "Hi, I'm Maria Rossi (maria.rossi@example.it). My order #ACME-2026-04812 shipped to via Roma 45, 00184 Roma.",
);

// ... LLM call uses `sanitized` ...
const reply = '...';

const { restored } = np.restore(reply, sessionId);
await np.dispose();
```

CLI:

```bash
$ npx nullpii sanitize --stdin --format json < customer-email.txt | jq .sanitized
"Hi [[NULLPII:private_person:0]], thanks for reaching out about [[NULLPII:account_number:0]]..."
```

## Model mode (HuggingFace)

```python
from gliner import GLiNER

model = GLiNER.from_pretrained("lBroth/nullpii")
labels = ["account_number", "private_address", "private_date",
          "private_email", "private_person", "private_phone",
          "private_url", "secret"]

text = "Email John Smith at john@acme.com about IBAN IT60X0542811101000000123456"
for entity in model.predict_entities(text, labels, threshold=0.5):
    print(entity["label"], "→", entity["text"], entity["score"])
```

ONNX (CPU-deployment recommended, INT4 ~844 MB):

```python
model = GLiNER.from_pretrained(
    "lBroth/nullpii",
    load_onnx_model=True,
    onnx_model_file="onnx/model_int4.onnx",
)
```

The repo ships:

- **PyTorch FP32** at the repo root (`pytorch_model.bin` + `gliner_config.json` + tokenizer files).
- **ONNX FP32** at `onnx/model.onnx` (~1.1 GB).
- **ONNX INT4** at `onnx/model_int4.onnx` (~844 MB, quantized via `onnxruntime.quantization.matmul_nbits_quantizer`).

ONNX INT8 is intentionally **not published** — it collapses on F1 for this architecture (avg F1 drops to ~0.58). INT4 preserves quality and is the recommended CPU-deployment variant.

## What gets caught (8 categories)

| Label             | Examples                                             |
| ----------------- | ---------------------------------------------------- |
| `private_person`  | personal names                                       |
| `private_email`   | email addresses                                      |
| `private_phone`   | phone / fax numbers                                  |
| `private_address` | street addresses                                     |
| `private_date`    | birth dates, hire dates, anniversaries               |
| `private_url`     | private URLs (admin panels, internal wikis)          |
| `account_number`  | bank accounts, IBAN, customer IDs                    |
| `secret`          | API keys, passwords, JWT tokens                      |

For known formats with low ML coverage (your internal employee ID, AWS access keys, SWIFT BIC), add custom regex-based recognizers as a post-pass:

```ts
np.addRecognizer({
  id: 'aws-key',
  pattern: /\bAKIA[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
});
```

ML-first, regex-augmented. No "no regex" purity theatre.

## Install (npm)

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an **optional peer dependency** — install it only if you want the Node-side backend (CPU / MPS / CUDA). The library is also usable in browsers / WebGPU via the `nullpii/backend/*` subpath imports.

Requires **Node 24 LTS** (see `.nvmrc`).

## Backends

| Backend | Platform               | Notes                                              |
| ------- | ---------------------- | -------------------------------------------------- |
| `cpu`   | All                    | Universal. Currently fastest on macOS.             |
| `mps`   | Apple Silicon          | CoreML EP; partial op coverage — see `EVAL_RESULTS.md`. |
| `cuda`  | Linux/Windows + NVIDIA | Tensor cores on Volta+. CUDA EP via ORT.           |

Auto-selects in priority **CUDA → MPS → CPU**. Default variant is `int4` (~875 MB, ~6% F1 drop). Pin `variant: 'fp32'` (~5 GB) when you need maximum accuracy or a regression baseline.

## Architecture

```
input text
   │
   ▼                  ┌──────────────────────────────┐
tokenizer ─offsets─►  │ ONNX Runtime (CPU / MPS /    │
   │                  │             CUDA EP)         │
   │                  │                              │
   ▼                  └────────────────┬─────────────┘
attention_mask                          │ logits [seq × 33]
                                        ▼
                            constrained Viterbi (BIOES)
                                        │
                                        ▼
                              char-level PiiSpan[]
                                        │
                                        ▼
              vault.sanitize ──► (placeholder text, sessionId)
                                        │
                                        ▼
                            (LLM call with placeholder text)
                                        │
                                        ▼
                            vault.restore(sessionId) ──► original text
```

## nullpii-bench (eval dataset)

`packages/eval/datasets/nullpii-bench.jsonl`:

- **271 samples**, **680 PII spans**, **5 locales** (en / it / de / fr / es), Apache-2.0.
- Three subsets: `bundled` (202 dev-style prompts — PR reviews, deploy logs, RFCs, customer-support tickets), `adversarial` (decoys), `long-prompts` (62 ~3k-char prompts that exercise chunking).
- Schema: `{ id, locale, subset, text, spans }` per row. See [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md).

## Training details (model)

- Base: `urchade/gliner_multi_pii-v1` (mDeBERTa-v3-base + GLiNER head, ~278M params)
- Hardware: 1× RTX 5090 (32 GB)
- Mixed precision: BF16 + TF32
- Optimizer: AdamW, cosine LR with linear warmup (ratio 0.1)
- **Training data is a subset, not the full upstream releases.** Default caps (`packages/eval/scripts/runpod/train-on-pod.sh`): `ai4privacy/pii-masking-300k` capped at **100k** samples (≈33% of the full release), `Isotonic/pii-masking-200k` capped at **20k per locale × 5 locales = 100k** samples (≈50% of the release, distributed across en/de/fr/it/es). Round 2 added **30k synthetic dev-prompts** from `_generate_dev_prompts`. Total train mix ≈ 230k samples.
- **Round 1**: ai4privacy + Isotonic only. Effective batch 24 (12 × 2 grad accum), encoder LR 5e-6 / head LR 1e-5, 20 epochs cap, early stopping patience 3 → stopped at epoch 6. Recovered multilingual F1 0.93+ but **regressed dev-prompts-synth** (0.62 → 0.43) due to distribution mismatch.
- **Round 2**: continued from round-1 best, added the 30k dev-prompts-synth to the training mix, halved LR to 2e-6 / 5e-6, raised weight decay from 0.01 to 0.05. 10 epochs cap, early stopping patience 3 → best at epoch 8 (eval_loss 1.528). dev-synth recovered to 0.82 while multilingual stayed 0.93+.

A larger train mix (full 300k + 200k) is plausible to push F1 further, but the diminishing-returns curve at 200k+ samples on this fine-tune is steep — the current cap is the cost/quality knee, not a budget ceiling.

## Limitations

- **Non-Latin scripts**: Japanese / Korean / Chinese dates and names are *not* reliably detected. The training mix didn't include CJK-heavy data. Documented as a known gap; the overnight bench's `wikiann-zh` / `wikiann-ja` rows quantify it.
- **Adversarial decoys**: a small adversarial subset (~6 samples) is dominated by structured-secret patterns that the regex pack catches trivially; the nullpii model on its own is not optimised for these. Use the npm runtime's recognizer post-pass for guaranteed regex coverage.
- **INT8 dynamic quant collapse**: do not use the INT8 ONNX path; F1 drops to ~0.58. The matmul-nbits INT4 path is the recommended quantized variant.

## Privacy guarantees

- The PII detection step **never touches the network**.
- The vault is **in-memory only** — never serialized to disk.
- `destroySession()` purges the mapping.
- No `console.log` of PII; debug logs only carry counts and short ids.
- See [SECURITY.md](SECURITY.md) for the full threat model and how to report a vulnerability.

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Same as the GLiNER base model and both training datasets.

The full runtime tree is **100% permissive** (MIT / Apache-2.0 / BSD / ISC / CC0). Verified by `npm run license-check` in CI.

## Citation

> nullpii contributors (2026). *nullpii: a study comparing openai/privacy-filter and a fine-tuned GLiNER for local PII detection.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, mDeBERTa-v3-base + GLiNER head). Training data: a **subset** of [`ai4privacy/pii-masking-300k`](https://huggingface.co/datasets/ai4privacy/pii-masking-300k) (~100k of 300k) and [`Isotonic/pii-masking-200k`](https://huggingface.co/datasets/Isotonic/pii-masking-200k) (~100k of 200k, multilingual mix), plus 30k synthetic dev-prompts. See "Training details" above.
