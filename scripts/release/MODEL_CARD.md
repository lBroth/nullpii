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

# nullpii

A two-round fine-tune of [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1)
on a mix of `ai4privacy/pii-masking-300k`, `Isotonic/pii-masking-200k`
(en / de / fr / it locales) and a synthetic dev-prompts generator.
Trained as part of the [nullpii](https://github.com/lBroth/nullpii)
research kit comparing `openai/privacy-filter` (1.5B, naive HF
usage vs intended Viterbi usage) against a smaller, fine-tuned GLiNER
on the same PII detection task.

The repo ships three variants:

- **PyTorch FP32** at the repo root (`pytorch_model.bin` +
  `gliner_config.json` + tokenizer files).
- **ONNX FP32** at `onnx/model.onnx` (~1.1 GB).
- **ONNX INT4** at `onnx/model_int4.onnx` (~844 MB, quantized via
  `onnxruntime.quantization.matmul_nbits_quantizer`).

ONNX INT8 is intentionally **not published** — it collapses on F1 for
this architecture (avg F1 drops to ~0.58). INT4 preserves quality and
is the recommended CPU-deployment variant.

## Why fine-tune

Baseline GLiNER multi-pii-v1 multilingual F1 sits around 0.46–0.51 on
isotonic-en/de/fr/it. After two rounds of fine-tuning, the same
backbone reaches **0.93–0.97 multilingual F1** while staying at ~278M
parameters. See the comparison write-up at
[github.com/lBroth/nullpii/blob/main/docs/guide/comparisons.md](https://github.com/lBroth/nullpii/blob/main/docs/guide/comparisons.md).

## Benchmark (preview, n=100 per dataset, IoU ≥ 0.5)

| Dataset                  | baseline GLiNER | **nullpii PT FP32** | nullpii ONNX INT4 |
| ------------------------ | --------------: | -------------: | -----------: |
| isotonic-en              |           0.462 |          0.951 |    **0.961** |
| isotonic-de              |           0.497 |          0.932 |    **0.939** |
| isotonic-fr              |           0.471 |          0.947 |    **0.967** |
| isotonic-it              |           0.509 |          0.938 |    **0.959** |
| ai4privacy-300k          |           0.309 |          0.800 |    **0.864** |
| dev-prompts-synth        |       **0.618** |          0.821 |        0.801 |

Latency p50 (5090 GPU): **14 ms / sample** for PT FP32. Mac Apple
Silicon CPU: **31 ms** (ONNX FP32) / **43 ms** (ONNX INT4) /
**87 ms** (PT FP32). Linux x86 ONNX CPU is ~25× slower than Apple
Silicon ONNX CPU on this model — vendor-specific kernel choice
matters. INT4 is a *memory* win, not a *latency* win on CPU.

## Usage

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

ONNX:

```python
model = GLiNER.from_pretrained(
    "lBroth/nullpii",
    load_onnx_model=True,
    onnx_model_file="onnx/model_int4.onnx",
)
```

## Training details

- Base: `urchade/gliner_multi_pii-v1` (mDeBERTa-v3-base + GLiNER head)
- Hardware: 1× RTX 5090 (32 GB)
- Mixed precision: BF16 + TF32
- Optimizer: AdamW, cosine LR with linear warmup (ratio 0.1)
- Round 1: ai4privacy 200k + Isotonic 30k × {en, de, fr, it, es},
  effective batch 24 (12 × 2 grad accum), encoder LR 5e-6 / head LR
  1e-5, 20 epochs cap, early stopping patience 3 → stopped at epoch 6.
  Recovered multilingual F1 0.93+ but **regressed dev-prompts-synth**
  (0.62 → 0.43) due to distribution mismatch.
- Round 2: continued from round-1 best, added 30k dev-prompts-synth
  to the training mix, halved LR to 2e-6 / 5e-6, raised weight decay
  from 0.01 to 0.05. 10 epochs cap, early stopping patience 3 →
  best at epoch 8 (eval_loss 1.528). dev-synth recovered to 0.82
  while multilingual stayed 0.93+.

## Limitations

- **Non-Latin scripts**: Japanese / Korean / Chinese dates and names
  are *not* reliably detected. The training mix didn't include
  CJK-heavy data. Documented as a known gap.
- **`bench-adversarial` regression**: the small adversarial subset
  (n=6) is dominated by structured-secret patterns the regex pack
  catches trivially; the nullpii model on its own is not optimised for
  these. Use the `nullpii` runtime's recognizer post-pass for
  guaranteed regex coverage.
- **INT8 dynamic quant collapse**: do not use the INT8 ONNX path; F1
  drops to ~0.58. The matmul-nbits INT4 path is the recommended
  quantized variant.

## Intended use

Local PII redaction in dev workflows: sanitize prompts before they
leave the machine, restore originals in the response. Suitable for
sanitization layers, RAG pipelines that need to scrub before
embedding, or a redaction CLI.

## License

Apache 2.0. Same as the GLiNER base model and both training datasets.

## Citation / attribution

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1)
(GLiNER, Pile of Law / Pile of PII derivative); training data from
[`ai4privacy/pii-masking-300k`](https://huggingface.co/datasets/ai4privacy/pii-masking-300k)
and [`Isotonic/pii-masking-200k`](https://huggingface.co/datasets/Isotonic/pii-masking-200k).

If you use this model, please cite the comparison write-up:

> nullpii contributors (2026). nullpii: a study comparing
> openai/privacy-filter and a fine-tuned GLiNER for local PII
> detection. https://github.com/lBroth/nullpii
