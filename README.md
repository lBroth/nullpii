# nullpii

Local PII sanitization for LLM prompts. ML-based span detection + reversible in-memory vault — pass placeholders to your LLM, restore original values from the response.

> **Status (2026-05-04)** — v10 release-candidate. Two routers under evaluation: `router-embedding` (~430 MB, distiluse + 5 LoRA adapters) and `router-xlmr` (~1.4 GB, xlm-roberta + 4 LoRA adapters). The unified release benchmark is pending; release numbers, HuggingFace model cards, and the merged-LoRA ONNX export for npm will land after the overnight bench completes. See [`docs/v10/V10_PLAN.md`](docs/v10/V10_PLAN.md) for current state and gating criteria.

## Install

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an optional peer dependency (CPU / MPS / CUDA backend). Requires Node 24 LTS (see `.nvmrc`).

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
| `private_person`  | personal names                                    |
| `private_email`   | email addresses                                   |
| `private_phone`   | phone / fax numbers                               |
| `private_address` | street addresses                                  |
| `private_date`    | birth / hire dates                                |
| `private_url`     | private URLs (admin panels, internal wikis)       |
| `account_number`  | bank accounts, IBAN, SSN, customer IDs            |
| `secret`          | API keys, tokens, passwords, JWT, PEM private keys |

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

> **Status (2026-05-05)**: v10 release-candidate. nullpii numbers below come from the unified release bench (`packages/eval/results/bench-v10-release-local/matrix.{json,csv}`). The bare third-party baselines (presidio, gliner-onnx-pii-fp32, piiranha, deberta, scrubadub, nemotron-pii-raw, openai naive/BIOES/Viterbi) ship a published `matrix.json` row in the next bench iteration on a 5090 GPU host.

Mac M-series CPU, single seed, macro F1 at IoU ≥ 0.5. Bare-mode contract: no competitor row wraps nullpii post-processing. 27 of 31 datasets benched (4 require gated HuggingFace access: lmsys / enron / stackoverflow / thestack).

### Release pipeline decision

**Ship `nullpii-v10-router-embedding`** (distiluse + 5 LoRA, ~430 MB).

Per release gating step 2 in [`docs/v10/V10_PLAN.md`](docs/v10/V10_PLAN.md): F1 delta ≤ 0.02 → storage tiebreaker wins → distiluse.

| Pipeline | macro F1 (27 datasets) | Storage | Wins (head-to-head) |
|---|:---:|:---:|:---:|
| **`nullpii-v10-router-embedding`** (default) | **0.7172** | **~430 MB** | 4 |
| `nullpii-v10-router-xlmr` (alt) | 0.7076 | ~1.4 GB | 21 |
| Ties | — | — | 2 |

The xlm-roberta router wins more datasets but by smaller margins (typically +0.01–0.02). distiluse wins `nullpii-bench` OOD (the project-bundled gold standard) by **+0.118 F1** (0.7280 vs 0.6096) and the adversarial subset by **+0.062**. Aggregate delta is within the storage-tiebreaker band.

### Per-dataset F1 (`nullpii-v10-router-embedding`, the shipping pipeline)

| Dataset | n | F1 | Notes |
|---|---:|:---:|---|
| `nullpii-bench` | 264 | **0.7280** | Project-bundled OOD gold standard (real-world dev paste, RFCs, multilingual tickets) |
| `tab-echr` | 127 | **0.8862** | EU legal (TAB ECHR test split) |
| `oasst-dev-planted` | 15 | 0.4921 | Real chat text + planted PII |
| `presidio-synthetic` | 5k | 0.6907 | Faker-driven synthetic |
| `argilla-pii` | 2k | 0.6002 | Third-party held-out (model-suggested labels — see model card) |
| `nemotron-pii-test` | 5k | **0.7602** | ⚠ in-distribution (enterprise adapter trained on Nemotron train split) |
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

The bare-mode third-party baselines (presidio, gliner-onnx-pii-fp32, piiranha, deberta, scrubadub, nemotron-pii-raw, openai naive/BIOES/Viterbi) are wired in `bench_full.py` but require a longer-running GPU pass to publish defensible numbers. The bench surface and methodology are documented in [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md). This README will refresh with the head-to-head matrix once the GPU bench completes.

## Documentation

### Top-level

- [`COMPETITIVE_ANALYSIS.md`](COMPETITIVE_ANALYSIS.md) — bench methodology + competitor landscape
- [`CHANGELOG.md`](CHANGELOG.md) — release notes
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — dev setup + architecture rules
- [`SECURITY.md`](SECURITY.md) — threat model + vuln reporting

### v10 release docs (`docs/v10/`)

- [`V10_PLAN.md`](docs/v10/V10_PLAN.md) — release gating + status + decision tree
- [`TRAINING.md`](docs/v10/TRAINING.md) — training procedure summary (Art. 53 transparency)
- [`AUDIT_2026-05-04.md`](docs/v10/AUDIT_2026-05-04.md) — security audit (25 findings, 17 closed)
- Model card drafts — [`docs/v10/model-cards/`](docs/v10/model-cards/):
  - [`README.md`](docs/v10/model-cards/README.md) — index + train-vs-eval overlap matrix
  - [`router-embedding.md`](docs/v10/model-cards/router-embedding.md) — release-candidate A
  - [`router-xlmr.md`](docs/v10/model-cards/router-xlmr.md) — release-candidate B
  - [`adapter-devops.md`](docs/v10/model-cards/adapter-devops.md)
  - [`adapter-legal.md`](docs/v10/model-cards/adapter-legal.md)
  - [`adapter-medical-experimental.md`](docs/v10/model-cards/adapter-medical-experimental.md) — ⚠ non-HIPAA
  - [`adapter-narrative.md`](docs/v10/model-cards/adapter-narrative.md)
  - [`adapter-enterprise.md`](docs/v10/model-cards/adapter-enterprise.md) — Nemotron-aug

### Compliance (`docs/compliance/`)

- [`DPIA_TEMPLATE.md`](docs/compliance/DPIA_TEMPLATE.md) — GDPR Art. 35 template (buyer-facing)

> Internal-only compliance docs (held-out routing-eval plan, SOC2 Type II readiness gap analysis) live under `packages/eval/private/compliance/` and are not part of the public release surface.

### Eval kit

- [`packages/eval/README.md`](packages/eval/README.md) — bench harness + scripts inventory
- [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md) — dataset cards + licenses
- [`examples/README.md`](examples/README.md) — TS usage examples

The unified release bench (head-to-head vs Presidio, GLiNER-base, Nemotron-PII, piiranha, deberta, scrubadub, openai/privacy-filter naive/BIOES/Viterbi) will publish after the overnight run. README will refresh with v10 numbers at that point.

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Runtime tree is 100% permissive (MIT / Apache-2.0 / BSD / ISC / CC0); verified by `npm run license-check` in CI.

## Citation

> nullpii contributors (2026). *nullpii: local PII sanitization for LLM prompts.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, mDeBERTa-v3-base + GLiNER head). Per-domain LoRA adapters trained on `ai4privacy/pii-masking-300k`, `Isotonic/pii-masking-200k`, `nvidia/Nemotron-PII`, TAB ECHR, MEDDOCAN, plus internal synth + adversarial subsets.
