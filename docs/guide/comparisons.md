# Comparisons

Tool-vs-tool numbers on the dev-focused bench suite. The same input
goes to every tool, F1 is partial-match (IoU ≥ 0.5), latency is
per-call wall-clock. See `packages/eval/results/runpod-YYYYMMDD/matrix.csv`
for the live tabulation. Reproduction recipe at the bottom.

## Tools in the matrix

| Tool | Source | Notes |
|------|--------|-------|
| **nullpii** | `openai/privacy-filter` ONNX + nullpii pipeline | Chunking + constrained Viterbi BIOES + recognizers |
| **nullpii (fine-tuned GLiNER)** | `urchade/gliner_multi_pii-v1` fine-tuned on ai4privacy + Isotonic + dev-prompts-synth | 2-round fine-tune, ~278M PT or ONNX (FP32 / INT4) |
| **openai (bare HF)** | same upstream model, `transformers.pipeline()` | Isolates the value of the nullpii runtime |
| **gliner** | `urchade/gliner_multi_pii-v1` | Zero-shot multilingual, ~278M params |
| **deberta** | `lakshyakh93/deberta_finetuned_pii` | English-only specialised |
| **piiranha** | `iiiorg/piiranha-v1-detect-personal-information` | Multilingual ~278M params |
| **presidio** | Microsoft Presidio 2.x analyzer | Regex + recognizer engine |
| **regex** | Built-in regex pack | URLs, emails, AWS/GitHub/Stripe/OpenAI keys, IBAN, SSN |
| **ensemble** | nullpii + gliner + regex | `primary` merge + boundary refinement |

## Datasets

Dev-focused: "developer pastes prod data into LLM" is the threat model.

- `nullpii-bench` — project-bundled (curated sentences + long real-world prompts)
- `bigcode-pii` — labelled secrets in source code
- `dev-prompts-synth` — local generator with planted PII
- `enron-planted`, `stackoverflow-planted`, `thestack-planted` —
  real text from Enron / StackExchange / The Stack with PII planted at
  known offsets

Span gold is exact in the planted datasets (we own the placement);
upstream gold otherwise.

## Reading the matrix

`matrix.csv` is the headline pivot (rows = datasets, columns = tools,
cells = F1). `matrix.json` carries the per-cell wall-clock and sample
count, `confusion.json` per-label TP/FP/FN.

## Qualitative comparison

Numerical F1 only catches half of the picture — span boundaries matter
for downstream redaction. See
`packages/eval/results/train/qualitative_compare.md` for a 30-case
side-by-side across four models: `openai/privacy-filter` via the
default `transformers.pipeline()` (`aggregation_strategy="simple"`),
`openai/privacy-filter` with a Python BIOES decoder, the `gliner`
zero-shot baseline, and our fine-tuned `nullpii`. Inputs are 20 short
prompts (real-world patterns + adversarial edge cases) and 10 longer
documents (medical records, contracts, bank statements, deposition
transcript, multilingual itineraries). All fake.

> **Important fairness note** (and a partial correction). The
> `openai/privacy-filter` model card explicitly says inference is
> supposed to apply a **constrained Viterbi BIOES decoder** with
> learned transition biases. There are two ways to actually run it
> with that decoder:
>
> 1. **Use the official `opf` CLI** from
>    [`github.com/openai/privacy-filter`](https://github.com/openai/privacy-filter).
>    `pip install -e .` from that repo gives you `opf "Alice was born on
>    1990-01-02."`, which loads the model and applies the full Viterbi
>    decoder OpenAI ships in `opf/_core/`. This is the official path.
> 2. **Use nullpii's runtime**, which ships its own constrained Viterbi
>    BIOES decoder over the same upstream model — the historical reason
>    nullpii is designed around `openai/privacy-filter`.
>
> What does NOT work out of the box: the transformers integration that
> upstream HF added recently ships only the per-token logits — no
> Viterbi. Calling `transformers.pipeline()` with the default
> `aggregation_strategy="simple"` therefore aggregates tokens via naive
> same-base-label adjacency grouping (NOT BIOES-aware), and produces
> very fragmented spans (`.com`, `+1-843-555-014` then `2`, `aitre`).
> That is **not the model's intended output**, just what HF's default
> does with raw logits when the Viterbi step is missing.
>
> The bench in `qualitative_compare.py` ships an in-Python BIOES decoder
> (`predict_openai_bioes`) that strict-parses B/I/E/S transitions on the
> raw `argmax` outputs of the HF model. It still doesn't include the
> learned transition biases, so it's weaker than the official `opf` /
> nullpii Viterbi, but it respects boundaries and recovers most of the
> model's quality. Use it as a "no extra dependency" comparison row.

Headline (latency on 5090 GPU, 30 cases avg):

| model | avg latency | typical span shape on long docs |
| ----- | ----------: | ------------------------------- |
| openai HF pipeline (`agg=simple`) | ~230 ms | fragmented (`.com`, `aitre`, `Mr.`) |
| openai + Python BIOES decoder | ~207 ms | clean (`0xA9B4FF12`, `FR76 ... 184`) |
| gliner baseline (zero-shot) | ~26 ms | clean, broad coverage |
| nullpii (fine-tuned GLiNER) | ~33 ms | clean, tightest spans |

`openai/privacy-filter` is ~10× slower than the gliner-based models
because it's ~1.5B parameters vs ~278M.

### Cross-platform latency (nullpii models, same code, p50 ms over 30 cases)

| backend                   | RunPod 5090 (Linux x86) | Mac (M-series) |
| ------------------------- | ----------------------: | -------------: |
| pt-cuda                   | **14**                  | n/a            |
| pt-mps                    | n/a                     | 110            |
| pt-cpu                    | 147                     | 87             |
| onnx-cpu-fp32             | 799                     | **31**         |
| onnx-cpu-int4             | 691                     | 43             |
| onnx-coreml-fp32          | n/a                     | 121            |
| onnx-coreml-int4          | n/a                     | 128            |
| nullpii TS pipeline (cpu) | 103                     | 82             |

Two surprises worth flagging:

1. **ONNX Runtime CPU on Apple Silicon is ~25× faster** than ONNX
   Runtime CPU on Linux x86 for this model (31 ms p50 vs 799 ms p50).
   Apple's vendor-specific kernels are dramatically better at the
   token-classification matmul mix here than the generic upstream ORT
   build.
2. **INT4 (`MatMulNBitsQuantizer`) is NOT a CPU latency win.** It only
   reduces memory footprint (333→844 MB depending on quant scheme); the
   `MatMulNBits` op still has to dequantize at runtime, costing
   compute. Use INT4 when you're memory-constrained, not when you're
   latency-bound. PyTorch FP32 on CPU is faster than ONNX INT4 on the
   same CPU (Mac and Linux).

`bench_multiplatform_pod.json` and `bench_multiplatform_mac.json` carry
the full per-case detail for each backend.

### Worst-case test cases (where each model breaks)

The 30-case set in `qualitative_compare.md` is intentionally designed
to stress real failure modes. A few highlights:

- `japanese-date` / `japanese-mixed` — `openai/privacy-filter` does NOT
  detect non-Latin date formats (e.g. `1985年7月3日`, `平成元年4月15日`).
  This is a known limitation per the model card ("performance may drop
  on non-English text, non-Latin scripts"). Our nullpii fine-tune was
  trained on multilingual but not Japanese-heavy data, so it also
  misses these — flagged as future work.
- `markdown-table` — every model except nullpii over-tags the
  headers (`Name`, `Email`, `Phone`) as PII; nullpii under-tags
  (catches only some emails).
- `adversarial-code-looking-like-pii` — JS regex patterns get
  misclassified by the openai-bare HF pipeline; nullpii keeps it clean.
- `code-with-api-keys` — only models with explicit `secret` training
  signal (openai BIOES, nullpii TS, v2) detect the JWT / SK keys.

## Fine-tune details

`nullpii` is two rounds of fine-tune from `urchade/gliner_multi_pii-v1`:

1. **Round 1** — ai4privacy/pii-masking-300k + Isotonic/pii-masking-200k
   (en/de/fr/it). 6 epochs (early-stopped). Multilingual F1 jumped to
   0.93–0.94 but **dev-prompts-synth regressed** (0.62 → 0.43)
   because the training mix didn't include dev-style prompts.
2. **Round 2** — re-trained from the round-1 checkpoint on a mix
   that adds 30k dev-prompts-synth samples + halved learning rate +
   raised weight decay. 10 epochs (early-stop on epoch-8 best).
   dev-prompts-synth recovered to 0.82, multilingual stayed at 0.93+.

Quantization deltas (preview, n=100 per dataset, IoU ≥ 0.5):

| Variant | avg F1 | Size MB | p50 latency (CPU) |
| ------- | -----: | ------: | ----------------: |
| nullpii PT (CUDA) | 0.91 | 1102 | 14 ms (5090 GPU) |
| nullpii ONNX FP32 (CPU) | 0.91 | 1104 | 670 ms |
| nullpii ONNX INT4 (CPU) | **0.92** | 844 | 602 ms |
| nullpii ONNX INT8 (CPU) | 0.58 | **333** | 614 ms — **F1 collapse, avoid** |

INT4 (matmul-only nbits quant) actually beats FP32 marginally on F1;
INT8 dynamic quant is too lossy on this architecture.

## Reproduction

```bash
bash packages/eval/scripts/runpod/launch.sh
bash packages/eval/scripts/runpod/resume.sh medium  # ~3.5h, ~$5 on 5090
bash packages/eval/scripts/runpod/teardown.sh        # pulls results, terminates pod
```

Tunables (env vars on the pod):

- `BACKEND` — `cpu` (apple-to-apple sanity) or `cuda` (default for
  medium/full)
- `NULLPII_BACKEND` — defaults to `cpu` because ONNX Runtime CUDA EP MoE
  kernels lack Blackwell SM_120 support; switch to `cuda` on Ada (4090)
- `POOL_SIZE` — nullpii daemon pool (default 8)
- `PARALLEL` — concurrent ML tools per dataset (default 4)
