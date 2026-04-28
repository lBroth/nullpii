# Comparisons

Honest head-to-head numbers vs every PII / NER tool we can run on the
same datasets. Measurements reproducible — see bottom.

**Tools currently compared**:

- **nullpii** (this library) — `openai/privacy-filter` 1.3B
  via ONNX Runtime + chunking + constrained Viterbi + posterior
  scoring + recognizer post-pass.
- **OpenAI bare HF pipeline** — same upstream model loaded via
  `transformers.pipeline()` with the default decoder. Isolates the
  value of nullpii's runtime over the bare upstream pipeline.
- **Microsoft Presidio** 2.x — regex + small spaCy NER, English-tuned
  recognizer set.
- **bare spaCy NER** — `*_core_news_lg` / `en_core_web_lg`, no PII
  recognizers. General NER baseline.
- **piiranha-v1** — [`iiiorg/piiranha-v1-detect-personal-information`](https://huggingface.co/iiiorg/piiranha-v1-detect-personal-information),
  DeBERTa-v3-based multilingual PII detector (~278M params, 6
  languages — en/es/fr/de/it/nl, 17 PII labels, 256-tok max). Smaller
  cousin of nullpii's upstream model; useful as a "small PII model"
  baseline.
- **deberta-pii** — [`lakshyakh93/deberta_finetuned_pii`](https://huggingface.co/lakshyakh93/deberta_finetuned_pii),
  DeBERTa-base English-only PII detector with rich label set (~50+
  categories — IBAN, Bitcoin, BIC, IPv4/v6, GPS, etc.). Mapped down
  to nullpii's 8 categories; tests how a label-rich English-only
  model performs on multilingual evals.
- **GLiNER PII** — [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1),
  zero-shot NER built on `urchade/gliner_multi-v2.1` (BERT-like).
  Accepts arbitrary label sets at inference time; we pass a curated
  list of 18 PII categories. Different paradigm from straight token
  classification.

nullpii's detector is OpenAI's
[`privacy-filter`](https://huggingface.co/openai/privacy-filter)
(Apache 2.0, 1.3B param token classifier) running locally via ONNX
Runtime — default **`fp16`** (~3 GB, F1-equivalent to fp32, ~17%
faster than int8 on CPU). Pin `int4f16` (~772 MB, ~6% F1 drop) for
edge / memory-constrained installs.

## Head-to-head accuracy

Macro F1 over 8 PII categories, partial-match (IoU ≥ 0.5).

### PII-focused datasets — nullpii leads on dev-style + multi-locale

Run on M5 Pro 48GB, 4-daemon nullpii pool + HF on CPU multi-thread.
**OpenAI bare HF** = upstream model loaded via `transformers.pipeline`
with the default decoder (no chunking, no Viterbi, no posterior).

| Dataset                          | Locale |    n |   nullpii | OpenAI bare HF | Presidio | spaCy NER |
| -------------------------------- | ------ | ---: | --------: | -------------: | -------: | --------: |
| bundled (dev prompts)            | en     |   62 | **0.782** |          0.535 |    0.484 |     0.200 |
| bundled (dev prompts)            | it     |   40 | **0.761** |          0.464 |    0.459 |     0.109 |
| bundled (dev prompts)            | de     |   34 | **0.669** |          0.459 |    0.488 |     0.114 |
| bundled (dev prompts)            | fr     |   33 | **0.728** |          0.487 |    0.483 |     0.120 |
| bundled (dev prompts)            | es     |   33 | **0.756** |          0.490 |    0.463 |     0.118 |
| long-prompts-en (chunking proof) |   en   |   62 | **0.600** |          0.350 |    0.348 |     0.079 |
| isotonic/pii-masking-200k        | en     | 5000 | **0.572** |          0.386 |    0.478 |     0.173 |
| isotonic/pii-masking-200k        | it     | 5000 | **0.592** |          0.389 |    0.415 |     0.084 |
| isotonic/pii-masking-200k        | de     | 5000 | **0.580** |          0.385 |    0.399 |     0.102 |
| isotonic/pii-masking-200k        | fr     | 5000 | **0.578** |          0.380 |    0.415 |     0.082 |
| presidio-synthetic               | en     | 5000 | **0.576** |          0.390 |    0.575 |     0.157 |

**Reading**: nullpii wins **11/11 PII runs across 5 locales** — one
near-tie with Presidio on its own synthetic generator (0.576 vs
0.575). The OpenAI bare HF column isolates the value of nullpii's
runtime: same model, **+0.226 F1 average** attributable entirely to
chunking + constrained Viterbi + forward-backward posterior +
recognizer post-pass. Bare spaCy NER catches names + locations but
misses emails, phones, account numbers, secrets — it's general NER,
not PII.

### Wikipedia NER (`wikiann`) — spaCy leads, both PII tools struggle

| Dataset | Locale |    n |   nullpii | OpenAI bare HF | Presidio | **spaCy NER** |
| ------- | ------ | ---: | --------: | -------------: | -------: | ------------: |
| wikiann | en     | 1000 |     0.229 |          0.161 |    0.285 |     **0.380** |
| wikiann | it     | 1000 |     0.149 |          0.087 |    0.222 |     **0.747** |
| wikiann | de     | 1000 |     0.136 |          0.103 |    0.201 |     **0.786** |
| wikiann | fr     | 1000 |     0.175 |          0.104 |    0.228 |     **0.692** |
| wikiann | es     | 1000 |     0.229 |          0.104 |    0.234 |     **0.753** |

**Reading**: WikiAnn is Wikipedia-extracted PER/LOC/ORG. spaCy
`*_core_news_lg` was trained on Wikipedia-like prose and dominates.
PII tools score low because the dataset isn't really PII — mapping
"Italy" to `private_address` (loose heuristic) hurts both.

**Honest result, not a marketing one**: if you need general NER, use
spaCy. If you need PII redaction, use nullpii.

## Throughput

Single-thread CPU inference, Apple M-series.

| Tool                     | seq=128 (ms) | seq=512 (ms) | Notes                          |
| ------------------------ | -----------: | -----------: | ------------------------------ |
| **bare spaCy NER**       |          ~3 |         ~10 | regex-free; pure spaCy pipeline |
| **Microsoft Presidio**   |          6.9 |         22.9 | spaCy NER + ~30 regex recognizers |
| nullpii (fp16 ONNX, default) |     33.2 |       ~55  | 1.3B param transformer          |
| nullpii (int4f16, edge)  |        ~38 |        ~60 | smaller, ~6% F1 drop            |

**Tradeoff curve**: spaCy fastest + lowest PII F1; Presidio middle;
nullpii slowest + highest PII F1. ~5× factor between extremes.

## Side-by-side feature matrix

| Capability                        | nullpii                                          | Presidio                                       | bare spaCy           |
| --------------------------------- | ------------------------------------------------ | ---------------------------------------------- | -------------------- |
| Primary language                  | **TypeScript / Node**                            | Python                                         | Python               |
| Detector                          | OpenAI [`privacy-filter`](https://huggingface.co/openai/privacy-filter) — 1.3B token classifier (Apache 2.0), ONNX | spaCy NER + regex recognizers | spaCy NER alone |
| Avg PII F1 (bundled, 5 locales)   | **0.739**                                        | 0.475                                          | 0.132                |
| Avg PII F1 (isotonic 5k, 4 locales)|**0.581**                                        | 0.427                                          | 0.110                |
| F1 on Presidio's own synthetic 5k | **0.576**                                        | 0.575                                          | 0.157                |
| F1 on Wikipedia NER (5 locales)   | 0.184                                            | 0.234                                          | **0.672**            |
| Avg PII F1 vs OpenAI bare HF (Δ)  | **+0.226 F1** over upstream pipeline             | n/a                                            | n/a                  |
| Latency (seq=512, ms)             | 57.7                                             | 22.9                                           | **~10**              |
| Default categories                | 8 PII                                            | 50+ PII / general                              | 18 NER               |
| Locales (production-tested)       | 5 with **30–40 dev prompts each**                | English mainly + 6 partial                     | **20+ via spaCy**    |
| Reversible vault                  | ✅ first-class, in-memory, scoped                 | ✅ via `AnonymizerEngine` + caller-managed state | ❌                    |
| Custom recognizer (regex)         | ✅ `addRecognizer()`                              | ✅ `PatternRecognizer`                          | ❌                    |
| Anthropic SDK middleware          | ✅ `withNullPii(client)`                          | ❌                                              | ❌                    |
| Claude Code plugin                | ✅ `@nullpii/claude-code`                         | ❌                                              | ❌                    |
| Streaming response restore        | ✅ `messages.stream` aware (cross-chunk buffer)   | ❌                                              | ❌                    |
| First-run download                | ~3 GB (fp16, default) or ~772 MB (int4f16) once  | ~50 MB per language                            | ~500 MB per language |
| License purity (runtime)          | **100% Apache/MIT/BSD/ISC/CC0**                  | spaCy models vary (some CC-BY-SA-4.0)          | model-dependent      |
| Image / file redaction            | ❌ text only                                      | ✅                                              | ❌                    |

## When to pick which

### Use **nullpii** if

- You integrate with Claude Code or `@anthropic-ai/sdk`.
- You ship in TypeScript / Node and adding Python is unacceptable.
- You care more about **PII recall** on conversational text than raw
  throughput.
- You want a **reversible vault** out of the box.
- You want a **100% permissive dependency tree**.

### Use **Presidio** if

- You need 30+ languages today with broad recognizer coverage.
- You already run Python and want a battle-tested platform.
- You need image / audio / OCR redaction.
- Your compliance team requires a long audit history.

### Use **spaCy NER alone** if

- You don't need PII per se — you need general entity recognition
  (companies, places, dates) in **arbitrary languages including
  Wikipedia-like text**.
- Throughput is the dominant constraint (~3× faster than Presidio,
  ~10× faster than nullpii).

### Use **nullpii + recognizer packs**

Pair the ML pass (catches contextual / multilingual PII) with our
recognizer packs for known formats:

```bash
npm install @nullpii/recognizers-cloud @nullpii/recognizers-finance @nullpii/recognizers-id-it
```

Hybrid approach is usually the strongest — ML for natural-language
PII, regex for structured formats.

## Migration: Presidio → nullpii

`PatternRecognizer` maps directly to a nullpii `Recognizer`:

```python
# Presidio
PatternRecognizer(
    supported_entity="AWS_KEY",
    patterns=[Pattern(name="aws", regex=r"\bAKIA[0-9A-Z]{16}\b", score=0.99)],
)
```

```ts
// nullpii
np.addRecognizer({
  id: 'aws-key',
  pattern: /\bAKIA[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
});
```

Reach out via GitHub Discussions if you hit a Presidio feature you
miss — we'll either add it or document the workaround.

## Reproduce

```bash
cd packages/eval
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[presidio]" presidio-evaluator datasets

# spaCy models per locale
for m in en_core_web_lg it_core_news_lg de_core_news_lg fr_core_news_lg es_core_news_lg; do
  python -m spacy download "$m"
done

# Bundled multi-locale
for loc in en it de fr es; do
  python -m nullpii_eval.run_compare --out "out-bundled-$loc.json" --dataset bundled --locale "$loc"
done

# Presidio synthetic (Microsoft's own generator)
python -m nullpii_eval.run_compare --out out-presidio.json --dataset presidio-synthetic --max-samples 500

# Open ai4privacy mirror — multi-locale (en/it/de/fr; no es in upstream)
for loc in en it de fr; do
  python -m nullpii_eval.run_compare --out "out-isotonic-$loc.json" --dataset isotonic/pii-masking-200k --locale "$loc" --max-samples 200
done

# WikiAnn multi-locale
for loc in en it de fr es; do
  python -m nullpii_eval.run_compare --out "out-wikiann-$loc.json" --dataset wikiann --locale "$loc" --max-samples 200
done
```

The runner spawns one long-lived `nullpii serve` process and streams
JSON-lines to it — single model load, no per-sample warmup.
