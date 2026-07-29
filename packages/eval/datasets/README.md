# nullpii eval datasets

Apache-2.0, no real PII (synthetic / externally-licensed test splits).

## Inventory

Three files at HEAD: the project's canonical `nullpii-bench.jsonl` plus two
externally-licensed upstream splits.

| File | Rows | Used in canonical bench | Origin |
|---|---:|:---:|---|
| `nullpii-bench.jsonl` | 2,361 | ✅ project-authored, see subsets below | self-authored, Apache-2.0 |
| `presidio-synthetic.jsonl` | 5,000 | ✅ external, member of **OOD-7** | Microsoft Presidio seed, MIT |
| `tab-echr-test.jsonl` | 127 | ✅ EU legal test split, member of **OOD-7** | TAB ECHR test (ACL 2022), MIT |

Every file listed here is redistributed inside the `nullpii-eval` wheel via
the per-file allowlist in [`../pyproject.toml`](../pyproject.toml). A file
dropped into this directory does **not** ship until it is added there —
which is the point: adding the line forces a licence check first. Only
MIT / Apache-2.0 / BSD / ISC / CC0 upstreams are eligible.

Additional bench rows (`ai4privacy-*`, `isotonic-*`, `nemotron-pii-*`,
`argilla-pii`) are fetched from HuggingFace at bench time by the per-tool
adapters under `packages/eval/src/nullpii_eval/`. They retain their own
licences and are NEVER bundled in the npm package — see [`NOTICE`](../../../NOTICE).

### `nullpii-bench.jsonl` subsets

All project-authored bench data lives in one file with a `subset` field.
Loaders filter by subset to produce the bench rows.

All subsets feed the `nullpii-bench` cell in the canonical bench
(one F1 number summarises behaviour across every perturbation pattern).
Total 2,361 rows.

| Subset | Rows | Notes |
|---|---:|---|
| `clean` | 2,052 | dev paste, RFCs, long-form prompts, multilingual support tickets, code-PII, decoys |
| `adversarial` | 219 | typo / unicode-homoglyph / zero-width / whitespace / base64-URL-HTML-entity / TextAttack perturbations |
| `v03_coverage` | 90 | v0.3 schema-coverage rows for `private_passport` / `private_driver_license` / `private_vehicle_id` / `private_geolocation` / `private_ip` / `private_mac` (15 each) |

Sources (`source` field): `fair` (project-authored, no detector involvement) — 2,213 rows. `opf-generated` / `opf-enriched` — 148 rows re-annotated through OPF after an independent-gold audit (avoids the self-validation trap of detector-derived labels).

The generation scripts that produced the `clean` / `adversarial`
subsets are not tracked in the repo — they live under
`packages/eval/private/` (gitignored). The v0.3 coverage subset is
produced by the tracked `packages/eval/scripts/extend_bench_rows_v03.py`
(pure-Python templates, seeded RNG, no `nullpii` import — see
"Independent-gold rule" docstring). The output `nullpii-bench.jsonl` is
the canonical artifact and is committed verbatim. Treat the file as
fixed; rebuilds of the `clean` / `adversarial` subsets require
re-fetching the upstream pool from internal storage.

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
recognizer pack, base64 decoder), not an OOD generalisation claim.

### OOD-7 — the held-out headline set

The OOD headline reported in the top-level README is the macro over
**seven** external datasets, named **OOD-7** here and in the root README:

```
presidio-synthetic
isotonic-en-heldout   isotonic-de-heldout
isotonic-fr-heldout   isotonic-it-heldout
ai4privacy-300k-heldout
tab-echr
```

Membership criterion: the dataset is externally authored **and** no part
of it entered nullpii's training distribution. The `-heldout` suffix means
rows sliced above nullpii's own training offsets
(`_AI4_HELDOUT_OFFSET` / `_ISOTONIC_HELDOUT_ROW_OFFSET`,
[`../scripts/bench_full.py`](../scripts/bench_full.py)) — it carries **no**
held-out guarantee for any other tool in the matrix.

Do not restate this number by hand. Compute it from `matrix.json`:

```bash
python packages/eval/scripts/ood_macro.py packages/eval/published-bench/matrix.json
```

An earlier revision of this file described the headline as a macro over
five datasets; that was wrong and disagreed with the root README by
0.0128 F1 (OOD-5 = 0.7656 vs OOD-7 = 0.7784 at v0.3.0). The root README
figure was the correct one.

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
