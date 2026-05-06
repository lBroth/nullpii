<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Local PII sanitization with reversible in-memory vault. ML span detection swaps PII with placeholders; pass the sanitized text anywhere (LLM, log, third-party API), then restore original values from the response.

## Why this exists

Honest framing: this is a **night-hobby project**, not a production-ready PII tool, not a research paper, not a commercial product.

Since I started using Claude Code I stopped playing video games — it became my night toy. nullpii is what fell out of those nights: a chance to learn the GLiNER + LoRA + router stack end-to-end, run it under a strict bench harness, write the honest audit on what works and what doesn't, and ship something that does the round-trip cleanly.

What's interesting here is the engineering rigor + adversarial preprocessor, not state-of-the-art F1.

> **Status (2026-05-06)** — first release `v0.1.0`. Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (multilingual GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, ~278M params). Shipping pipeline: `router-embedding` (~430 MB, **Google distiluse** + 5 per-domain LoRA adapters). The npm runtime downloads the full router stack from HF on first call.

## Bench at a glance

Mac M-series CPU, 10-dataset canonical surface, macro F1 at IoU ≥ 0.5 (partial-match span scoring). `nullpii` row = npm subprocess (what `npm i nullpii` runs); `router-embedding` row = Python re-impl of the same pipeline (sanity check). Full per-tool matrix at [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv).

| Dataset | n | `nullpii` | `router-embedding` | Notes |
|---|---:|:---:|:---:|---|
| `tab-echr` | 127 | **0.9170** ✨ | 0.8862 | EU legal (TAB ECHR test). ⚠ in-distribution (legal adapter trained on TAB train) |
| `adversarial-code` | 80 | **1.0000** 🎯 | 1.0000 | Credentials in code/comments — preprocessor + recognizer pack |
| `adversarial-unicode` | 80 | **0.9358** | 0.9358 | Cyrillic homoglyph + zero-width — preprocessor lift |
| `adversarial-typo` | 80 | 0.8869 | **0.9400** | Single-char neighbour swap — preprocessor lift |
| `isotonic-de-heldout` | 5k | **0.8756** ✨ | 0.8746 | Held-out (offset 200k+) |
| `isotonic-en-heldout` | 5k | **0.8685** ✨ | 0.8671 | Held-out (offset 200k+) |
| `nullpii-bench` | 264 | 0.7255 | **0.7280** | Project gold (real-world dev paste, RFCs, multilingual). ⚠ in-distribution (template-family leak) |
| `nemotron-pii-test` | 5k | 0.7227 | **0.7602** | **NVIDIA Nemotron-PII** test split. ⚠ in-distribution (enterprise adapter trained on Nemotron train) |
| `presidio-synthetic` | 5k | 0.6051 | **0.6943** † | Faker-driven synthetic (**Microsoft Presidio Evaluator**) — held-out |
| `ai4privacy-300k-heldout` | 5k | 0.5170 | **0.5283** | Held-out (offset 100k+) |
| **Mixed (10)** | — | **0.8054** | 0.8214 | inflated by adv. preprocessor wins + in-distribution rows |
| **Held-out OOD (4)** | — | 0.7166 | **0.7411** | honest non-adversarial generalisation claim |
| **Adversarial preprocessor (3)** | — | 0.9409 | **0.9586** | preprocessor-driven lift, not model-driven |
| **In-distribution diagnostic (3)** | — | 0.7884 | **0.7915** | memorisation, not generalisation |

Legend:
- **bold** = best of the two columns on that dataset
- ✨ = npm subprocess beats Python re-impl
- 🎯 = perfect score (1.0000)
- ⚠ = in-distribution, treat F1 as memorisation diagnostic, not OOD generalisation
- † = `presidio-synthetic` gap explained: npm uses the full `DEFAULT_RECOGNIZERS` pack everywhere; Python re-impl swaps to `MINIMAL_REGEX_PATTERNS` for narrative/legal/medical routes. Per-domain pack switching deferred to v0.2.x. Per-row F1 difference is ~0.09 only on prose-heavy data with many synthetic addresses.

Latency (Mac M-series CPU, n=50/size):

| Input size | p50 | p95 | p99 |
|---|---:|---:|---:|
| 100 chars | 81 ms | 87 ms | 91 ms |
| 1 000 chars | 230 ms | 251 ms | 259 ms |
| 10 000 chars | 2.15 s | 2.25 s | 2.83 s |

## Install

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an optional peer dependency (CPU / MPS / CUDA backend). Requires Node 24 LTS (see `.nvmrc`).

> **First-call download**: the first `sanitize()` invocation downloads ~6 GB of model artifacts from HuggingFace Hub ([`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) — 5 merged-LoRA ONNX shards + distiluse encoder + tokenizer + prototypes) into `~/.cache/nullpii/` (or `$XDG_CACHE_HOME/nullpii/`). One-shot; subsequent calls hit the local cache. Plan accordingly for air-gapped installs (mirror the HF repo locally and pass `modelDir`).

## Usage

```ts
import { sanitize, restore } from 'nullpii';

const safe = await sanitize('Email John Smith at john@acme.com about SSN 123-45-6789');
// safe.sanitized: 'Email [[NULLPII:private_person:0]] at [[NULLPII:private_email:0]] about SSN [[NULLPII:account_number:0]]'
// safe.sessionId: opaque session id
// safe.spans:     PiiSpan[] in document order

// pass safe.sanitized to any LLM …
const reply = 'Hello [[NULLPII:private_person:0]], we received your request.';

const back = restore(reply, safe.sessionId);
// back.restored: 'Hello John Smith, we received your request.'
```

Programmatic API:

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });
const { sessionId, sanitized, spans } = await np.sanitize(text);
// … LLM call uses `sanitized` …
const { restored } = np.restore(reply, sessionId);
await np.dispose();
```

CLI:

```bash
npx nullpii sanitize --stdin --format json < customer-email.txt | jq .sanitized
```

## What gets caught (8 categories)

| Label             | Examples                                          |
| ----------------- | ------------------------------------------------- |
| `private_person`  | personal names (first / last / middle, prefixes)  |
| `private_email`   | email addresses                                   |
| `private_phone`   | phone / fax numbers                               |
| `private_address` | street addresses, cities, GPE, ZIP                |
| `private_date`    | birth / hire dates                                |
| `private_url`     | private URLs (admin panels, internal wikis)       |
| `account_number`  | bank accounts, IBAN, SSN, credit cards, MRN, customer IDs |
| `secret`          | API keys, tokens, passwords, JWT, PEM private keys |

> **Why only 8 categories?** Microsoft Presidio ships ~20 entity types (and 30+ optional recognizers). NVIDIA Nemotron-PII trains on 55 fine-grained classes (`first_name` vs `last_name`, `mrn` vs `health_plan_beneficiary_number`, etc.). nullpii inherits the 8-class schema of its [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) backbone and keeps it.
>
> Rationale: distinguishing `first_name` vs `last_name` doesn't matter when **redacting** — both end up as `[[NULLPII:private_person:0]]`. SSN / IBAN / credit-card all collapse to `account_number` because you mask them the same way. Granular schemas are useful as training signal (Nemotron's 55-class fine-tune learns finer distinctions); broad schemas are easier downstream (one placeholder type per category, simpler restore mapping). Different targets.
>
> Bench-side: Presidio / Nemotron / DeBERTa native predictions are remapped to nullpii's 8-class **before** the F1 comparison so cross-tool bench is fair (see "Benchmarks" below). Symmetric — every cross-schema NER bench needs the bridge.

Add custom regex recognizers as a post-pass for known formats with low ML coverage:

```ts
np.addRecognizer({
  id: 'aws-key',
  pattern: /\bAKIA[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
});
```

## Backends

| Backend | Platform                | Notes                                  |
| ------- | ----------------------- | -------------------------------------- |
| `cpu`   | All                     | Universal; fast on Apple Silicon       |
| `mps`   | macOS Apple Silicon     | CoreML EP, partial op coverage         |
| `cuda`  | Linux / Windows + NVIDIA | CUDA EP via `onnxruntime-node`        |

Auto-selects in priority **CUDA → MPS → CPU**.

## Privacy guarantees

- Detection runs **entirely local** — never touches the network.
- Vault is **in-memory only** — never serialized to disk.
- `destroySession()` purges the mapping.
- Logs never contain PII (counts and short ids only).
- See [SECURITY.md](SECURITY.md) for the threat model and how to report a vulnerability.

## Benchmarks

> **Status (2026-05-06)**: first release bench. nullpii numbers below come from the local Mac CPU bench (`packages/eval/published-bench/matrix.{json,csv}`). Two columns: `nullpii` (the npm subprocess, what users get from `npm i nullpii`) + `nullpii-router-embedding` (Python re-impl, sanity check on the same pipeline). Third-party baselines wired in `bench_full.py` for a later head-to-head iteration.

Mac M-series CPU, single seed, macro F1 at IoU ≥ 0.5, partial-match span scoring on **10 datasets** — full list in the per-dataset table below. Picked to cover the brand-recognition canonical PII suites (`presidio-synthetic`, `nemotron-pii-test`, `ai4privacy`, `isotonic`, `tab-echr`) + the project gold (`nullpii-bench`) + the 3 adversarial subsets where the preprocessor wins.

**Bare-mode contract** — zero nullpii post-processing on competitor rows: no `_normalize_for_detection`, no boundary refine, no never-PII filter, no regex pack. The only adapter glue is the universal NER-bench plumbing applied identically to every tool:

- **Chunking 1400/200 char stride** — every ML tool has a ~512-token context limit, so documents like TAB ECHR (avg 2000+ tokens) must be split + dedupe. Same code path on `gliner-onnx-pii-fp32`, `nemotron-pii-raw`, GLiNER family, and the nullpii rows.
- **Per-tool label remap** to nullpii's 8-class schema — Microsoft Presidio emits `PERSON` / `EMAIL_ADDRESS` / `LOCATION`, NVIDIA Nemotron emits 55 fine-grained labels (`first_name`, `ssn`, `mrn`, …), Microsoft DeBERTa fine-tune emits `PER` / `LOC` / `ORG`. The bench predictor wrappers (`presidio_predictor`, `gliner_nemotron_pii_predictor`, etc.) translate those native labels to nullpii's 8-class **before** the span is compared to gold — so a Presidio `EMAIL_ADDRESS` at offset `[20:33]` is scored against gold `private_email` at `[20:33]` as a true positive. Without this bridge F1 would be ~0 even on perfectly detected spans (different label spaces). Symmetric — every cross-tool NER bench needs it; not a nullpii advantage.

### Pipeline

**Ship the npm subprocess (`nullpii` row, what `npm i nullpii` runs)**: distiluse encoder + 5 merged-LoRA GLiNER ONNX adapters + recognizer pack + reversible vault. ~430 MB on disk after first-call HF download. The Python re-impl row (`nullpii-router-embedding`) reproduces the same pipeline as a sanity check; numbers track within ~0.05 across the canonical surface.

#### Headline number, honest

We split the 10-dataset bench into three buckets and report each separately so the reader can judge what "F1" means:

1. **Held-out non-adversarial (4 datasets) — F1 0.7166.** The model never saw any of these rows during training. This is the **honest OOD claim** for nullpii.
   - `presidio-synthetic`, `ai4privacy-300k-heldout` (offset 100k+), `isotonic-{en,de}-heldout` (offset 200k+).

2. **Adversarial subset (3 datasets) — preprocessor-driven, not model-driven, F1 0.9409.** Synthetic perturbations (typo / unicode / code) generated post-training, technically held-out, but the lift comes from the `_normalize_for_detection` preprocessor (NFKC + unidecode + zero-width strip + spaced-PII despace), not from the model.

3. **In-distribution diagnostic (3 datasets) — F1 0.7884, NOT a generalisation claim.** Adapters trained on slices of these datasets, so performance is in-distribution memorisation. Published for transparency only.
   - `nullpii-bench` (project-bundled, template-leaked with `dev-paste-synth-train`); `tab-echr` (legal adapter trained on TAB train, 127/127 test docs share shingles); `nemotron-pii-test` (enterprise adapter trained on Nemotron train).

The mixed **F1 0.8054 (10 datasets)** is the average of all three buckets — inflated by both the in-distribution rows and the adversarial-preprocessor wins. Use the held-out 0.7166 figure for any OOD claim; quote the mixed 0.8054 only with the caveat above.

### Per-dataset F1

`nullpii` = npm subprocess (canonical user-facing row, what `npm i nullpii` ships). `router-embedding` = Python re-impl of the same pipeline (sanity check; numbers should track).

| Dataset | n | `nullpii` | `router-embedding` | Notes |
|---|---:|:---:|:---:|---|
| `nullpii-bench` | 264 | **0.7255** | 0.7280 | Project-bundled gold (real-world dev paste, RFCs, multilingual tickets) — ⚠ in-distribution (template-family leak with `dev-paste-synth-train`) |
| `tab-echr` | 127 | **0.9170** | 0.8862 | EU legal (TAB ECHR test split) — ⚠ in-distribution (legal adapter trained on TAB train) |
| `nemotron-pii-test` | 5k | **0.7227** | 0.7602 | **NVIDIA Nemotron-PII** test split — ⚠ in-distribution (enterprise adapter trained on NVIDIA Nemotron train split) |
| `presidio-synthetic` | 5k | 0.6051 | 0.6811 | Faker-driven synthetic (**Microsoft Presidio Evaluator**) — held-out |
| `ai4privacy-300k-heldout` | 5k | 0.5170 | 0.5283 | Held-out (offset 100k+) |
| `isotonic-en-heldout` | 5k | **0.8685** | 0.8671 | Held-out (offset 200k+) |
| `isotonic-de-heldout` | 5k | **0.8756** | 0.8746 | Held-out (offset 200k+) |
| `adversarial-typo` | 80 | 0.8869 | 0.9400 | Single-char neighbour swap — preprocessor lift |
| `adversarial-unicode` | 80 | **0.9358** | 0.9358 | Cyrillic homoglyph + zero-width insertion — preprocessor lift |
| `adversarial-code` | 80 | **1.0000** | 1.0000 | Credentials in comments / docstrings — preprocessor lift |

### Latency

p50 / p95 / p99 over 50 inputs per size bucket (`nullpii-router-embedding` Python re-impl, Mac M-series CPU, n=50/size):

| Input size | p50 | p95 | p99 | mean |
|---|---:|---:|---:|---:|
| 100 chars | 81 ms | 87 ms | 91 ms | 81 ms |
| 1 000 chars | 230 ms | 251 ms | 259 ms | 231 ms |
| 10 000 chars | 2 150 ms | 2 248 ms | 2 833 ms | 2 168 ms |

Reproduce: `python -u packages/eval/scripts/bench_latency.py --profiles nullpii-router-embedding --backend cpu --sizes 100 1000 10000 --n-per-size 50 --out packages/eval/results/latency-<DATE>`.

### Competitor comparison

Bare-mode third-party baselines benched on the same 10-dataset Mac CPU pass alongside `nullpii-router-embedding`: **Microsoft Presidio**, GLiNER (`urchade/gliner_multi_pii-v1` ONNX FP32), `iiiorg/piiranha`, **Microsoft DeBERTa**-v3 community fine-tune, **NVIDIA Nemotron-PII** (`nvidia/gliner-pii`), and `gliner-pii-large-v1`. Same chunking (1400/200 char stride), same per-tool label remap to nullpii's 8-class schema, no nullpii post-processing leak on competitor rows.

Head-to-head matrix — per-dataset F1, every tool × every dataset: [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv). Methodology, schema-bridge mechanics, and the `CLAIM-VERIFIER-01` finding (Presidio 0.85+ / piiranha 0.99 not reproducible with span IoU ≥ 0.5) are documented in [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md).

Honest read: nullpii sits in the GLiNER-family ballpark on the held-out non-adversarial subset (F1 0.7378) and wins the adversarial bucket because of `_normalize_for_detection` (typo 0.94 / unicode 0.94 / code 1.00), not because of model strength. Read the matrix for the per-dataset trade-offs.

## Documentation

### Top-level

- [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) — bench methodology + competitor landscape
- [`CHANGELOG.md`](CHANGELOG.md) — release notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup + architecture rules
- [`SECURITY.md`](SECURITY.md) — threat model + vuln reporting

### Model card

Lives on HuggingFace Hub: [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) — training data composition, intended use, limitations, in-distribution disclosures.

### Eval kit

- [`packages/eval/README.md`](packages/eval/README.md) — bench harness + scripts inventory
- [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md) — dataset cards + licenses

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Runtime tree is 100% permissive (MIT / Apache-2.0 / BSD / ISC / CC0); verified by `npm run license-check` in CI.

## Citation

> nullpii contributors (2026). *nullpii: local PII sanitization with reversible vault.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, Zaratiana et al. NAACL 2024). Per-domain LoRA adapter training data composition + recipe: see the HF model card.
