# nullpii eval datasets

Apache-2.0, no real PII (synthetic / templated / Common Crawl filtered no-PII).

## Inventory

| File | Rows | Used in canonical bench |
|---|---:|:---:|
| `nullpii-bench.jsonl` | 271 | ✅ project gold |
| `tab-echr-test.jsonl` | 127 | ✅ EU legal (TAB ECHR test, ACL 2022) |
| `nullpii-adversarial.jsonl` | 480 | ✅ typo / unicode / code subsets |
| `nullpii-adversarial-textattack.jsonl` | 1670 | ❌ |
| `dev-paste-synth-train.jsonl` | ~20k | training-only (devops adapter) |
| `cc-negative-25k.jsonl` | 25k | training-only (negative-class regularizer) |
| `cc-negative-200-test.jsonl` | 200 | diagnostics-only |
| `{en,de,fr,it,es}-baseline.jsonl` + `*-templates.txt` | — | source for `nullpii-bench` `bundled` subset |

## `nullpii-bench` schema

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

8-class redaction labels: `private_person` / `private_email` / `private_phone` / `private_address` / `private_date` / `private_url` / `account_number` / `secret`.

271 samples · 680 spans · 5 locales (en 131 / it 40 / de 34 / fr 33 / es 33). Subsets: `bundled` 202, `adversarial` 7, `long-prompts` 62. ⚠ in-distribution: shares template family with `dev-paste-synth-train` (devops adapter training corpus); F1 reads as memorisation diagnostic, not OOD.

## `nullpii-adversarial` (canonical subsets)

3 × 80 rows where the `_normalize_for_detection` preprocessor (NFKC + unidecode + zero-width strip + spaced-PII despace) drives F1, not the model:

- `typo_pii` — single-char neighbour swap
- `unicode_obf` — Cyrillic homoglyph + zero-width insertion
- `code_pii` — credentials in comments / docstrings

Preprocessor implementation: [`src/normalize.ts`](../../../src/normalize.ts).

## `tab-echr-test`

EU jurisprudence test split, 127 docs, ~3000 chars avg. Gold spans cover `private_person` / `private_address` / `private_date`. ⚠ in-distribution generalisation (legal adapter trained on TAB train split — disjoint rows, same distribution).

## Loading

```python
from datasets import Dataset
ds = Dataset.from_json("packages/eval/datasets/nullpii-bench.jsonl")
bundled_it = ds.filter(lambda r: r["subset"] == "bundled" and r["locale"] == "it")
```

## License + citation

```
@misc{nullpii-bench-2026,
  title  = {nullpii-bench: multilingual PII evaluation prompts},
  author = {nullpii contributors},
  year   = {2026},
  url    = {https://github.com/lBroth/nullpii},
  note   = {Apache-2.0 license}
}
```

External datasets (ai4privacy, Isotonic, Nemotron-PII, TAB ECHR upstream, presidio-synthetic, argilla-pii) retain their own licenses — see each HF dataset card.
