# nullpii eval datasets

Local datasets shipped with the `nullpii` eval kit. All Apache-2.0, no
real PII (synthetic + templated + filtered Common Crawl). Together with
the HF-hosted external sets (ai4privacy, isotonic, Nemotron-PII,
presidio-synthetic, argilla-pii) these drive `bench_full.py`.

## Inventory

| File | Rows | Purpose | Used in canonical 10 bench? |
|---|---:|---|:---:|
| `nullpii-bench.jsonl` | 271 | Project gold standard — multilingual dev-style prompts + adversarial decoys + long-prompts | ✅ |
| `nullpii-adversarial.jsonl` | 480 | 6 synthetic perturbation subsets (80 each): `typo_pii`, `unicode_obf`, `whitespace_obf`, `encoding_obf`, `decoys`, `code_pii` | ✅ (typo / unicode / code only) |
| `nullpii-adversarial-textattack.jsonl` | 1670 | TextAttack perturbation variants × 334: homoglyph / charswap / chardelete / charinsert / charsub | ❌ (private extended-bench) |
| `tab-echr-test.jsonl` | 127 | EU jurisprudence test split (TAB ECHR, Pilán et al. ACL 2022) — legal-domain eval | ✅ |
| `adversarial.jsonl` | 7 | Hand-curated decoy strings (already merged into `nullpii-bench` `adversarial` subset) | source-only |
| `long-prompts-en-baseline.jsonl` | 62 | English long-form (~3k chars) source for chunking stress test (already merged into `nullpii-bench`) | source-only |
| `{en,de,fr,it,es}-baseline.jsonl` | varies | Per-locale baseline prompts (source for `nullpii-bench` `bundled` subset) | source-only |
| `{en,de,fr,it,es}-templates.txt` | — | `{{label\|text}}` markup templates → emit char-level spans via `build.py` | source-only |
| `dev-paste-synth-train.jsonl` | ~20k | `devops` adapter training corpus (Faker-driven dev paste / code / secrets) | training-only |
| `cc-negative-25k.jsonl` | 25k | Common Crawl filtered no-PII partition (negative class regularizer, ~6.25k per adapter) | training-only |
| `cc-negative-200-test.jsonl` | 200 | Hold-out FP test partition (Common Crawl, no-PII) | diagnostics-only |

## `nullpii-bench` schema

Each line:

```jsonc
{
  "id": "bundled-it-0023",
  "locale": "it",
  "subset": "bundled",                            // bundled | adversarial | long-prompts
  "text": "Inoltrare a Maria Rossi (maria.rossi@example.it) entro venerdì.",
  "spans": [
    { "label": "private_person", "start": 11, "end": 22 },
    { "label": "private_email",  "start": 24, "end": 47 }
  ]
}
```

8-class label set (matches `nullpii` redaction schema):
`private_person` / `private_email` / `private_phone` / `private_address` /
`private_date` / `private_url` / `account_number` / `secret`.

### Subsets

| Subset | Rows | Description |
|---|---:|---|
| `bundled` | 202 | Dev-style prompts (PR reviews, deploy logs, RFCs, customer support) across 5 locales |
| `adversarial` | 7 | Decoy strings that look like PII but aren't — false-positive stress test |
| `long-prompts` | 62 | English long-form prompts (~3k chars) with PII positioned past the 512-token mark — chunking stress test |

### Locale distribution

| Locale | Rows | Breakdown |
|---|---:|---|
| `en` | 131 | 62 bundled + 7 adversarial + 62 long-prompts |
| `it` | 40 | bundled |
| `de` | 34 | bundled |
| `fr` | 33 | bundled |
| `es` | 33 | bundled |

### Span-label distribution (680 total)

| Label | Count |
|---|---:|
| `private_person` | 214 |
| `private_email` | 164 |
| `secret` | 73 |
| `private_date` | 67 |
| `private_url` | 56 |
| `private_phone` | 53 |
| `account_number` | 30 |
| `private_address` | 23 |

### In-distribution disclosure

`nullpii-bench` shares template family with `dev-paste-synth-train`
(the `devops` adapter training corpus): same `{{label|text}}` markup
patterns, overlapping prompt skeletons. F1 on `nullpii-bench` is
treated as **in-distribution memorisation diagnostic**, not OOD.
Documented in the train-vs-eval overlap matrix at
[`docs/v10/model-cards/README.md`](../../../docs/v10/model-cards/README.md#train-vs-eval-dataset-overlap).

## `nullpii-adversarial` subsets

6 × 80 rows, each subset stresses a different perturbation:

| Subset | Perturbation | In canonical 10? |
|---|---|:---:|
| `typo_pii` | Single-char neighbour swap | ✅ |
| `unicode_obf` | Cyrillic homoglyph + zero-width insertion | ✅ |
| `code_pii` | Credentials in comments / docstrings | ✅ |
| `whitespace_obf` | `g i a n l u c a @ g m a i l . c o m` style | ❌ private |
| `encoding_obf` | Base64 / URL / HTML-entity wrapping (preprocessor gap) | ❌ private |
| `decoys` | Look-alike strings that are not PII (FP stress) | ❌ private |

The 3 wins (typo / unicode / code) are preprocessor-driven, not
model-driven — see `_normalize_for_detection` mirrored in
[`src/normalize.ts`](../../../src/normalize.ts).

## `tab-echr-test`

EU jurisprudence test split, 127 docs, ~3000 chars avg → exercises the
1400/200-stride chunker. Gold spans cover `private_person` /
`private_address` / `private_date`. Train split (used to fine-tune the
`legal` adapter) is **disjoint rows from the same upstream dataset** —
treat F1 as in-distribution generalisation, not OOD.

## Loading

```python
from datasets import Dataset
ds = Dataset.from_json("packages/eval/datasets/nullpii-bench.jsonl")

# Filter by subset / locale
bundled_it = ds.filter(lambda r: r["subset"] == "bundled" and r["locale"] == "it")
long_en    = ds.filter(lambda r: r["subset"] == "long-prompts")
```

## Regenerating

```bash
cd packages/eval
python3 datasets/build.py                  # per-locale baselines from templates
python3 datasets/build_nullpii_bench.py    # merge baselines + adversarial + long-prompts
```

Adversarial + textattack JSONLs regen via
[`scripts/generate_adversarial_bench.py`](../scripts/generate_adversarial_bench.py)
+ [`scripts/generate_textattack_adversarial.py`](../scripts/generate_textattack_adversarial.py)
(synthesis is seeded for reproducibility, `random.Random(seed=42)`).

## License + citation

Apache-2.0 throughout. No real PII — every span is synthetic, templated,
or filtered Common Crawl no-PII.

```
@misc{nullpii-bench-2026,
  title  = {nullpii-bench: multilingual PII evaluation prompts},
  author = {nullpii contributors},
  year   = {2026},
  url    = {https://github.com/lBroth/nullpii},
  note   = {Apache-2.0 license}
}
```

External datasets (ai4privacy, isotonic, Nemotron-PII, TAB ECHR upstream,
presidio-synthetic, argilla-pii) retain their own licenses — see each
HF dataset card.

## Contributing

Add new prompts to `<locale>-templates.txt` using `{{label|text}}`
markup, then re-run `build.py` + `build_nullpii_bench.py`. PRs welcome
for under-represented locales / domains.
