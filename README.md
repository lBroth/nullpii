<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Local PII sanitization for LLM prompts. ML span detection + reversible in-memory vault — pass placeholders to your LLM, restore original values from the response.

## Why this exists

Honest framing: this is a **night-hobby project**, not a production-ready PII tool, not a research paper, not a commercial product.

Since I started using Claude Code I stopped playing video games — it became my night toy. nullpii is what fell out of those nights: a chance to learn the GLiNER + LoRA + router stack end-to-end, run it under a strict bench harness, write the honest audit on what works and what doesn't, and ship something that does the round-trip cleanly.

For real GDPR-grade PII redaction in production, use [Microsoft Presidio](https://microsoft.github.io/presidio/). What's interesting here is the engineering rigor + adversarial preprocessor + audit transparency, not state-of-the-art F1.

> **Status (2026-05-05)** — first release `v0.1.0`. Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (multilingual GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, ~278M params). Shipping pipeline: `router-embedding` (~430 MB, **Google distiluse** + 5 per-domain LoRA adapters). The npm runtime downloads the full router stack from HF on first call. Bench: see [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv).

## Install

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an optional peer dependency (CPU / MPS / CUDA backend). Requires Node 24 LTS (see `.nvmrc`).

> **First-call download**: the first `sanitize()` invocation downloads ~6 GB of model artifacts from HuggingFace Hub ([`lBroth/nullpii-v10-router-embedding`](https://huggingface.co/lBroth/nullpii-v10-router-embedding) — 5 merged-LoRA ONNX shards + distiluse encoder + tokenizer + prototypes) into `~/.cache/nullpii/` (or `$XDG_CACHE_HOME/nullpii/`). One-shot; subsequent calls hit the local cache. Plan accordingly for air-gapped installs (mirror the HF repo locally and pass `modelDir`).

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

> **Status (2026-05-05)**: first release bench. nullpii numbers below come from the local Mac CPU bench (`packages/eval/published-bench/matrix.{json,csv}`). Third-party baselines wired in `bench_full.py` for a later head-to-head iteration: **Microsoft Presidio**, GLiNER (`urchade/gliner_multi_pii-v1`), `iiiorg/piiranha`, **Microsoft DeBERTa**-v3 community fine-tune, scrubadub, **NVIDIA Nemotron-PII** (`nvidia/gliner-pii`), and **OpenAI** `openai/privacy-filter` in three usage modes (naive HF / BIOES / opf-Viterbi).

Mac M-series CPU, single seed, macro F1 at IoU ≥ 0.5, partial-match span scoring on **27 datasets** — full list in the per-dataset table below.

**Bare-mode contract** — zero nullpii post-processing on competitor rows: no `_normalize_for_detection`, no boundary refine, no never-PII filter, no regex pack. The only adapter glue is the universal NER-bench plumbing applied identically to every tool:

- **Chunking 1400/200 char stride** — every ML tool has a ~512-token context limit, so documents like TAB ECHR (avg 2000+ tokens) must be split + dedupe. Same code path on `gliner-onnx-pii-fp32`, `nemotron-pii-raw`, GLiNER family, and the nullpii rows.
- **Per-tool label remap** to nullpii's 8-class schema — Microsoft Presidio emits `PERSON` / `EMAIL_ADDRESS` / `LOCATION`, NVIDIA Nemotron emits 55 fine-grained labels (`first_name`, `ssn`, `mrn`, …), Microsoft DeBERTa fine-tune emits `PER` / `LOC` / `ORG`. The bench predictor wrappers (`presidio_predictor`, `gliner_nemotron_pii_predictor`, etc.) translate those native labels to nullpii's 8-class **before** the span is compared to gold — so a Presidio `EMAIL_ADDRESS` at offset `[20:33]` is scored against gold `private_email` at `[20:33]` as a true positive. Without this bridge F1 would be ~0 even on perfectly detected spans (different label spaces). Symmetric — every cross-tool NER bench needs it; not a nullpii advantage.

### Pipeline

**Ship `nullpii-v10-router-embedding`** (distiluse + 5 LoRA adapters, ~430 MB). The npm runtime downloads from HF on first `sanitize()` call; subsequent calls hit the local cache.

#### Headline number, honest

We split the 27-dataset bench into three buckets and report each separately so the reader can judge what "F1" means:

1. **Held-out, non-adversarial (7 datasets) — F1 0.7008.** The model never saw any of these rows during training. This is the **honest OOD claim** for nullpii.
   - Datasets: `argilla-pii`, `presidio-synthetic`, `oasst-dev-planted`, `ai4privacy-300k-heldout-v10` (offset 100k+), `isotonic-{en,de,fr}-heldout-v10` (offset 200k+).

2. **Adversarial subset (11 datasets) — preprocessor-driven, not model-driven.** Synthetic perturbations (typo / unicode / whitespace / encoding / code / TextAttack 5 variants) generated post-training, so technically held-out, but most of the lift comes from the `_normalize_for_detection` preprocessor (NFKC + unidecode + zero-width strip + spaced-PII despace), not from the model. Including these brings the held-out macro down a bit (heavy whitespace+encoding rows pull the average): **F1 0.6897 over 18 held-out rows**.

3. **In-distribution diagnostic (9 datasets) — F1 0.7712, NOT a generalisation claim.** Adapters trained on slices of these datasets, so performance is in-distribution memorisation. Published for transparency only.
   - `nullpii-bench` (project-bundled, template-leaked with `dev-paste-synth-train`); `tab-echr` (legal adapter trained on TAB train, 127/127 test docs share shingles); `nemotron-pii-test` (enterprise adapter trained on Nemotron train); `ai4privacy-300k`, `ai4privacy-400k`, `isotonic-{en,de,fr,it}` (offset 0, model saw rows 0-5k of these during training).

The often-quoted **mixed F1 0.7172 (27 datasets)** is the average of all three buckets — it inflates by ~+0.07 over the honest OOD number because of the 9 leak-disclosed rows. Use the held-out 0.7008 figure for any OOD claim; quote the mixed 0.7172 only with the caveat above.

> **Two specific red-team caveats** that warrant disclosure (full report internal at `packages/eval/private/v10/RED_TEAM_AUDIT_2026-05-05.md`):
>
> 1. **`TUNE-ENTGATE-01` — gate margin tuned on `nullpii-bench`.** The router gates the `enterprise` route at margin ≥ 0.10 vs runner-up. That `0.10` value was picked by sweeping on `nullpii-bench` itself, so part of the lift on that dataset is attributable to the tuning, not to the model. A margin-sensitivity sweep `{0.0, 0.05, 0.10, 0.15}` + a held-out routing-eval corpus are on the v11 roadmap.
> 2. **`LEAK-NEMO-ENTERPRISE-01` — `enterprise` adapter trained on Nemotron train split.** Bench includes `nemotron-pii-test` (Nvidia's own test split). The enterprise adapter was trained on the train split → `nemotron-pii-test` is **in-distribution generalisation, not OOD**. We publish the row for transparency but treat the F1 as a memorisation data-point. Retrain on Faker-only US-formats is scheduled v11.

### Per-dataset F1 (`nullpii-v10-router-embedding`, the shipping pipeline)

| Dataset | n | F1 | Notes |
|---|---:|:---:|---|
| `nullpii-bench` | 264 | **0.7280** | Project-bundled OOD gold standard (real-world dev paste, RFCs, multilingual tickets) |
| `tab-echr` | 127 | **0.8862** | EU legal (TAB ECHR test split) |
| `oasst-dev-planted` | 15 | 0.4921 | Real chat text + planted PII |
| `presidio-synthetic` | 5k | 0.6907 | Faker-driven synthetic (**Microsoft Presidio Evaluator**) |
| `argilla-pii` | 2k | 0.6002 | Third-party held-out (model-suggested labels — see model card) |
| `nemotron-pii-test` | 5k | **0.7602** | **NVIDIA Nemotron-PII** test split — ⚠ in-distribution (enterprise adapter trained on NVIDIA Nemotron train split) |
| `ai4privacy-300k-heldout-v10` | 5k | 0.5283 | Held-out (offset 100k+) |
| `ai4privacy-300k` | 5k | 0.5336 | In-distribution-adjacent |
| `ai4privacy-400k` | 5k | 0.5554 | In-distribution-adjacent |
| `isotonic-en-heldout-v10` | 5k | 0.8671 | Held-out (offset 200k+) |
| `isotonic-de-heldout-v10` | 5k | 0.8746 | Held-out |
| `isotonic-fr-heldout-v10` | 5k | 0.8619 | Held-out |
| `isotonic-en` / `de` / `fr` / `it` | 5k each | 0.8783 / 0.8743 / 0.8600 / 0.8647 | Multilingual structured PII |
| `adversarial-typo` | 80 | **0.9400** | Single-char neighbour swap |
| `adversarial-unicode` | 80 | **0.9358** | Cyrillic homoglyph + zero-width insertion |
| `adversarial-whitespace` | 80 | 0.3932 | `g i a n l u c a @ g m a i l . c o m` style |
| `adversarial-encoding` | 80 | 0.1216 | Base64 / URL / HTML-entity wrapping |
| `adversarial-code` | 80 | **1.0000** | Credentials in comments / docstrings |
| `adversarial-textattack` | 1.7k | 0.6900 | TextAttack mixed perturbations |
| `textattack-{homoglyph,charswap,chardelete,charinsert,charsub}` | 334 each | 0.66 / 0.72 / 0.72 / 0.66 / 0.66 | Per-perturbation breakdown |

`adversarial-encoding` is the documented gap — base64 / URL / HTML-entity wrapping require a deobfuscation layer not in the runtime defaults.

### Competitor comparison (pending 5090 run)

The bare-mode third-party baselines — **Microsoft Presidio**, GLiNER (`urchade/gliner_multi_pii-v1`), `iiiorg/piiranha`, **Microsoft DeBERTa**-v3 community fine-tune, scrubadub, **NVIDIA Nemotron-PII** (`nvidia/gliner-pii`), **OpenAI** `openai/privacy-filter` (naive HF / BIOES / opf-Viterbi) — are wired in `bench_full.py` but require a longer-running GPU pass to publish defensible numbers. The bench surface and methodology are documented in [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md). This README will refresh with the head-to-head matrix once the GPU bench completes.

## Documentation

### Top-level

- [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) — bench methodology + competitor landscape
- [`CHANGELOG.md`](CHANGELOG.md) — release notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup + architecture rules
- [`SECURITY.md`](SECURITY.md) — threat model + vuln reporting

### v10 release docs (`docs/v10/`)

- [`V10_PLAN.md`](docs/v10/V10_PLAN.md) — release gating + status + decision tree
- [`TRAINING.md`](docs/v10/TRAINING.md) — training procedure summary (Art. 53 transparency)
- [`AUDIT_2026-05-04.md`](docs/v10/AUDIT_2026-05-04.md) — security audit (25 findings, all closed)
- Model cards — [`docs/v10/model-cards/`](docs/v10/model-cards/):
  - [`README.md`](docs/v10/model-cards/README.md) — index + train-vs-eval overlap matrix
  - [`router-embedding.md`](docs/v10/model-cards/router-embedding.md) — shipping pipeline (distiluse + 5 LoRA)
  - [`adapter-devops.md`](docs/v10/model-cards/adapter-devops.md)
  - [`adapter-legal.md`](docs/v10/model-cards/adapter-legal.md)
  - [`adapter-medical.md`](docs/v10/model-cards/adapter-medical.md) — ⚠ non-HIPAA
  - [`adapter-narrative.md`](docs/v10/model-cards/adapter-narrative.md)
  - [`adapter-enterprise.md`](docs/v10/model-cards/adapter-enterprise.md) — Nemotron-aug, Nemotron-test in-distribution disclosed

### Compliance (`docs/compliance/`)

- [`DPIA_TEMPLATE.md`](docs/compliance/DPIA_TEMPLATE.md) — GDPR Art. 35 template (buyer-facing)

> Internal-only compliance docs (held-out routing-eval plan, SOC2 Type II readiness gap analysis) live under `packages/eval/private/compliance/` and are not part of the public release surface.

### Eval kit

- [`packages/eval/README.md`](packages/eval/README.md) — bench harness + scripts inventory
- [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md) — dataset cards + licenses
- [`examples/README.md`](examples/README.md) — TS usage examples

The unified release bench (head-to-head vs **Microsoft Presidio**, GLiNER (`urchade/gliner_multi_pii-v1`), **NVIDIA Nemotron-PII**, `iiiorg/piiranha`, **Microsoft DeBERTa**-v3 fine-tune, scrubadub, and **OpenAI** `openai/privacy-filter` in three usage modes — naive HF / BIOES / opf-Viterbi) will publish after the overnight run. README will refresh with v10 numbers at that point.

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Runtime tree is 100% permissive (MIT / Apache-2.0 / BSD / ISC / CC0); verified by `npm run license-check` in CI.

## Citation

> nullpii contributors (2026). *nullpii: local PII sanitization for LLM prompts.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, Zaratiana et al. NAACL 2024). Per-domain LoRA adapters trained on `ai4privacy/pii-masking-300k`, `Isotonic/pii-masking-200k`, **NVIDIA Nemotron-PII** (`nvidia/Nemotron-PII`), TAB ECHR (Pilán et al. ACL 2022), MEDDOCAN (IBERLEF 2019), plus internal synth + adversarial subsets.
