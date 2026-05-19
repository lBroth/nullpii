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
  --tools nullpii,nullpii-bare,presidio,nemotron-pii-raw,piiranha,deberta,gliner-onnx-pii-fp32,gliner-pii-large-v1 \
  --datasets all \
  --max-per-dataset 5000 --parallel-tools 1 \
  --backend cpu \
  --out-dir results/$(date +%Y%m%d)-bench
```

Output: `matrix.json` (per-cell F1 / wall / throughput) + `matrix.csv` (pivot). Override caps with `--max-per-dataset N` or `--no-cap`. Macro F1 uses the sklearn convention — labels with no ground-truth support are excluded from the macro average; the same coercion applies to every tool, no asymmetry. All third-party tools run bare — no `nullpii` post-processing is applied to their predictions.

### Chunking strategies

Long-document handling differs by tool, by design:
- **`nullpii` / `nullpii-bare`**: word-based chunker, 140 words / 30-word overlap, capped to fit the GLiNER 384-subword window.
- **Upstream GLiNER baselines** (`gliner-onnx-pii-fp32`, `gliner-pii-large-v1`): char-based, 1400 chars / 200-char overlap.
- **Piiranha**: char-based 1000 / 200 to dodge its 256-token truncation.
- **DeBERTa**, **Presidio**, **OPF**: full text passed to upstream pipeline (each does its own internal handling).
This is an intentional fair-comparison gap — each tool gets its upstream-recommended chunking; cross-tool F1 on long-doc datasets reflects the package as it ships, not a normalised harness. Same setting is applied to every benchmark cell.

## Reproduce latency

```bash
python -u scripts/bench_latency.py \
  --backend cpu --sizes 100 1000 10000 --n-per-size 50 \
  --out results/latency-$(date +%Y%m%d)
```

## Other scripts

- `scripts/confusion_report.py` — per-class precision/recall/F1 markdown report from `bench_full.py --confusion` output
- `scripts/failure_analysis.py` — top-K FN/FP per label per tool
- `scripts/report_per_class.py` — per-label precision/recall breakdown
- `scripts/verify_claims.py` — re-run vendor numbers on each tool's native test split + native label vocabulary (presidio, gliner-pii-base, piiranha, nemotron-pii-raw); span IoU ≥ 0.5
- `scripts/generate_bench_rows.py` — deterministic project-bench row generator
- `scripts/reannotate_underanno_rows.py` — regex-only enrichment pass for under-labelled rows

## Bundled datasets

`datasets/` — Apache 2.0, no real PII. See [`datasets/README.md`](datasets/README.md) for schema. Three files live there at HEAD: `nullpii-bench.jsonl` (project-authored), `presidio-synthetic.jsonl` (external, MIT), `tab-echr-test.jsonl` (external, MIT). All other bench rows (`ai4privacy-*`, `isotonic-*`, `nemotron-pii-*`, `argilla-pii`) are fetched from HuggingFace at bench time.

## Model card

[`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) — intended use, limitations, licence.
