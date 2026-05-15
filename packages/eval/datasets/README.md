# nullpii eval datasets

Apache-2.0, no real PII (synthetic / externally-licensed test splits).

## Inventory

Three files at HEAD: the project's canonical `nullpii-bench.jsonl` plus two
externally-licensed upstream splits.

| File | Rows | Used in canonical bench | Origin |
|---|---:|:---:|---|
| `nullpii-bench.jsonl` | 2,421 | ✅ project-authored, see subsets below | self-authored, Apache-2.0 |
| `presidio-synthetic.jsonl` | 5,000 | ✅ external (held-out OOD-5) | Microsoft Presidio seed, MIT |
| `tab-echr-test.jsonl` | 127 | ✅ EU legal test split | TAB ECHR test (ACL 2022), MIT |

Additional bench rows (`ai4privacy-*`, `isotonic-*`, `nemotron-pii-*`,
`argilla-pii`) are fetched from HuggingFace at bench time by the per-tool
adapters under `packages/eval/src/nullpii_eval/`. They retain their own
licences and are NEVER bundled in the npm package — see [`NOTICE`](../../../NOTICE).

### `nullpii-bench.jsonl` subsets

All project-authored bench data lives in one file with a `subset` field.
Loaders filter by subset to produce the bench rows.

All subsets feed the `nullpii-bench` cell in the canonical bench
(one F1 number summarises behaviour across all perturbation patterns).
Total 2,271 rows.

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
| `textattack-*` (homoglyph, charswap, chardelete, charinsert, charsub) | 334 each | adversarial perturbation slices |

The generation scripts that produced these subsets are not tracked in
the repo — they live under `packages/eval/private/` (gitignored). The
output `nullpii-bench.jsonl` is the canonical artifact and is committed
verbatim. Treat the file as fixed; rebuilds require re-fetching the
upstream pool from internal storage.

## `nullpii-bench` schema

```jsonc
{
  "id": "bundled-it-0023",
  "locale": "it",
  "subset": "bundled",                            // bundled | adversarial | long-prompts | typo_pii | …
  "text": "Inoltrare a Maria Rossi (maria.rossi@example.it) entro venerdì.",
  "spans": [
    { "label": "private_person", "start": 11, "end": 22 },
    { "label": "private_email",  "start": 24, "end": 47 }
  ]
}
```

10-class redaction labels: `private_person` / `private_email` / `private_phone` / `private_address` / `private_date` / `private_url` / `private_ip` / `private_mac` / `account_number` / `secret`.

⚠ `nullpii-bench` is in-distribution for the project pipeline. F1 on
this dataset is a regression test for the runtime (preprocessor,
recognizer pack, base64 decoder), not an OOD generalisation claim. The
held-out OOD headline is the macro over 5 external datasets
(`presidio-synthetic` + `isotonic-{en,de,fr,it}-heldout`) reported in
the top-level README.

## `presidio-synthetic`

Microsoft Presidio's templated test set (5,000 rows). MIT-licensed,
fully synthetic. Used as a held-out OOD baseline.

## `tab-echr-test`

EU jurisprudence test split, 127 docs, ~3,000 chars avg. Gold spans
cover `private_person` / `private_address` / `private_date`.

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

External datasets (`presidio-synthetic`, `tab-echr-test`, plus the
HF-fetched `ai4privacy`, `Isotonic`, `Nemotron-PII`, `argilla-pii`)
retain their own licences — see each upstream dataset card.
