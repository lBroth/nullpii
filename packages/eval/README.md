# nullpii eval

Bench reproduction kit for `nullpii`. Python 3.12. Not part of the npm publish surface.

## Setup

```bash
cd packages/eval
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[presidio]" presidio-evaluator datasets
```

## Reproduce the bench

```bash
NULLPII_MODEL_DIR=/path/to/lBroth-nullpii \
python -u scripts/bench_full.py \
  --tools nullpii,nullpii-bare,presidio,nemotron-pii-raw,piiranha,deberta,gliner-onnx-pii-fp32,gliner-pii-large-v1,openai-privacy-filter \
  --datasets all \
  --max-per-dataset 5000 --parallel-tools 1 \
  --backend cpu \
  --out-dir results/$(date +%Y%m%d)-bench
```

Output: `matrix.json` (per-cell F1 / wall / throughput) + `matrix.csv` (pivot). Override caps with `--max-per-dataset N` or `--no-cap`. Macro F1 uses the sklearn convention — labels with no ground-truth support are excluded from the macro average; the same coercion applies to every tool, no asymmetry. All third-party tools run bare — no `nullpii` post-processing is applied to their predictions.

## Reproduce latency

```bash
python -u scripts/bench_latency.py \
  --backend cpu --sizes 100 1000 10000 --n-per-size 50 \
  --out results/latency-$(date +%Y%m%d)
```

## Other scripts

- `scripts/confusion_report.py` — cross-tool confusion matrix from `matrix.json`
- `scripts/failure_analysis.py` — top-K FN/FP per label per tool
- `scripts/report_per_class.py` — per-label precision/recall breakdown
- `scripts/verify_claims.py` — `CLAIM-VERIFIER-01`: re-run Presidio / piiranha vendor numbers under span IoU ≥ 0.5
- `scripts/generate_bench_rows.py` — deterministic project-bench row generator
- `scripts/reannotate_underanno_rows.py` — regex-only enrichment pass for under-labelled rows

## Bundled datasets

`datasets/` — Apache 2.0, no real PII. See [`datasets/README.md`](datasets/README.md) for schema. Three files live there at HEAD: `nullpii-bench.jsonl` (project-authored), `presidio-synthetic.jsonl` (external, MIT), `tab-echr-test.jsonl` (external, MIT). All other bench rows (`ai4privacy-*`, `isotonic-*`, `nemotron-pii-*`, `argilla-pii`) are fetched from HuggingFace at bench time.

## Model card

[`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) — intended use, limitations, licence.
