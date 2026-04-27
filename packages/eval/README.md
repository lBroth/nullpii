# nullpii eval

Reproducible accuracy + benchmark suite. Two outputs:

1. `accuracy.json` — per-category precision/recall/F1 vs ground truth
2. `benchmark.json` — head-to-head latency / throughput vs Microsoft Presidio

## Datasets

Bundled, version-controlled, and synthetic-only — no real PII, no
gated downloads, no flaky CI.

| File                              | Locale | Size   | Notes                                              |
| --------------------------------- | ------ | -----: | -------------------------------------------------- |
| `datasets/en-baseline.jsonl`      | en     |    100 | English baseline. 8 categories, balanced.          |
| `datasets/it-baseline.jsonl`      | it     |    100 | Italian — names, indirizzi, codice fiscale.        |
| `datasets/de-baseline.jsonl`      | de     |     50 | German — Umlaut + compounds.                       |
| `datasets/fr-baseline.jsonl`      | fr     |     50 | French — accents.                                  |
| `datasets/es-baseline.jsonl`      | es     |     50 | Spanish.                                           |
| `datasets/adversarial.jsonl`      | en     |     30 | Decoy strings that look like PII but aren't.       |

Each line is `{ "text": "...", "spans": [{ "label": "...", "start": ..., "end": ... }] }`.

## Run

```bash
cd packages/eval
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[presidio]" presidio-evaluator datasets
for m in en_core_web_lg it_core_news_lg de_core_news_lg fr_core_news_lg es_core_news_lg; do
  python -m spacy download "$m"
done
```

### Smoke vs full

Two convenience scripts under `scripts/`:

| Script             | Caps                                              | Time (Apple M, single-thread) | Use                          |
| ------------------ | ------------------------------------------------- | ----------------------------- | ---------------------------- |
| `eval_smoke.sh`    | 200 isotonic, 200 wikiann, 500 presidio-synthetic | ~5 min                        | CI / dev iteration           |
| `eval_full.sh`     | no caps — full dataset splits                     | ~3-4h                         | release benchmark, published |

```bash
# Smoke (fast, numbers NOT for publication)
./scripts/eval_smoke.sh
# → out/smoke/{bundled,isotonic,presidio-syn,wikiann}-*.json

# Full (publishable numbers)
./scripts/eval_full.sh
# → out/full/...
```

Both scripts honor `OUT_DIR=...` to redirect output.

### Individual runs

```bash
# Accuracy on bundled datasets
python -m nullpii_eval.run_accuracy --out accuracy.json

# Head-to-head — omit --max-samples for full split
python -m nullpii_eval.run_compare \
  --out compare.json --dataset isotonic/pii-masking-200k --locale en

# Smoke (cap)
python -m nullpii_eval.run_compare \
  --out compare.json --dataset isotonic/pii-masking-200k --locale en --max-samples 200

# Latency benchmark
python -m nullpii_eval.run_benchmark --out benchmark.json
```

## Reports

Numbers feed `BENCHMARK.md` and `docs/guide/vs-presidio.md`. Update via:

```bash
python -m nullpii_eval.render_tables \
  --accuracy accuracy.json \
  --compare compare.json \
  --benchmark benchmark.json \
  --out ../../docs/guide/eval-results.md
```
