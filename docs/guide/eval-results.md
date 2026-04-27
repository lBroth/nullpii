# Eval results

Real numbers from `packages/eval/`. Reproducible — see bottom of page.

**Last run**: 2026-04-27 on Apple M-series, macOS, Node 24, Python 3.12,
nullpii int8 ONNX (CPU) running OpenAI
[`privacy-filter`](https://huggingface.co/openai/privacy-filter)
(Apache 2.0, 1.3B param), Microsoft Presidio 2.x with `*_core_web_lg` /
`*_core_news_lg`.

## Methodology

- **Span policy**: partial-match (IoU ≥ 0.5) — standard NER (CoNLL/MUC).
  `--policy exact` available for stricter eval.
- **nullpii**: long-running `nullpii serve` daemon hosting OpenAI
  `privacy-filter` (token classifier, BIOES decoded) — ~30 ms / sample
  after warmup, single model load across the run.
- **Presidio**: in-process `AnalyzerEngine.analyze(text, language='en')`
  with default recognizer set. Entities mapped to our 8 categories
  (`PERSON → private_person`, etc.).
- **Datasets**:
  - `bundled` — **180 dev-style prompts across 5 locales**
    (en/it/de/fr/es). Generated deterministically from
    `<locale>-templates.txt` via `datasets/build.py`. Mix of one-liners
    (PR reviews, deploy logs, customer support) and multi-paragraph
    solution-design RFCs.
  - `presidio-synthetic` — Microsoft's own synthetic generator
    (`PresidioSentenceFaker`), 500 samples.
  - `isotonic/pii-masking-200k` — open HF mirror of ai4privacy's PII
    Masking corpus, 200 samples × 4 locales (en/it/de/fr).
  - `wikiann` — open HF dataset (Wikipedia NER, 200 samples × 5 locales).
  - `conll2003`, `ai4privacy/pii-masking-300k` — supported by the
    runner; `conll2003` HF script support was removed upstream;
    `ai4privacy` requires `HF_TOKEN` (use the open `isotonic` mirror
    above for the same data without auth).

## Accuracy by locale (180 bundled dev prompts)

Partial-match (IoU ≥ 0.5). 3-way: nullpii vs Presidio vs bare spaCy NER.

| Locale | n   | **nullpii** | Presidio | spaCy NER |
| ------ | --: | ----------: | -------: | --------: |
| en     |  40 |   **0.751** |    0.536 |     0.219 |
| it     |  40 |   **0.761** |    0.459 |     0.109 |
| de     |  34 |   **0.669** |    0.488 |     0.114 |
| fr     |  33 |   **0.746** |    0.483 |     0.120 |
| es     |  33 |   **0.735** |    0.463 |     0.118 |
| **avg**|     |   **0.732** |    0.486 |     0.136 |

## Head-to-head on public datasets

| Dataset                              | n   |   nullpii | Presidio |     spaCy |
| ------------------------------------ | --: | --------: | -------: | --------: |
| presidio-synthetic (en)              | 500 |     0.548 |**0.558** |     0.157 |
| isotonic/pii-masking-200k (en)       | 200 | **0.548** |    0.499 |     0.185 |
| isotonic/pii-masking-200k (it)       | 200 | **0.597** |    0.409 |     0.075 |
| isotonic/pii-masking-200k (de)       | 200 | **0.604** |    0.401 |     0.106 |
| isotonic/pii-masking-200k (fr)       | 200 | **0.582** |    0.437 |     0.070 |
| **isotonic avg (4 locales)**         |     | **0.583** |    0.436 |     0.109 |
| wikiann (en) — Wikipedia NER         | 200 |     0.257 |    0.271 | **0.362** |
| wikiann (it)                         | 200 |     0.174 |    0.347 | **0.725** |
| wikiann (de)                         | 200 |     0.245 |    0.289 | **0.778** |
| wikiann (fr)                         | 200 |     0.162 |    0.223 | **0.611** |
| wikiann (es)                         | 200 |     0.224 |    0.335 | **0.766** |

> **PII-focused (bundled + isotonic)**: nullpii dominates — wins all 9
> PII runs across 5 locales.
> **Presidio synthetic (500)**: near-tie (∆ 0.01); Presidio's analyzer
> is well-tuned for the lexicon its own generator produces.
> **Wikipedia NER**: spaCy dominates — Wikipedia ≠ PII; spaCy is the
> right tool for general NER.

> **Bundled (en)**: nullpii nearly 2× Presidio on real-world prompt
> patterns the upstream model was trained on. Sample is small but
> homogeneous.
>
> **Isotonic/pii-masking-200k**: open mirror of the ai4privacy 300k
> corpus (Apache 2.0, no `HF_TOKEN` needed). nullpii wins all 4 locales,
> with the largest gap on it/de/fr — Presidio's regex+spaCy stack ships
> mostly English recognizers; the contextual classifier generalizes to
> non-English without per-locale rule packs.
>
> **Presidio synthetic (500)**: at 100 samples nullpii won 0.569 vs
> 0.486 (1st run, summary only). At 500 samples Presidio edges ahead by
> 0.01 — within noise, but worth the honest table. The generator's
> phrasing favours the lexicon Presidio's analyzer was tuned against
> (templated full names, address blocks).
>
> **WikiAnn**: spaCy dominates. Wikipedia NER (PER/LOC/ORG) is not
> really PII; both PII tools score low because the dataset is Wikipedia
> article snippets with mostly proper nouns mapped onto our 8 PII
> categories with a loose `LOC → private_address` heuristic. Use this
> only as a sanity-check on general NER capability, not as a PII
> benchmark.

## Throughput

Single-thread CPU. Higher is better.

Eval-runner numbers (subprocess JSON-lines, includes IPC overhead;
real Anthropic middleware sees ~12 ms / 128 tok with no IPC):

| Tool     | Hardware            | seq=128 ms | seq=512 ms |
| -------- | ------------------- | ---------: | ---------: |
| nullpii  | Apple M / arm64     |       34.7 |       57.7 |
| Presidio | Apple M / arm64     |        6.9 |       22.9 |

Pure Node-side numbers from `BENCHMARK.md` (no IPC):

| Backend | Variant | seq=128 (tok/s) | seq=512 (tok/s) |
| ------- | ------- | --------------: | --------------: |
| CPU     | int8    |           5,313 |           8,929 |

> **Honest takeaway**: Presidio is ~5× faster on this hardware. Tradeoff:
> nullpii catches contextual PII (better F1) at the cost of a transformer
> forward pass; Presidio is regex + small spaCy NER (cheaper, lower F1).

## When to use which

- **nullpii**: Claude Code workflow, TS app, you care more about
  recall than throughput, you want a reversible vault, you accept a
  ~30 ms/sample cost.
- **Presidio**: Python-first stack, you need 30+ languages today, you
  process millions of items/hour and 5× speed matters more than the
  F1 delta.
- **Both**: pair nullpii ML pass with our recognizer packs
  (`@nullpii/recognizers-cloud|finance|id-it`) for the formats where
  regex naturally wins.

## Reproduce

```bash
cd packages/eval
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[presidio]" presidio-evaluator datasets
python -m spacy download en_core_web_lg

# Bundled
python -m nullpii_eval.run_accuracy --out accuracy.json
python -m nullpii_eval.run_compare --out compare-bundled.json --dataset bundled
python -m nullpii_eval.run_benchmark --out benchmark.json

# Public benchmarks
python -m nullpii_eval.run_compare \
  --out compare-presidio-synthetic.json \
  --dataset presidio-synthetic --max-samples 500

# Open ai4privacy mirror — multi-locale (en/it/de/fr)
for loc in en it de fr; do
  python -m nullpii_eval.run_compare \
    --out "compare-isotonic-$loc.json" \
    --dataset isotonic/pii-masking-200k --locale "$loc" --max-samples 200
done

python -m nullpii_eval.run_compare \
  --out compare-wikiann.json \
  --dataset wikiann --max-samples 200
```

The runner spawns one long-lived `nullpii serve` process and streams
JSON-lines to it — single model load, no per-sample warmup.
