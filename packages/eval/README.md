# nullpii eval

Bench reproduction kit for `nullpii` v0.1.0. Python 3.12, gitignored —
not part of the npm publish surface. Powers the canonical 10-dataset
hobby-bench published at [`packages/eval/published-bench/matrix.csv`](published-bench/matrix.csv).

Training scripts + internal journal live under `packages/eval/private/`
(local-only, not part of this release surface).

## Setup

```bash
cd packages/eval
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[presidio]" presidio-evaluator datasets
```

## Reproduce the bench

`scripts/bench_full.py` runs a `tool × dataset` matrix with checkpoint
resume. Output: `matrix.json` (per-cell F1 / wall / throughput) +
`matrix.csv` (pivot).

```bash
# Canonical hobby-bench: 8 tools × 10 datasets, Mac CPU.
# NULLPII_MODEL_DIR points the nullpii subprocess at a staged model dir
# (defaults to ~/.cache/nullpii on first run if unset).
NULLPII_MODEL_DIR=/tmp/nullpii-stack-test \
python -u scripts/bench_full.py \
  --tools nullpii,nullpii-v10-router-embedding,presidio,nemotron-pii-raw,piiranha,deberta,gliner-onnx-pii-fp32,gliner-pii-large-v1 \
  --datasets nullpii-bench,tab-echr,nemotron-pii-test,presidio-synthetic,ai4privacy-300k-heldout-v10,isotonic-en-heldout-v10,isotonic-de-heldout-v10,adversarial-typo,adversarial-unicode,adversarial-code \
  --backend cpu \
  --out-dir results/$(date +%Y%m%d)-bench
```

Override caps with `--max-per-dataset N` (global cap) or `--no-cap`
(full). Single-tool re-run: `--tools nullpii-v10-router-embedding`.

### Tool surface (8 rows)

`nullpii` (subprocess of the local npm build, the canonical user-facing
row) + `nullpii-v10-router-embedding` (Python re-impl of the same
pipeline, sanity check) + bare third-party baselines:

- **Microsoft Presidio** (`presidio`)
- **NVIDIA Nemotron-PII** raw (`nemotron-pii-raw`)
- `iiiorg/piiranha` (`piiranha`)
- **Microsoft DeBERTa**-v3 community fine-tune (`deberta`)
- GLiNER ONNX FP32 (`gliner-onnx-pii-fp32`)
- `gliner-pii-large-v1` (knowledgator, popular HF)

Bare-mode contract: no nullpii post-processing leaks into competitor
rows. Only universal NER-bench plumbing (1400/200 char chunking +
per-tool label remap to nullpii's 8-class). See
[`COMPETITIVE_ANALYSIS.md`](../../COMPETITIVE_ANALYSIS.md) for full
methodology.

### Dataset surface (10 rows)

| Dataset | Source | Bucket |
|---|---|---|
| `nullpii-bench` | bundled (`datasets/nullpii-bench.jsonl`) | in-distribution disclosed |
| `tab-echr` | bundled (`datasets/tab-echr-test.jsonl`) | in-distribution disclosed |
| `nemotron-pii-test` | HF `nvidia/Nemotron-PII` test split | in-distribution disclosed |
| `presidio-synthetic` | HF `presidio-research/presidio-synthetic` | held-out non-adversarial |
| `ai4privacy-300k-heldout-v10` | HF `ai4privacy/pii-masking-300k` offset 100k+ | held-out non-adversarial |
| `isotonic-en-heldout-v10` | HF `Isotonic/pii-masking-200k` offset 200k+ | held-out non-adversarial |
| `isotonic-de-heldout-v10` | HF `Isotonic/pii-masking-200k` offset 200k+ | held-out non-adversarial |
| `adversarial-typo` | bundled (`datasets/nullpii-adversarial.jsonl`) | adversarial preprocessor |
| `adversarial-unicode` | bundled | adversarial preprocessor |
| `adversarial-code` | bundled | adversarial preprocessor |

See [`datasets/README.md`](datasets/README.md) for the full bundled
inventory.

## Other scripts

| Script | Purpose |
|---|---|
| `scripts/bench_latency.py` | Per-tool latency p50/p95 measurements |
| `scripts/bench_openai_decoders.py` | Reference comparison: naive HF / BIOES / Viterbi delta on `openai/privacy-filter` (competitor, not nullpii's base) |
| `scripts/confusion_report.py` | Cross-tool confusion matrix from `matrix.json` |
| `scripts/failure_analysis.py` | Top-K FN/FP per label per tool |
| `scripts/report_per_class.py` | Per-label precision/recall breakdown |
| `scripts/verify_claims.py` | `CLAIM-VERIFIER-01` — re-run Presidio / piiranha vendor numbers under standard methodology (span IoU ≥ 0.5, label-agnostic, seqeval) |
| `scripts/release/` | HF push pipeline (CI-only — `push-to-hf.sh` + ONNX export utilities) |

## Bundled datasets

`datasets/` (Apache 2.0, project-internal — see
[`datasets/README.md`](datasets/README.md) for full inventory + schema).

| File | Rows | In canonical 10? |
|---|--:|:---:|
| `nullpii-bench.jsonl` | 271 | ✅ |
| `tab-echr-test.jsonl` | 127 | ✅ |
| `nullpii-adversarial.jsonl` | 480 | ✅ (typo/unicode/code subsets) |
| `nullpii-adversarial-textattack.jsonl` | 1670 | ❌ |
| `dev-paste-synth-train.jsonl` | ~20k | training-only |
| `cc-negative-25k.jsonl` | 25k | training-only |
| `cc-negative-200-test.jsonl` | 200 | diagnostics-only |

External datasets (loaded on demand by `nullpii_eval.public_datasets`):
`ai4privacy/pii-masking-300k`, `Isotonic/pii-masking-200k`,
`nvidia/Nemotron-PII`, `presidio-research/presidio-synthetic`,
`argilla/textcat-tokencat-pii-per-domain`.

## Model card

HF Hub: [`lBroth/nullpii-v10-router-embedding`](https://huggingface.co/lBroth/nullpii-v10-router-embedding) — training data composition, intended use, limitations, in-distribution disclosures.
