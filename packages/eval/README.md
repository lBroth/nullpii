# nullpii eval

Bench reproduction kit for `nullpii` v0.1.0. Python 3.12, gitignored — not part of the npm publish surface.

## Setup

```bash
cd packages/eval
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[presidio]" presidio-evaluator datasets
```

## Reproduce the bench

```bash
NULLPII_MODEL_DIR=/tmp/nullpii-stack-test \
python -u scripts/bench_full.py \
  --tools nullpii,presidio,nemotron-pii-raw,piiranha,deberta,gliner-onnx-pii-fp32,gliner-pii-large-v1 \
  --datasets nullpii-bench,tab-echr,nemotron-pii-test,presidio-synthetic,ai4privacy-300k-heldout,isotonic-en-heldout,isotonic-de-heldout,adversarial-typo,adversarial-unicode,adversarial-code \
  --backend cpu --confusion \
  --out-dir results/$(date +%Y%m%d)-bench
```

Output: `matrix.json` (per-cell F1 / wall / throughput) + `matrix.csv` (pivot). Override caps with `--max-per-dataset N` or `--no-cap`. Methodology + bare-mode contract: [`COMPETITIVE_ANALYSIS.md`](../../COMPETITIVE_ANALYSIS.md).

## Reproduce latency

```bash
python -u scripts/bench_latency.py --profiles nullpii-router-embedding \
  --backend cpu --sizes 100 1000 10000 --n-per-size 50 \
  --out results/latency-$(date +%Y%m%d)
```

## Other scripts

- `scripts/confusion_report.py` — cross-tool confusion matrix from `matrix.json`
- `scripts/failure_analysis.py` — top-K FN/FP per label per tool
- `scripts/report_per_class.py` — per-label precision/recall breakdown
- `scripts/verify_claims.py` — `CLAIM-VERIFIER-01`: re-run Presidio / piiranha vendor numbers under span IoU ≥ 0.5
- `scripts/release/` — HF push pipeline (CI only)

## Bundled datasets

`datasets/` — Apache 2.0, no real PII, see [`datasets/README.md`](datasets/README.md) for schema + per-file detail. Canonical bench files: `nullpii-bench.jsonl`, `tab-echr-test.jsonl`, `nullpii-adversarial.jsonl` (typo/unicode/code subsets). External datasets loaded on demand: `ai4privacy/pii-masking-300k`, `Isotonic/pii-masking-200k`, `nvidia/Nemotron-PII`, `presidio-research/presidio-synthetic`.

## Model card

HF Hub: [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) — training data composition, intended use, limitations, in-distribution disclosures.
