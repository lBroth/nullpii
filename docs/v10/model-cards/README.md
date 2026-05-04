# nullpii v10 — model cards (draft, pre-HF push)

Seven artifacts will publish to the HuggingFace Hub under `lBroth/`:

| Repo | Type | Card |
|---|---|---|
| `lBroth/nullpii-v10-router-embedding` | release-candidate router (default) | [`router-embedding.md`](router-embedding.md) |
| `lBroth/nullpii-v10-router-xlmr` | release-candidate router (high-F1 alt) | [`router-xlmr.md`](router-xlmr.md) |
| `lBroth/nullpii-v10-devops-lora` | LoRA adapter | [`adapter-devops.md`](adapter-devops.md) |
| `lBroth/nullpii-v10-legal-lora` | LoRA adapter | [`adapter-legal.md`](adapter-legal.md) |
| `lBroth/nullpii-v10-medical-experimental-lora` | LoRA adapter (HIPAA-pending) | [`adapter-medical-experimental.md`](adapter-medical-experimental.md) |
| `lBroth/nullpii-v10-narrative-lora` | LoRA adapter | [`adapter-narrative.md`](adapter-narrative.md) |
| `lBroth/nullpii-v10-enterprise-lora` | LoRA adapter (Nemotron-aug) | [`adapter-enterprise.md`](adapter-enterprise.md) |

## Why model cards

EU AI Act Art. 53 (transparency obligations for general-purpose AI providers) and NIST AI RMF Govern 4.1 / Map 5.2 require providers to publish documentation covering: training data composition, intended use, out-of-scope use, evaluation methodology, known limitations, and ethical considerations. These cards satisfy that obligation.

Cards are also the customer-facing source of truth for procurement / DPIA reviews — the README and CHANGELOG point downstream readers here.

## Status

🟡 **Draft, pre-bench**. Numerical eval cells are placeholders (`TBD-BENCH`) pending the unified release benchmark (see [`../V10_PLAN.md`](../V10_PLAN.md) §"Release gating" step 1). Once `bench_full.py` produces the final `matrix.json`, cards will be regenerated with concrete F1 / latency numbers and pushed to HuggingFace.

## Train-vs-eval dataset overlap

A single matrix tracks which adapter saw which dataset during training, so reviewers can spot in-distribution vs out-of-distribution rows in the evaluation tables.

| Dataset (eval) | devops | legal | medical-exp | narrative | enterprise |
|---|:---:|:---:|:---:|:---:|:---:|
| `nullpii-bench` (project-bundled OOD) | ❌ | ❌ | ❌ | ❌ | ❌ |
| `adversarial-{typo,unicode,whitespace,encoding,code}` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `textattack-{homoglyph,charswap,chardelete,charinsert,charsub}` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `tab-echr` (test split) | ❌ | ⚠ train split used | ❌ | ❌ | ❌ |
| `presidio-synthetic` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `ai4privacy-300k-heldout-v10` (offset 100k+) | ❌ | ❌ | ❌ | ❌ | ❌ |
| `ai4privacy-300k` (rows 0–100k) | ⚠ 0–5k train | ⚠ 0–5k train | ⚠ 0–5k train | ⚠ rows train | ⚠ subset train |
| `ai4privacy-400k` | ⚠ adjacent rows | ⚠ adjacent rows | ⚠ adjacent rows | ⚠ adjacent rows | ❌ |
| `isotonic-{en,de,fr,it}` (rows 0–200k) | ⚠ 0–5k train | ❌ | ❌ | ⚠ rows train | ❌ |
| `isotonic-{en,de,fr}-heldout-v10` (offset 200k+) | ❌ | ❌ | ❌ | ❌ | ❌ |
| `oasst-dev-planted` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `argilla-pii` | ❌ | ❌ | ❌ | ❌ | ❌ |
| `nemotron-pii-test` (Nvidia test split) | ❌ | ❌ | ❌ | ❌ | ⚠ Nemotron train split used (10k rows) |

**Reading the table**:

- ✅ green / ❌ no overlap — out-of-distribution evaluation
- ⚠ amber — train and eval pull from the same upstream dataset, possibly adjacent rows. Treat F1 deltas vs ❌ rows as a memorization-vs-generalisation signal, not an absolute capability claim.
- `enterprise × nemotron-pii-test`: the `enterprise` adapter is trained on `nvidia/Nemotron-PII` train split (10k rows). Its evaluation on the Nemotron test split is in-distribution. We publish the number for transparency but treat it as a memorization data-point, not a generalisation claim.

The held-out splits (`-heldout-v10` suffix, offset 100k+ for ai4privacy, offset 200k+ for isotonic) are the rows the adapters never saw during training. Compare those to non-heldout rows to estimate the memorization gap on each dataset.

## License

All seven artifacts ship under **Apache 2.0** (matches base model `urchade/gliner_multi_pii-v1` and all training datasets except where noted in each card).
