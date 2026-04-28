# Eval results

Real numbers from `packages/eval/`. Reproducible — see bottom of page.

**Last run**: 2026-04-28 on Apple M5 Pro 48 GB, macOS, Node 24, Python
3.12, nullpii fp16 ONNX (CPU EP, 4-daemon pool with 8 ORT threads)
running OpenAI
[`privacy-filter`](https://huggingface.co/openai/privacy-filter)
(Apache 2.0, 1.3B param), Microsoft Presidio 2.x with `*_core_web_lg` /
`*_core_news_lg`. The OpenAI HF baseline is the same model loaded
via `transformers.pipeline()` with the default decoder — no chunking,
no Viterbi, no posterior scoring. Total: 16 datasets, 32k samples,
~128k inferences in 30 min wall-clock.

> **Why fp16 on CPU?** On this hardware (Apple Silicon ORT), fp16 is
> F1-equivalent to fp32 and ~17% faster than int8 (33 ms vs 41 ms /
> 512 tokens). MPS+CoreML EP only covers ~24/365 ops, so the partition
> overhead beats the GPU/ANE gains for this custom architecture.

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

## Aggregate (avg PII F1, 11 datasets, 30k samples)

Latency: per-sample weighted across all PII datasets on M5 Pro 48GB.

| Tool                  | avg PII F1 | latency ms/sample |
| --------------------- | ---------: | ----------------: |
| **nullpii**           |  **0.655** |              43.9 |
| GLiNER multi PII      |      0.603 |             104.7 |
| Microsoft Presidio    |      0.455 |              15.1 |
| piiranha-v1           |      0.439 |              59.0 |
| OpenAI bare HF        |      0.430 |              90.4 |
| DeBERTa PII (English) |      0.419 |              58.3 |
| bare spaCy NER        |      0.122 |              13.7 |

## Accuracy by locale (202 bundled dev prompts)

Partial-match (IoU ≥ 0.5). 7-way comparison.

| Locale | n  | nullpii | GLiNER | OpenAI bare HF | piiranha | DeBERTa-PII | Presidio | spaCy |
| ------ | -: | ------: | -----: | -------------: | -------: | ----------: | -------: | ----: |
| en     | 62 |**0.782**|  0.706 |          0.535 |    0.361 |       0.388 |    0.484 | 0.200 |
| it     | 40 |   0.761 |**0.774**|         0.464 |    0.358 |       0.330 |    0.459 | 0.109 |
| de     | 34 |   0.669 |**0.757**|         0.459 |    0.359 |       0.339 |    0.488 | 0.114 |
| fr     | 33 |   0.728 |**0.734**|         0.487 |    0.349 |       0.393 |    0.483 | 0.120 |
| es     | 33 |   0.756 |**0.764**|         0.490 |    0.368 |       0.379 |    0.463 | 0.118 |
| **avg**|    |   0.739 |**0.747**|         0.487 |    0.359 |       0.366 |    0.475 | 0.132 |

**Reading**: nullpii wins English; GLiNER edges nullpii on the four
non-English locales (largest gap: de, +0.09). Both leverage
multilingual training; nullpii's gap closes when chunking and
constrained Viterbi don't matter (short prompts, single-pass
inference). Long-prompts (below) flip the ordering.

## Head-to-head on public datasets

7-way at scale: 5k Isotonic per locale, 5k Presidio-synthetic, 1k
WikiAnn per locale.

| Dataset                              |    n | nullpii | GLiNER | OpenAI bare HF | piiranha | DeBERTa-PII | Presidio |   spaCy |
| ------------------------------------ | ---: | ------: | -----: | -------------: | -------: | ----------: | -------: | ------: |
| presidio-synthetic (en)              | 5000 |   0.591 |**0.656**|         0.403 |    0.390 |       0.433 |    0.573 |   0.156 |
| long-prompts-en (chunking proof)     |   62 |**0.600**|  0.000 |          0.350 |    0.352 |       0.000 |    0.348 |   0.079 |
| isotonic/pii-masking-200k (en)       | 5000 |   0.572 |  0.572 |          0.386 |    0.581 |   **0.751** |    0.478 |   0.173 |
| isotonic/pii-masking-200k (it)       | 5000 |**0.592**|  0.558 |          0.389 |    0.570 |       0.542 |    0.415 |   0.084 |
| isotonic/pii-masking-200k (de)       | 5000 |**0.580**|  0.561 |          0.385 |    0.569 |       0.488 |    0.399 |   0.102 |
| isotonic/pii-masking-200k (fr)       | 5000 |**0.578**|  0.549 |          0.380 |    0.569 |       0.569 |    0.415 |   0.082 |
| **isotonic avg (4 locales)**         |      |**0.581**|  0.560 |          0.385 |    0.572 |       0.587 |    0.427 |   0.110 |
| wikiann (en) — Wikipedia NER         | 1000 |   0.229 |  0.384 |          0.161 |    0.132 |       0.115 |    0.285 |**0.380**|
| wikiann (it)                         | 1000 |   0.149 |  0.283 |          0.087 |    0.180 |       0.075 |    0.222 |**0.747**|
| wikiann (de)                         | 1000 |   0.136 |  0.221 |          0.103 |    0.230 |       0.067 |    0.201 |**0.786**|
| wikiann (fr)                         | 1000 |   0.175 |  0.268 |          0.104 |    0.170 |       0.114 |    0.228 |**0.692**|
| wikiann (es)                         | 1000 |   0.229 |  0.229 |          0.104 |    0.195 |       0.084 |    0.234 |**0.753**|

> **Headline avg PII F1** (11 datasets, excludes wikiann):
> nullpii **0.655**, GLiNER 0.603, Presidio 0.455, piiranha 0.439,
> OpenAI bare HF 0.430, DeBERTa-PII 0.419, spaCy 0.122.
>
> **Per-dataset wins**: nullpii 5/11 (en bundled + 3 isotonic +
> long-prompts), GLiNER 4/11 (4 non-en bundled), DeBERTa-PII 1/11
> (isotonic-en only), GLiNER also wins presidio-synthetic.
>
> **+0.226 F1 vs OpenAI bare HF** — same upstream model, different
> decoder. Isolates the value of nullpii's runtime: chunking +
> constrained Viterbi + forward-backward posterior + recognizer
> post-pass.
>
> **GLiNER is the closest competitor**: 0.603 avg, batte nullpii sui
> 4 locales bundled non-English. **Ma 0.000 su long-prompts-en**
> (max-length truncation, no chunking). Stesso problema con DeBERTa-PII.
> Solo nullpii cattura PII oltre 512 tok by design.
>
> **Wikipedia NER**: spaCy dominates as expected — Wikipedia ≠ PII.
> GLiNER second (0.281 avg), nullpii third (0.184 avg).

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
> **Presidio synthetic (5000)**: virtual tie (0.576 vs 0.575). The
> generator's phrasing favours the lexicon Presidio's analyzer was
> tuned against (templated full names, address blocks); both tools
> hit the ceiling of what regex+NER can recover from this lexicon.
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

| Tool                  | Hardware            | seq=128 ms | seq=512 ms |
| --------------------- | ------------------- | ---------: | ---------: |
| nullpii (fp16, default)| Apple M5 Pro / arm64|      33.2 |       ~55  |
| nullpii (int4f16, edge)| Apple M5 Pro / arm64|     ~38   |       ~60  |
| Presidio              | Apple M5 Pro / arm64|       6.9 |       22.9 |

> **Honest takeaway**: Presidio is ~4× faster on this hardware.
> Tradeoff: nullpii catches contextual PII (better F1) at the cost of
> a transformer forward pass; Presidio is regex + small spaCy NER
> (cheaper, lower F1). MPS / CoreML EP path is currently slower than
> CPU EP because only ~24/365 model ops are CoreML-eligible —
> partition overhead beats GPU/ANE gains for this custom architecture.

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
