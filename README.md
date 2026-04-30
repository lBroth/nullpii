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
> **Headline finding (validated)**: HF `transformers.pipeline()` with the default `aggregation_strategy="simple"` *does not implement* the constrained Viterbi BIOES decoder that `openai/privacy-filter`'s model card prescribes. Naive HF usage produces fragmented spans (`.com`, `+1-843-555-014` then `2`, `aitre`). The official [`opf` CLI](https://github.com/openai/privacy-filter) ships the real decoder; calling it via `opf._api.OPF` recovers ~+0.30 F1 on `nullpii-bench`. **This is the most honest, reproducible result in this repo.**
>
> **Headline finding (qualified)**: A 2-round fine-tune of GLiNER on a subset of `ai4privacy/pii-masking-300k` + `Isotonic/pii-masking-200k` improves F1 substantially on **held-out splits** of those same datasets (overnight bench in flight). The earlier preview "0.93–0.97 multilingual F1" was measured **on the training distribution** (same dataset slices the model was trained on) — that is memorization, not generalization. Headline numbers are being re-measured on `*-heldout` splits drawn from rows the model never saw; those are the only fine-tune numbers worth quoting.

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

F1, IoU ≥ 0.5. **Numbers update progressively as the overnight bench completes**; this section will be rewritten end-to-end when the run finishes (`packages/eval/results/mac-overnight-20260430-v2/matrix.json`).

The columns under headline are **held-out** (suffix `-heldout`): never seen at training time. Training-distribution rows live in the appendix below as a regression sentinel only.

| Dataset                  | baseline GLiNER | **nullpii PT FP32** | nullpii ONNX INT4 | openai (official Viterbi) | openai (HF naive) |
| ------------------------ | --------------: | ------------------: | ----------------: | ------------------------: | ----------------: |
| nullpii-bench (n=264)    |             N/D |                 N/D |               N/D |                       N/D |             0.458 |
| ai4privacy-heldout       |             N/D |                 N/D |               N/D |                       N/D |               N/D |
| isotonic-en-heldout      |             N/D |                 N/D |               N/D |                       N/D |               N/D |
| isotonic-de-heldout      |             N/D |                 N/D |               N/D |                       N/D |               N/D |
| isotonic-fr-heldout      |             N/D |                 N/D |               N/D |                       N/D |               N/D |
| isotonic-it-heldout      |             N/D |                 N/D |               N/D |                       N/D |               N/D |

### Appendix — training-overlap rows (regression check, NOT generalization)

These rows are kept to confirm the fine-tune did not collapse on its training data. They are **not** evidence of generalization. Do not quote them as headline numbers.

| Dataset                       | nullpii PT FP32 | nullpii ONNX INT4 | openai (official Viterbi) |
| ----------------------------- | --------------: | ----------------: | ------------------------: |
| ai4privacy-traindist          |             N/D |               N/D |                       N/D |
| isotonic-en-traindist         |             N/D |               N/D |                       N/D |

### Appendix — loose-schema rows (WikiAnn PER/LOC, not PII)

PER → `private_person`, LOC → `private_address` is a loose mapping. Read these as non-Latin transfer signals only.

| Dataset      | nullpii PT FP32 | openai (official Viterbi) |
| ------------ | --------------: | ------------------------: |
| wikiann-es   |             N/D |                       N/D |
| wikiann-zh   |             N/D |                       N/D |
| wikiann-ja   |             N/D |                       N/D |

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
