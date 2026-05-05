<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

Local PII sanitization for LLM prompts. ML-based span detection + reversible in-memory vault — pass placeholders to your LLM, restore original values from the response.

> **Status (2026-05-05)** — first release. Local PII detection built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (multilingual GLiNER, **Microsoft mDeBERTa-v3** base + GLiNER head, ~278M params). Shipping pipeline: `router-embedding` (~430 MB, **Google distiluse** + 5 LoRA adapters per domain). The npm runtime ships the full router stack via HF Hub on first call. Bench: see [`packages/eval/published-bench/matrix.csv`](packages/eval/published-bench/matrix.csv).

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

> **Status (2026-05-05)**: first release bench. nullpii numbers below come from the local Mac CPU bench (`packages/eval/published-bench/matrix.{json,csv}`). Third-party baselines wired in `bench_full.py` for a later head-to-head iteration: **Microsoft Presidio**, GLiNER (`urchade/gliner_multi_pii-v1`), `iiiorg/piiranha`, **Microsoft DeBERTa**-v3 community fine-tune, scrubadub, **NVIDIA Nemotron-PII** (`nvidia/gliner-pii`), and **OpenAI** `openai/privacy-filter` in three usage modes (naive HF / BIOES / opf-Viterbi).

Mac M-series CPU, single seed, macro F1 at IoU ≥ 0.5. Bare-mode contract: no competitor row wraps nullpii post-processing — no `_normalize_for_detection`, no boundary refine, no never-PII filter, no regex pack. Only chunking 1400/200 stride + per-tool label remap (the cross-schema bridge required for F1 comparability) survive on competitor rows. 27 of 31 datasets benched (4 require gated HuggingFace access: lmsys / enron / stackoverflow / thestack).

### Pipeline

**Ship `nullpii-v10-router-embedding`** (distiluse + 5 LoRA adapters, ~430 MB). The npm runtime downloads from HF on first `sanitize()` call; subsequent calls hit the local cache.

| Subset | macro F1 distiluse |
|---|:---:|
| **Held-out non-adversarial** (7 datasets — argilla-pii, presidio-synthetic, oasst-dev-planted, ai4privacy heldout, isotonic en/de/fr heldout) | **0.7008** |
| Held-out incl adversarial (18 datasets — adds 11 typo / unicode / whitespace / encoding / code / textattack-* rows) | 0.6897 |
| Mixed bench (27 datasets, includes 9 in-distribution rows below) | 0.7172 |
| In-distribution diagnostic (9 datasets, all leak-disclosed: nullpii-bench, tab-echr, nemotron-pii-test, ai4privacy/isotonic offset-0) | 0.7712 |

The honest **OOD F1 is ~0.70 macro** (held-out non-adversarial). Mixed 0.7172 inflates by ~+0.07 from the 9 leak-disclosed rows.

> **Caveats** (`TUNE-ENTGATE-01` + `LEAK-NEMO-ENTERPRISE-01` from the red-team audit at `packages/eval/private/v10/RED_TEAM_AUDIT_2026-05-05.md`):
> - The enterprise-route gate margin (`0.10`) was tuned on `nullpii-bench`. Some of the +0.118 nullpii-bench distiluse delta is attributable to that tuning. A margin-sensitivity sweep `{0.0, 0.05, 0.10, 0.15}` is on the v11 roadmap.
> - The `enterprise` adapter is trained on **NVIDIA Nemotron-PII** (`nvidia/Nemotron-PII`) train split. `nemotron-pii-test` is in-distribution generalisation, not OOD. Retrain on Faker-only US-formats scheduled v11.

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
  - [`adapter-medical-experimental.md`](docs/v10/model-cards/adapter-medical-experimental.md) — ⚠ non-HIPAA
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
