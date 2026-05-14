# nullpii eval datasets

Apache-2.0, no real PII (synthetic / templated / Common Crawl filtered no-PII).

## Inventory

| File | Rows | Used in canonical bench |
|---|---:|:---:|
| `nullpii-bench.jsonl` | 2 421 | ✅ unified — see subsets below |
| `tab-echr-test.jsonl` | 127 | ✅ EU legal (TAB ECHR test, ACL 2022) |
| `dev-paste-synth-train.jsonl` | ~20k | training-only (devops adapter) |
| `cc-negative-25k.jsonl` | 25k | training-only (negative-class regularizer) |
| `cc-negative-200-test.jsonl` | 200 | diagnostics-only |
| `{en,de,fr,it,es}-baseline.jsonl` + `*-templates.txt` | — | source for `nullpii-bench` `bundled` subset |

### `nullpii-bench.jsonl` subsets

All project-authored bench data lives in one file with a `subset` field. Loaders filter by subset to produce the bench rows.

All subsets feed the unified `nullpii-bench` cell in the canonical bench (one F1 number summarises behaviour across all perturbation patterns). Total 2 421 rows.

| Subset | Rows | Notes |
|---|---:|---|
| `bundled` | 202 | dev paste, RFCs, multilingual support tickets |
| `long-prompts` | 62 | English long-form (~3 k chars), chunking stress |
| `adversarial` | 7 | hand-curated decoy strings, regex-only, perfect F1 trivially |
| `typo_pii` | 80 | single-char neighbour swap (preprocessor regression) |
| `unicode_obf` | 80 | Cyrillic homoglyph + zero-width insertion |
| `whitespace_obf` | 80 | `g i a n l u c a @ g m a i l . c o m` — preprocessor regression |
| `encoding_obf` | 80 | base64 / URL / HTML-entity wrapping |
| `decoys` | 80 | strings that look like PII but aren't (FP stress) |
| `code_pii` | 80 | credentials in code/comments |
| `textattack-homoglyph` / `charswap` / `chardelete` / `charinsert` / `charsub` | 334 each | TextAttack perturbations over ai4privacy 0–500 |

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

2 421 rows total · 5 locales for the `bundled` + `long-prompts` slice (en 131 / it 40 / de 34 / fr 33 / es 33).

⚠ The base `nullpii-bench` slice (`bundled` + `long-prompts`) shares template family with `dev-paste-synth-train` (devops adapter training corpus); F1 on this row is a memorisation diagnostic, not OOD.

⚠ The `typo_pii` / `unicode_obf` / `code_pii` slices are self-authored — synthesised by `packages/eval/private/scripts/generate_adversarial_bench.py` over a project-curated PII pool (12 names, 6 emails, 5 phones, etc.) with project-chosen perturbations. The `_normalize_for_detection` preprocessor in [`src/normalize.ts`](../../../src/normalize.ts) targets exactly the perturbation classes generated. Treat the F1 as a regression test for the preprocessor, not a generalisation claim.

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
