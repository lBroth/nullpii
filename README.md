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

> **What this is.** Two independent deliverables packaged together with an honest evaluation. Read the limitations before quoting any number.
>
> 1. **npm library** — `nullpii` on npm. Wraps `openai/privacy-filter` (1.5B) with the constrained Viterbi BIOES decoder, chunking, regex recognizers, and a reversible in-memory vault. Independent of the fine-tuned model below.
> 2. **HuggingFace model** — `lBroth/nullpii` on HF. A separate fine-tune of `urchade/gliner_multi_pii-v1` (278M). Useful as a smaller, drop-in detector. **Not used by the npm library.**
>
> **Headline finding (validated, useful)**: HF `transformers.pipeline()` with the default `aggregation_strategy="simple"` *does not implement* the constrained Viterbi BIOES decoder that `openai/privacy-filter`'s model card prescribes. Naive HF usage produces fragmented spans. Calling the official [`opf` CLI](https://github.com/openai/privacy-filter) (via `opf._api.OPF`) recovers **+0.10–0.25 F1** across every benchmark row — see "Headline comparison" below for the table. **This is the most reproducible useful result in this repo.**
>
> **Headline finding (positive, end-to-end)**: The npm runtime (`openai/privacy-filter` ONNX INT4 + constrained Viterbi BIOES + chunking + regex recognizer post-pass) **is the best tool on the only true-OOD dataset**: `nullpii-bench` F1 = **0.7669**, beating baseline GLiNER (0.6947), `openai-official` (0.6764), and the fine-tune (0.4737). The runtime stack on top of the bare model with proper Viterbi adds +0.09 F1 on this row. The npm package is the recommended deployment.
>
> **Headline finding (negative, equally important)**: A 2-round fine-tune of GLiNER on a subset of `ai4privacy/pii-masking-300k` + `Isotonic/pii-masking-200k` **loses 0.22 F1 on the OOD row** (`nullpii-bench`: baseline GLiNER 0.69 → fine-tune 0.47). The fine-tune wins by 0.30+ F1 on held-out rows of the *same* training datasets, but held-out vs train-dist numbers are identical within 0.005 — that's memorization at the format/style level, not generalization. The earlier preview "0.93–0.97 multilingual F1" was measured on the training distribution and is misleading. **Default to the npm runtime, not the fine-tune, until a generalization-aware training mix is built.**

## What's in this repo

Two **independent** deliverables and the eval kit:

1. **npm library** — `nullpii` (this package). Sanitize / restore engine over `openai/privacy-filter` with the constrained Viterbi BIOES decoder + chunking + recognizer post-pass + reversible vault. CLI binary `nullpii sanitize|restore|scan|benchmark|...` plus a TS API (`sanitize()`, `restore()`, `NullPii` class). Does **not** depend on the fine-tuned HF model below.
2. **HuggingFace model** — [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii). GLiNER fine-tune in PT FP32, ONNX FP32 and ONNX INT4 variants. Standalone — use via `gliner.GLiNER.from_pretrained(...)`. Does **not** depend on the npm library.
3. **Reproducibility kit** — `packages/eval/` with the bench harness, dataset loaders (held-out splits supported), training scripts, and comparison results.

## Honest limitations (read this first)

Past versions of this README quoted "0.93–0.97 multilingual F1" as a headline. Those numbers were measured on the same dataset slices the model was fine-tuned on (`isotonic-{en,de,fr,it}` and `ai4privacy-300k`, first N rows). That is **memorization measurement, not generalization**. The current overnight bench replaces those numbers with measurements on **held-out** splits (`*-heldout`, drawn from rows after the training cut at `ai4privacy[100000:]` and `isotonic[200000:]`).

Other limitations the previous version hid:

- **No `opf` CLI baseline.** The phrase "openai (proper Viterbi)" appeared in old tables next to `—` cells: we never ran the real reference. The `openai-bioes` row was a hand-rolled approximation (greedy, no transition costs), not the upstream Viterbi. The current bench includes `openai-official` (the actual `opf._api.OPF` Python API). Old `openai-bioes` numbers should be discarded.
- **`dev-prompts-synth` is a self-graded test.** The generator (10 hand-written templates) is ours, and 30k samples from it were mixed into round-2 training. Benchmarking on it tests recall of training distribution, not detection capability. Dropped from the headline; kept only as a regression sentinel.
- **WikiAnn schema mismatch.** PER → `private_person`, LOC → `private_address` is a loose mapping. Numbers should be read as a non-Latin transfer signal (es/zh/ja), not absolute PII F1.
- **No statistical tests in published numbers yet.** Single-seed benches at fixed `n`. Bootstrap CI + multi-seed are pending; numbers below are point estimates only.
- **`enron-planted`, `stackoverflow-planted`, `thestack-planted`, `conll2003` loaders are broken on the open-data path** (mirrors removed/renamed/gated). The "real-text + planted PII" generalization datasets are not available to us right now; the only true OOD row is `nullpii-bench` (264 samples, project-bundled). Pending fix.
- **Two independent deliverables, not one study.** The npm library wraps `openai/privacy-filter` (1.5B). The HF model is the GLiNER fine-tune (278M). They share a repo, an evaluation kit, and a license — that is all. The "unified study" framing in older versions was post-hoc.

## Headline comparison

F1, IoU ≥ 0.5. Mac M-series CPU bench, n=2000 per dataset (n=264 for `nullpii-bench`), single seed. Source: `packages/eval/results/mac-overnight-20260430-v2/matrix.json`.

The headline row is **`nullpii-bench`** — the only true out-of-distribution dataset (264 project-bundled prompts, never used in training). The `*-heldout` rows below it are slices of the *training* datasets that the fine-tune never saw, but same distribution → numbers cluster with `*-traindist` (see appendix).

| Dataset                  | baseline GLiNER | nullpii PT FP32 | nullpii ONNX INT4 | openai (official Viterbi) | openai (HF naive) | **nullpii npm runtime** |
| ------------------------ | --------------: | --------------: | ----------------: | ------------------------: | ----------------: | ----------------------: |
| **nullpii-bench (OOD)**  |          0.6947 |          0.4737 |            0.3966 |                    0.6764 |            0.4264 |              **0.7669** |
| ai4privacy-heldout       |          0.1267 |          0.3285 |        **0.3855** |                    0.2303 |            0.1451 |                     N/D |
| isotonic-en-heldout      |          0.6016 |          0.9277 |        **0.9339** |                    0.5631 |            0.3822 |                     N/D |
| isotonic-de-heldout      |          0.5912 |          0.9371 |        **0.9495** |                    0.5734 |            0.3809 |                     N/D |
| isotonic-fr-heldout      |          0.5953 |          0.9387 |        **0.9480** |                    0.5766 |            0.3771 |                     N/D |
| isotonic-it-heldout      |          0.5818 |          0.9372 |        **0.9384** |                    0.6053 |            0.3894 |                     N/D |

**nullpii npm runtime** = `openai/privacy-filter` ONNX INT4 + constrained Viterbi BIOES + chunking + regex recognizer post-pass + reversible vault. Same model as the `openai (...)` columns, different decode + post-processing stack.

**Reading the table:**

- **nullpii npm runtime is the best tool overall on the only true-OOD row** (`nullpii-bench`: 0.7669 — beats every other tool, including baseline GLiNER 0.6947 and `openai-official` 0.6764). The runtime stack (Viterbi + chunking + regex post-pass) adds value over the bare model with proper Viterbi alone. **This is the strongest end-to-end result the repo has on real-world data.** Other-dataset cells are N/D — the bench harness deadlocked on long-input chunking-Viterbi inputs (sample 1700 of `ai4privacy-heldout` triggered an infinite loop on the runtime side, killed manually); needs a per-call timeout fix before re-running. The OOD row is the headline number; the `*-heldout` cells of the runtime can be filled in once the harness is fixed.
- The fine-tune (`nullpii PT FP32` / `ONNX INT4`) **loses 0.22 F1 on the OOD row** (`nullpii-bench`: baseline 0.69 → fine-tune 0.47). It wins on `*-heldout` rows by 0.30+ F1, but those are same-distribution-different-rows — the appendix shows `traindist` and `heldout` numbers are within 0.005 of each other, confirming "held-out" within the same dataset is not a generalization test.
- `openai-official` (the real Viterbi via `opf._api.OPF`) is competitive with the **baseline** GLiNER on OOD (0.68 vs 0.69) and beats `openai-naive` on every row by 0.10–0.18 F1 — that delta quantifies what the constrained Viterbi BIOES decoder buys you over `transformers.pipeline()` defaults.
- `openai-naive` (HF default `aggregation_strategy='simple'`) is the worst tool across the board on real tasks. Do not use the model that way.

**`gliner-v2.1` (generic-NER backbone, NOT PII-fine-tuned)**: tested on `nullpii-bench` (F1=0.156) and `ai4privacy-heldout` (F1=0.006). Useless for PII labels — a generic-NER backbone does not transfer to the 8-category PII schema without supervision. Dropped from the headline.

### Appendix — training-distribution rows (regression sentinel)

Same datasets as headline, but slice indices the model **was** trained on. By construction these should match `*-heldout` if the fine-tune neither memorised individual rows nor regressed on its train set. They do, within 0.005 F1.

| Dataset                  | baseline GLiNER | nullpii PT FP32 | nullpii ONNX INT4 | openai (official Viterbi) | openai (HF naive) |
| ------------------------ | --------------: | --------------: | ----------------: | ------------------------: | ----------------: |
| ai4privacy-traindist     |          0.1171 |          0.3718 |        **0.3859** |                    0.2224 |            0.1392 |
| isotonic-en-traindist    |          0.6065 |          0.9324 |        **0.9341** |                    0.5767 |            0.3860 |

The takeaway is *not* "the fine-tune is great on its training data" (it had to be). It's that **same-dataset held-out is nearly identical to train-dist** — i.e. shifting the slice index doesn't measure generalization. The OOD signal lives only in `nullpii-bench`.

### Appendix — WikiAnn (loose-schema NER, not native PII)

PER → `private_person`, LOC → `private_address` is a loose mapping. Read as non-Latin transfer signals only — absolute F1 is not directly comparable to the headline rows.

| Dataset      | baseline GLiNER | nullpii PT FP32 | nullpii ONNX INT4 | openai (official Viterbi) | openai (HF naive) |
| ------------ | --------------: | --------------: | ----------------: | ------------------------: | ----------------: |
| wikiann-es   |      **0.3326** |          0.2262 |            0.1686 |                    0.1844 |            0.0878 |
| wikiann-zh   |          0.1353 |          0.1518 |        **0.1549** |                    0.0863 |            0.0383 |
| wikiann-ja   |          0.0665 |      **0.1080** |            0.0974 |                    0.0563 |            0.0344 |

Two patterns: (1) Spanish (Latin script, in training) — baseline GLiNER beats the fine-tune (overfitting cost again). (2) Chinese / Japanese (CJK, NOT in training) — every tool collapses below 0.16 F1. The fine-tune holds a tiny edge on `wikiann-ja` but the absolute floor is too low to call it useful. **CJK is a dead zone across the board** until someone trains on CJK PII data.

### Dataset notes

- **`nullpii-bench` (n=264)** — project-bundled, `packages/eval/datasets/nullpii-bench.jsonl`. The only true OOD generalization dataset currently working. Apache-2.0.
- **`*-heldout`** — `ai4privacy[100000:105000]` and `isotonic[200000:200000+prefetch]` (per locale, after lang filter). Slice indices documented in `packages/eval/scripts/bench_full.py` (`_AI4_HELDOUT_OFFSET`, `_ISOTONIC_HELDOUT_ROW_OFFSET`).
- **`*-traindist`** — first-rows slices, same indices the model was trained on. Regression sentinel.
- **`dev-prompts-synth`** — ours, training-overlap. Removed from default bench; see `packages/eval/src/nullpii_eval/public_datasets.py:_generate_dev_prompts` if you need it.

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
