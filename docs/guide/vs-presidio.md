# nullpii vs Microsoft Presidio vs bare spaCy NER

Honest 3-way comparison with real numbers across **5 locales** and
**4 public datasets**. All measurements reproducible — see bottom.

nullpii's detector is OpenAI's
[`privacy-filter`](https://huggingface.co/openai/privacy-filter)
(Apache 2.0, 1.3B param token classifier) running locally via ONNX
Runtime — default **`fp16`** (~3 GB, F1-equivalent to fp32, ~17%
faster than int8 on CPU). Pin `int4f16` (~772 MB, ~6% F1 drop) for
edge / memory-constrained installs.

## Head-to-head accuracy

Macro F1 over 8 PII categories, partial-match (IoU ≥ 0.5).

### PII-focused datasets — nullpii leads on dev-style + multi-locale

| Dataset                          | Locale | n   |   nullpii | Presidio | spaCy NER |
| -------------------------------- | ------ | --: | --------: | -------: | --------: |
| bundled (dev prompts)            | en     |  40 | **0.751** |    0.536 |     0.219 |
| bundled (dev prompts)            | it     |  40 | **0.761** |    0.459 |     0.109 |
| bundled (dev prompts)            | de     |  34 | **0.669** |    0.488 |     0.114 |
| bundled (dev prompts)            | fr     |  33 | **0.746** |    0.483 |     0.120 |
| bundled (dev prompts)            | es     |  33 | **0.735** |    0.463 |     0.118 |
| isotonic/pii-masking-200k        | en     | 200 | **0.548** |    0.499 |     0.185 |
| isotonic/pii-masking-200k        | it     | 200 | **0.597** |    0.409 |     0.075 |
| isotonic/pii-masking-200k        | de     | 200 | **0.604** |    0.401 |     0.106 |
| isotonic/pii-masking-200k        | fr     | 200 | **0.582** |    0.437 |     0.070 |
| presidio-synthetic               | en     | 500 |     0.548 |**0.558** |     0.157 |

**Reading**: nullpii wins 9/10 PII runs across 5 locales — including
800 samples of the open ai4privacy mirror in 4 languages, where
Presidio's English-tuned recognizer set is noticeably weaker. The one
exception is Presidio's own synthetic generator at 500 samples, where
the analyzer wins by 0.01 — a tie within noise. Bare spaCy NER catches
names + locations but misses emails, phones, account numbers, secrets
— it's general NER, not PII.

### Wikipedia NER (`wikiann`) — spaCy leads, both PII tools struggle

| Dataset    | Locale | n   | nullpii | Presidio | **spaCy NER** |
| ---------- | ------ | --: | ------: | -------: | ------------: |
| wikiann    | en     | 200 |   0.257 |    0.271 |     **0.362** |
| wikiann    | it     | 200 |   0.174 |    0.347 |     **0.725** |
| wikiann    | de     | 200 |   0.245 |    0.289 |     **0.778** |
| wikiann    | fr     | 200 |   0.162 |    0.223 |     **0.611** |
| wikiann    | es     | 200 |   0.224 |    0.335 |     **0.766** |

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
| Avg PII F1 (bundled, 5 locales)   | **0.732**                                        | 0.486                                          | 0.136                |
| Avg PII F1 (isotonic, 4 locales)  | **0.583**                                        | 0.436                                          | 0.109                |
| F1 on Presidio's own synthetic    | 0.548                                            | **0.558**                                      | 0.157                |
| F1 on Wikipedia NER (5 locales)   | 0.212                                            | 0.293                                          | **0.648**            |
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
