# Getting Started

## Install

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an **optional** peer dependency. Install it only if
you need a Node-side backend (CPU / MPS / CUDA / ROCm).

::: tip Node version
nullpii requires **Node 24 LTS** or later. See `.nvmrc`.
:::

## Quick start

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });

const { sessionId, sanitized } = await np.sanitize(
  'Hi, my name is John Smith and my email is john@example.com.',
);

// → "Hi, my name is [[NULLPII:private_person:0]] and my email is [[NULLPII:private_email:0]]."

// ... pass `sanitized` to any LLM ...
const reply = `Hello [[NULLPII:private_person:0]]`;

const { restored } = np.restore(reply, sessionId);
// → "Hello John Smith"

await np.dispose();
```

## What gets detected

Eight categories from `openai/privacy-filter`:

| Label             | Examples                                              |
| ----------------- | ----------------------------------------------------- |
| `account_number`  | bank account numbers, IBAN, customer IDs              |
| `private_address` | physical street addresses                             |
| `private_date`    | birth dates, hire dates, anniversaries                |
| `private_email`   | email addresses                                       |
| `private_person`  | personal names                                        |
| `private_phone`   | phone numbers, fax numbers                            |
| `private_url`     | private URLs (admin panels, internal wikis)           |
| `secret`          | API keys, passwords, JWT tokens                       |

The model emits BIOES tags (B-, I-, E-, S-) for each category. nullpii
runs a constrained Viterbi decoder to enforce valid label transitions
and produces character-level spans against your original input.

## Choosing a backend

`{ backend: 'auto' }` (the default) picks **CUDA → MPS → ROCm → CPU**,
in that priority. To pin one explicitly:

```ts
new NullPii({ backend: 'cpu', variant: 'int8' });   // production-safe
new NullPii({ backend: 'mps', variant: 'fp16' });   // Apple Silicon
new NullPii({ backend: 'cuda', variant: 'fp16' });  // NVIDIA
```

## CLI

```bash
npx nullpii scan "My email is john@example.com"
npx nullpii sanitize --stdin --format json < prompt.txt
npx nullpii models list
npx nullpii benchmark --model-dir ./.nullpii/models/...
```
