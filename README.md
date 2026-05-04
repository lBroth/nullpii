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

## Research / benchmarks

- Engineering journal: [`docs/v10/V10_JOURNAL.md`](docs/v10/V10_JOURNAL.md)
- Plan + release gating: [`docs/v10/V10_PLAN.md`](docs/v10/V10_PLAN.md)
- Security audit (2026-05-04): [`docs/v10/AUDIT_2026-05-04.md`](docs/v10/AUDIT_2026-05-04.md)
- Eval kit (datasets, scripts, LoRA training): `packages/eval/`

The unified release bench (head-to-head vs Presidio, GLiNER-base, Nemotron-PII, piiranha, deberta, scrubadub, openai/privacy-filter naive/BIOES/Viterbi) will publish after the overnight run. README will refresh with v10 numbers at that point.

## License

Apache 2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Runtime tree is 100% permissive (MIT / Apache-2.0 / BSD / ISC / CC0); verified by `npm run license-check` in CI.

## Citation

> nullpii contributors (2026). *nullpii: local PII sanitization for LLM prompts.* https://github.com/lBroth/nullpii

Built on [`urchade/gliner_multi_pii-v1`](https://huggingface.co/urchade/gliner_multi_pii-v1) (GLiNER, mDeBERTa-v3-base + GLiNER head). Per-domain LoRA adapters trained on `ai4privacy/pii-masking-300k`, `Isotonic/pii-masking-200k`, `nvidia/Nemotron-PII`, TAB ECHR, MEDDOCAN, plus internal synth + adversarial subsets.
