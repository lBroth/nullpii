# Eval results

Live numbers ship from `packages/eval/results/runpod-YYYYMMDD/matrix.csv`
+ `matrix.json`, produced by `packages/eval/scripts/bench_full.py`. The
bench runs on a RunPod 5090 host (CUDA mix, nullpii forced CPU due to
ONNX Runtime Blackwell SM_120 MoE limitation — see
`packages/eval/scripts/runpod/README.md`).

## How to read

`matrix.json` shape:

```json
{
  "<dataset>": {
    "<tool>": {
      "status": "OK" | "CRASHED",
      "f1": 0.xxx,
      "wall_s": 12.3,
      "n": 1000,
      "samples_per_s": 81.3
    }
  }
}
```

A `status: "CRASHED"` cell carries `error: "<type>: <message>"` and a
null F1 — never a silent default. `_load_error` keys at the dataset
level surface upstream loader failures.

## Datasets in the suite

The bench is dev-focused — "developer pastes prod data into LLM" is the
threat model — and ships these datasets:

- **nullpii-bench** — project-bundled, ~264 samples merging the
  `bundled` (curated 5-locale sentences) and `long-prompts` (real
  long inputs that exercise chunking + Viterbi) subsets.
- **dev-prompts-synth** — local generator (`_generate_dev_prompts`),
  fully synthetic templates with PII planted at known offsets
  (Apache 2.0).
- **enron-planted** — real Enron Email Corpus (FERC public-domain)
  + planted PII (gold positions exact).
- **stackoverflow-planted** — StackExchange CC-BY-SA archive +
  planted PII (gold positions exact).

## How to reproduce

```bash
# 1. Spin up a RunPod 5090 (Secure cloud, on-demand)
bash packages/eval/scripts/runpod/launch.sh

# 2. Sync code + run the bench in `medium` mode (~3.5h)
bash packages/eval/scripts/runpod/resume.sh medium

# 3. Pull results back, then terminate the pod
bash packages/eval/scripts/runpod/teardown.sh
```

Outputs land in `packages/eval/results/runpod-YYYYMMDD/`: `matrix.json`,
`matrix.csv`, `confusion.json` (per-label TP/FP/FN), `run.log`.

## Tools compared

- **nullpii** (npm package, full pipeline) — `openai/privacy-filter` ONNX
  + chunking + constrained Viterbi BIOES + recognizer post-pass + gliner
  zero-shot pass + regex secrets, merged with `primary` strategy +
  boundary refinement.
- **openai (bare)** — same upstream `openai/privacy-filter` model run
  via the default `transformers.pipeline()` with
  `aggregation_strategy="simple"`. **Caveat**: the model card describes
  inference as applying a constrained Viterbi BIOES decoder; the
  transformers integration ships only per-token logits, so `simple`
  aggregation is naive same-base-label adjacency grouping (no boundary
  enforcement) and spans look fragmented. This row is the fair
  "naive HF usage" baseline, not the model's intended quality. The
  intended quality is reachable in two ways: (a) the official `opf`
  CLI from
  [`github.com/openai/privacy-filter`](https://github.com/openai/privacy-filter)
  which ships the full Viterbi decoder, or (b) nullpii's runtime
  (the `nullpii` row above), which also implements that decoder.
  `docs/guide/comparisons.md` adds a third row using a small Python
  BIOES decoder that recovers most of the gap with no extra
  dependency.
- **gliner** — `urchade/gliner_multi_pii-v1`, zero-shot multilingual,
  ~278M params.
- **deberta** — `lakshyakh93/deberta_finetuned_pii`, English-only.
- **piiranha** — `iiiorg/piiranha-v1-detect-personal-information`,
  multilingual, ~278M params.
- **presidio** — Microsoft Presidio 2.x (analyzer only).
- **regex** — built-in regex pack (URL, email, AWS/GitHub/Stripe/OpenAI
  keys, IBAN, SSN). Pure CPU.

Span match policy: partial-match IoU ≥ 0.5 (CoNLL/MUC standard).

## Latest run — RunPod 5090, 2026-04-28

Sources:

- `packages/eval/results/runpod-20260428-5090/matrix.{json,csv}` —
  primary, latest 5090 run.
- `packages/eval/results/runpod-20260428-medium-mixed-partial/matrix.json` —
  earlier same-day run, used only for the `isotonic-*` rows missing
  from the primary run.

Hardware: RTX 5090 host (CUDA mix; nullpii forced CPU due to ONNX Runtime
Blackwell SM_120 limitation).

### F1 by dataset × tool

| Dataset | nullpii | gliner | openai (bare) | piiranha | presidio | deberta | regex |
| ------- | ------: | -----: | ------------: | -------: | -------: | ------: | ----: |
| nullpii-bench (n=264) | **0.777** | 0.695 | 0.427 | 0.357 | 0.392 | 0.316 | 0.339 |
| dev-prompts-synth (n=30000) | **0.697** | 0.688 | 0.439 | 0.527 | 0.333 | 0.359 | 0.190 |
| bench-bundled (n=201) | **0.846** | 0.715 | 0.488 | 0.359 | 0.474 | 0.366 | 0.340 |
| bench-long-prompts (n=61) | **0.692** | 0.621 | 0.354 | 0.352 | 0.348 | 0.000 | 0.340 |
| isotonic-en (n=8000) | 0.621 | 0.605 | 0.314 | — | 0.472 | **0.753** | 0.275 |
| isotonic-de (n=8000) | **0.624** | 0.603 | 0.382 | 0.564 | 0.400 | 0.489 | 0.278 |
| isotonic-fr (n=8000) | **0.607** | 0.591 | 0.380 | 0.568 | 0.417 | 0.568 | 0.279 |
| isotonic-it (n=8000) | **0.623** | 0.596 | 0.385 | 0.572 | 0.416 | 0.540 | 0.278 |

`nullpii` here = the full pipeline (`openai/privacy-filter` ONNX +
chunking + Viterbi + recognizer + gliner zero-shot pass + regex secrets).
The bare upstream model is shown as `openai (bare)` for reference.

The `isotonic-*` rows come from the partial mixed run (same hardware,
earlier same day, smaller `n=8000` sample). `isotonic-es` and a piiranha
cell on `isotonic-en` are missing — pending a complete re-run. `deberta`
wins `isotonic-en` because the Isotonic-200k English split overlaps the
training distribution of `lakshyakh93/deberta_finetuned_pii` (English-only
fine-tune); read it as a domain-overlap signal, not a generalization
ranking.

### Throughput (samples/s, dev-prompts-synth, n=30000)

| Tool      | samples/s |
| --------- | --------: |
| regex     | 26,358 |
| presidio  | 71 |
| piiranha  | 34 |
| deberta   | 29 |
| gliner    | 6.0 |
| openai (bare) | 4.5 |
| nullpii   | 3.4 |

Throughput on CPU. nullpii (full pipeline) is slowest because it runs
the privacy-filter model + gliner + regex serially, but tops every
realistic dataset on F1.

### Takeaways

- **nullpii** (full pipeline) wins every realistic dataset (0.70–0.85 F1)
  at ~3.4 samples/s.
- **+0.35 F1** over the bare `openai/privacy-filter` baseline on
  nullpii-bench (0.78 vs 0.43) — quantifies what the full pipeline adds.
- **gliner** is the closest standalone competitor (0.69 vs nullpii 0.78).
- **regex** is fastest by 4 orders of magnitude but caps at ~0.34 F1 on
  realistic prompts; useful as a structured-secret pre-pass, not standalone.
- **deberta**, **piiranha**, **presidio** all underperform on the dev-
  paste threat model the suite targets.

## nullpii (fine-tuned GLiNER) (preview)

A two-round fine-tune of `urchade/gliner_multi_pii-v1` on a mix of
`ai4privacy/pii-masking-300k`, `Isotonic/pii-masking-200k` (en/de/fr/it),
and our `dev-prompts-synth` generator. Round 1 specialised on
ai4privacy + isotonic and lost dev-synth quality; round 2 added dev-synth
to the training mix and recovered it without giving back the multilingual
gains. Best checkpoint = epoch 8 (eval_loss 1.528).

Source: `packages/eval/results/train/variant_bench_v2.json` (cap=100
per dataset — preview, full bench pending). Ran on the same 5090 host.

### F1 (n=100 per dataset)

| Dataset | baseline gliner | nullpii-pt-cuda | nullpii-onnx-int4 |
| ------- | --------------: | ---------: | -----------: |
| isotonic-en | 0.462 | 0.951 | **0.961** |
| isotonic-de | 0.497 | 0.932 | **0.939** |
| isotonic-fr | 0.477 | 0.947 | **0.967** |
| isotonic-it | 0.509 | 0.938 | **0.959** |
| ai4privacy-300k | 0.309 | 0.800 | **0.864** |
| dev-prompts-synth | 0.618 | 0.821 | 0.801 |

### Latency + size

| Variant | p50 ms | Size MB | Backend |
| ------- | -----: | ------: | ------- |
| nullpii-pt-cuda | 14 | 1102 | CUDA (RTX 5090) |
| nullpii-onnx-fp32 | 670 | 1104 | CPU |
| nullpii-onnx-int4 | 602 | 844 | CPU |
| nullpii ONNX INT8 | 614 | 333 | CPU (F1 collapse, avoid) |

### Takeaways (preview)

- **nullpii beats baseline GLiNER by +0.45–0.55 F1** on every multilingual
  dataset.
- **INT4 quantization matches or BEATS the FP32 model** on F1 (matmul-
  only quant smooths the round-1 overfit). Best CPU production option.
- **INT8 dynamic quant collapses** (avg F1 ~0.58) — too lossy.
- **dev-prompts-synth recovered** vs round-1 (0.43 → 0.82) by mixing
  dev-synth into the training set.
- Numbers are preview-grade (n=100) — full bench against the same
  datasets as the base table is pending.
