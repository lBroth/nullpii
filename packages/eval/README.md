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

Long-document handling differs by tool. Each tool runs with the
chunker its upstream maintainers ship with the model, not a
project-tuned one — there is no `nullpii`-favouring chunking:

| Tool | Chunker | Source |
|---|---|---|
| `nullpii` / `nullpii-bare` | word-based, 140 words / 30 overlap | upstream GLiNER `gliner_multi_pii-v1` model card recommendation, fits the 384-subword window |
| `gliner-onnx-pii-fp32`, `gliner-pii-large-v1` | char-based, 1400 / 200 overlap | upstream `gliner` package default (`predict_entities(..., chunk_size=1400)`) |
| `piiranha` | char-based, 1000 / 200 overlap | required to dodge the model's hard 256-token truncation (HuggingFace model card §Limitations) |
| `nemotron-pii-raw` | upstream GLiNER chunker | matches NVIDIA NIM container default |
| `deberta`, `presidio`, `openai-privacy-filter` | full text, internal upstream handling | each pipeline manages its own windowing |

Forcing every tool through a single normalised harness (e.g. fixed
1024-char windows everywhere) would mean: (a) `piiranha` truncates at
256 tokens and drops late-document spans, (b) DeBERTa loses its
`aggregation_strategy='first'` continuation behaviour, (c) Presidio
loses its NER+anchor coordination. The result would be lower F1 for
every baseline, hand-disadvantaged. The current bench measures each
tool as it ships, not a synthetic harness. Same setting is applied to
every benchmark cell — no cross-cell drift.

### Threshold parity

Every GLiNER-family tool (`nullpii`, `nullpii-bare`,
`gliner-onnx-pii-fp32`, `gliner-pii-large-v1`) runs at threshold
**0.5** for cross-tool parity. `nemotron-pii-raw` runs at **0.3** per
its [upstream model card](https://huggingface.co/nvidia/gliner-pii)
which prescribes 0.3 as the production decision boundary; running it
at 0.5 (parity) would drop its F1 by ~0.07 on average across the
matrix and disadvantage it relative to its published characteristic.
Both thresholds are disclosed in the README footnotes so readers can
mentally adjust for the framing.

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
