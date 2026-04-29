<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

# nullpii

[![CI](https://github.com/lBroth/nullpii/actions/workflows/ci.yml/badge.svg)](https://github.com/lBroth/nullpii/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/nullpii?color=cb3837)](https://www.npmjs.com/package/nullpii)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)

> **A study + reproducibility kit.** What does it cost — in F1, latency, and engineering — to replace the well-known `openai/privacy-filter` (1.5B, gpt-oss style) with a fine-tuned, much smaller `urchade/gliner_multi_pii-v1` (278M, older) on the same PII detection task?
>
> **TL;DR**: a 2-round fine-tune lifts GLiNER from 0.46–0.51 multilingual F1 to **0.93–0.97 (en/de/fr/it)** at ~14 ms/sample on a 5090 GPU and ~125 ms/sample on a Mac CPU. ONNX INT4 (`MatMulNBitsQuantizer`, 844 MB) keeps the F1 but only saves memory, not latency. ONNX CPU on Apple Silicon is ~25× faster than ONNX CPU on Linux x86 for this model. INT8 dynamic quant collapses (avoid).
>
> **The openai/privacy-filter caveat**: per its model card, inference is supposed to apply a constrained Viterbi BIOES decoder; the upstream `transformers` integration ships only per-token logits. Calling `transformers.pipeline()` with default `aggregation_strategy="simple"` therefore produces fragmented spans (`.com`, `+1-843-555-014` then `2`, `aitre`). That is **not the model's intended quality** — just naive HF usage. To get its real output you need either (a) the official [`opf` CLI](https://github.com/openai/privacy-filter), or (b) nullpii's runtime, which both ship the constrained Viterbi.

## What's in this repo

Two deliverables and the experiment that produced them:

1. **npm library** — `nullpii` (this package). Sanitize / restore engine over `openai/privacy-filter` with the constrained Viterbi BIOES decoder + chunking + recognizer post-pass + reversible vault. CLI binary `nullpii sanitize|restore|scan|benchmark|...` plus a TS API (`sanitize()`, `restore()`, `NullPii` class).
2. **HuggingFace model** — [`lBroth/nullpii`](https://huggingface.co/lBroth/nullpii) (publication script under `packages/eval/scripts/release/`). GLiNER fine-tune in PT, ONNX FP32 and ONNX INT4 variants. Pin `local_files_only=True` and use the standard `gliner.GLiNER.from_pretrained(...)` API.
3. **Reproducibility kit** — `packages/eval/` with the full bench harness, dataset loaders (ai4privacy, Isotonic, the project's own `nullpii-bench`), the training scripts that produced v2, and the comparison results (`packages/eval/results/`).

## The headline comparison

Multilingual F1 (preview, n=100 per dataset, IoU ≥ 0.5; full bench is the next milestone):

| Dataset                  | baseline GLiNER | **nullpii PT FP32** | nullpii ONNX INT4 | openai (proper Viterbi) | openai (HF naive) |
| ------------------------ | --------------: | -------------: | -----------: | ----------------------: | ----------------: |
| isotonic-en              |           0.462 |          0.951 |    **0.961** |                       — |  fragmented (n/a) |
| isotonic-de              |           0.497 |          0.932 |    **0.939** |                       — |  fragmented (n/a) |
| isotonic-fr              |           0.471 |          0.947 |    **0.967** |                       — |  fragmented (n/a) |
| isotonic-it              |           0.509 |          0.938 |    **0.959** |                       — |  fragmented (n/a) |
| ai4privacy-300k          |           0.309 |          0.800 |    **0.864** |                       — |  fragmented (n/a) |
| dev-prompts-synth        |       **0.618** |          0.821 |        0.801 |                       — |  fragmented (n/a) |

`COMPARISONS.md` carries the full multi-platform tables, the
in-Python BIOES decoder used to recover most of the openai/privacy-filter
quality without extra deps, and the qualitative comparison
(`packages/eval/results/train/qualitative_compare.md`) over 30 real
prompts (medical records, contracts, multilingual itineraries, GitHub
issues from openai/privacy-filter, JP/CN/KR cases that surface known
non-Latin gaps).

## Library mode (the npm path)

```ts
import { sanitize, restore } from 'nullpii';

const safe = await sanitize('Email John Smith at john@acme.com about his SSN 123-45-6789');
// safe.text = 'Email [[NULLPII:private_person:0]] at [[NULLPII:private_email:0]] about his [[NULLPII:secret:0]]'
// safe.session = opaque session id

// ... pass safe.text to any LLM ...
const reply = `Hello [[NULLPII:private_person:0]], we received your request.`;

const back = await restore(reply, safe.session);
// back = 'Hello John Smith, we received your request.'
```

Programmatic API (full control):

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });

const { sessionId, sanitized, spans } = await np.sanitize(
  "Hi, I'm Maria Rossi (maria.rossi@example.it). My order #ACME-2026-04812 shipped to via Roma 45, 00184 Roma.",
);

// ... LLM call uses `sanitized` ...
const reply = '...';

const { restored } = np.restore(reply, sessionId);
await np.dispose();
```

CLI:

```bash
$ npx nullpii sanitize --stdin --format json < customer-email.txt | jq .sanitized
"Hi [[NULLPII:private_person:0]], thanks for reaching out about [[NULLPII:account_number:0]]..."
```

## What gets caught (8 categories)

| Label             | Examples                                             |
| ----------------- | ---------------------------------------------------- |
| `private_person`  | personal names                                       |
| `private_email`   | email addresses                                      |
| `private_phone`   | phone / fax numbers                                  |
| `private_address` | street addresses                                     |
| `private_date`    | birth dates, hire dates, anniversaries               |
| `private_url`     | private URLs (admin panels, internal wikis)          |
| `account_number`  | bank accounts, IBAN, customer IDs                    |
| `secret`          | API keys, passwords, JWT tokens                      |

For known formats with low ML coverage (your internal employee ID, AWS
access keys, SWIFT BIC), add custom regex-based recognizers as a
post-pass:

```ts
np.addRecognizer({
  id: 'aws-key',
  pattern: /\bAKIA[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
});
```

ML-first, regex-augmented. No "no regex" purity theatre.

## Install

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an **optional peer dependency** — install it only
if you want the Node-side backend (CPU / MPS / CUDA). The
library is also usable in browsers / WebGPU via the `nullpii/backend/*`
subpath imports.

Requires **Node 24 LTS** (see `.nvmrc`).

## Backends

| Backend | Platform              | Notes                                              |
| ------- | --------------------- | -------------------------------------------------- |
| `cpu`   | All                   | Universal. Currently fastest on macOS.             |
| `mps`   | Apple Silicon         | CoreML EP; partial op coverage — see `EVAL_RESULTS.md`. |
| `cuda`  | Linux/Windows + NVIDIA| Tensor cores on Volta+. CUDA EP via ORT.           |

Auto-selects in priority **CUDA → MPS → CPU**. Default variant
is `int4` (~875 MB, ~6% F1 drop). Pin `variant: 'fp32'` (~5 GB) when
you need maximum accuracy or a regression baseline.

## Architecture

```
input text
   │
   ▼                  ┌──────────────────────────────┐
tokenizer ─offsets─►  │ ONNX Runtime (CPU / MPS /    │
   │                  │             CUDA EP)  │
   │                  │                              │
   ▼                  └────────────────┬─────────────┘
attention_mask                          │ logits [seq × 33]
                                        ▼
                            constrained Viterbi (BIOES)
                                        │
                                        ▼
                              char-level PiiSpan[]
                                        │
                                        ▼
              vault.sanitize ──► (placeholder text, sessionId)
                                        │
                                        ▼
                            (LLM call with placeholder text)
                                        │
                                        ▼
                            vault.restore(sessionId) ──► original text
```

See [docs](./docs/) for the full guide.

## nullpii-bench (eval dataset)

We ship a small multilingual PII evaluation set under
`packages/eval/datasets/nullpii-bench.jsonl`:

- **271 samples**, **680 PII spans**, **5 locales** (en / it / de / fr / es), Apache-2.0.
- Three subsets: `bundled` (202 dev-style prompts — PR reviews, deploy logs, RFCs, customer-support tickets), `adversarial` (decoys), `long-prompts` (62 ~3k-char prompts that exercise chunking).
- Schema: `{ id, locale, subset, text, spans }` per row. See [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md).

Anyone can run other PII tools against the same set to reproduce or
extend the comparison — patches welcome.

## Privacy guarantees

- The PII detection step **never touches the network**.
- The vault is **in-memory only** — never serialized to disk.
- `destroySession()` purges the mapping.
- No `console.log` of PII; debug logs only carry counts and short ids.
- See [SECURITY.md](SECURITY.md) for the full threat model and how to report a vulnerability.

## License

Apache 2.0 — see [LICENSE](LICENSE), [NOTICE](NOTICE),
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

The full runtime tree is **100% permissive** (MIT / Apache-2.0 / BSD /
ISC / CC0). Verified by `npm run license-check` in CI.
