# Comparisons

Tool-vs-tool numbers on the dev-focused bench suite. The same input
goes to every tool, F1 is partial-match (IoU ≥ 0.5), latency is
per-call wall-clock. See `packages/eval/results/runpod-YYYYMMDD/matrix.csv`
for the live tabulation. Reproduction recipe at the bottom.

## Tools in the matrix

| Tool | Source | Notes |
|------|--------|-------|
| **nullpii** | `openai/privacy-filter` ONNX + nullpii pipeline | Chunking + constrained Viterbi BIOES + recognizers |
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

`matrix.csv` is a pivot: rows = datasets, columns = tools, cells = F1.
Crashed cells render as `CRASHED` (string) — never silently empty.
`matrix.json` carries the full record per cell:

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

`confusion.json` has per-label TP/FP/FN per cell when the bench is run
with `--confusion` (default in `bench-on-pod.sh`).

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
