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

- **bench-bundled** — curated sentences shipped with the project (5
  locales).
- **bench-adversarial** — handcrafted edge cases from the iter-N
  exploration loop.
- **bench-long-prompts** — long real-world prompts that exercise
  chunking + Viterbi.
- **bigcode-pii** — gated `bigcode/bigcode-pii-dataset` with labelled
  secrets and emails inside source code.
- **dev-prompts-synth** — local generator (`_generate_dev_prompts`),
  10k+ templates with planted PII at known offsets.
- **enron-planted** — real Enron Email Corpus + planted PII (gold
  positions exact).
- **stackoverflow-planted** — StackExchange CC-BY-SA archive +
  planted PII.
- **thestack-planted** — `bigcode/the-stack-smol` Python+JS files +
  planted secrets.

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

- **nullpii** (npm package) — `openai/privacy-filter` ONNX + chunking
  + constrained Viterbi BIOES + recognizer post-pass.
- **openai (bare HF)** — same upstream model, default `transformers.pipeline()`
  decoder. Isolates what the nullpii runtime adds.
- **gliner** — `urchade/gliner_multi_pii-v1`, zero-shot multilingual,
  ~278M params.
- **deberta** — `lakshyakh93/deberta_finetuned_pii`, English-only.
- **piiranha** — `iiiorg/piiranha-v1-detect-personal-information`,
  multilingual, ~278M params.
- **presidio** — Microsoft Presidio 2.x (analyzer only).
- **regex** — built-in regex pack (URL, email, AWS/GitHub/Stripe/OpenAI
  keys, IBAN, SSN). Pure CPU.
- **ensemble** — nullpii + gliner + regex with `primary` merge strategy
  + boundary refinement.

Span match policy: partial-match IoU ≥ 0.5 (CoNLL/MUC standard).
