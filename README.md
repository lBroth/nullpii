# nullpii

[![CI](https://github.com/lBroth/nullpii/actions/workflows/ci.yml/badge.svg)](https://github.com/lBroth/nullpii/actions/workflows/ci.yml)
[![docs](https://github.com/lBroth/nullpii/actions/workflows/docs.yml/badge.svg)](https://lbroth.github.io/nullpii/)
[![npm](https://img.shields.io/npm/v/nullpii?color=cb3837)](https://www.npmjs.com/package/nullpii)
[![license](https://img.shields.io/badge/license-Apache--2.0-blue)](LICENSE)
[![model](https://img.shields.io/badge/model-openai%2Fprivacy--filter-black)](https://huggingface.co/openai/privacy-filter)

> **Stop leaking PII to LLMs.** ML-first sanitization with OpenAI's
> `privacy-filter` model, plus user-defined recognizers for known
> formats (IBAN, AWS keys, internal IDs). Send the redacted text to
> Claude, restore originals in the response — automatically. Zero
> cloud calls. 100% permissive licenses.
>
> **Real numbers** (eval suite, partial-match F1, 32k samples across
> 16 datasets on M5 Pro 48GB; full table in
> [docs/guide/eval-results.md](docs/guide/eval-results.md)):
> - **bundled dev prompts** (202 multi-locale): nullpii **avg 0.739**
>   vs OpenAI bare HF 0.487 vs Presidio 0.475 vs spaCy 0.132.
> - **Isotonic/pii-masking-200k** (5k×4 locales): nullpii **0.581**
>   vs OpenAI bare HF 0.385 vs Presidio 0.427 vs spaCy 0.110.
> - **Presidio synthetic** (5000): virtual tie, nullpii 0.576 vs
>   Presidio 0.575 vs OpenAI bare HF 0.390.
> - **long-prompts-en** (chunking proof): nullpii **0.600** vs all
>   others <0.350 — chunking captures PII past the 512-tok boundary
>   that bare pipelines silently truncate.
> - **WikiAnn** (Wikipedia NER, 5 locales): spaCy wins. Wikipedia ≠ PII.
>
> Headline: **nullpii beats the upstream OpenAI HF pipeline by +0.226
> F1 on average** — same model, attributable entirely to nullpii's
> runtime (chunking + constrained Viterbi + forward-backward posterior
> + recognizer post-pass).
>
> Detection runs locally via OpenAI's
> [`privacy-filter`](https://huggingface.co/openai/privacy-filter)
> (Apache 2.0, 1.3B param token classifier, ONNX fp16 by default;
> int4f16 for edge installs) — no cloud calls. Tradeoff: nullpii is
> ~4× slower per call than Presidio.
> See [vs Presidio + spaCy](docs/guide/vs-presidio.md) for full
> multi-locale tables + reproduce script.

```ts
// Without nullpii ❌
await client.messages.create({
  messages: [{ role: 'user', content: 'Email John Smith at john@acme.com about his SSN 123-45-6789' }],
});
// → John's name, email, SSN all leave your machine.

// With nullpii ✅
import { withNullPii } from 'nullpii/middleware/anthropic';
const safe = withNullPii(client);
await safe.messages.create({
  messages: [{ role: 'user', content: 'Email John Smith at john@acme.com about his SSN 123-45-6789' }],
});
// → "Email [[NULLPII:private_person:0]] at [[NULLPII:private_email:0]] about
//    his [[NULLPII:secret:0]]" goes on the wire.
//   The reply is restored to readable English before you see it.
//   John's PII never leaves your process.
```

---

## Use it with Claude Code (1-line install)

`nullpii` ships a [Claude Code](https://claude.com/claude-code) plugin
that intercepts every prompt automatically. **No code changes — just
config.**

```bash
npm install -g @nullpii/claude-code
```

```jsonc
// .claude/settings.json
{
  "plugins": ["@nullpii/claude-code"],
  "nullpii": { "backend": "auto" }
}
```

From this point on, every prompt you send through Claude Code is
sanitized before it leaves your machine, and every response has
placeholders restored in-place. Multi-turn conversations reuse the same
vault, so a follow-up that quotes back an earlier value resolves
correctly.

---

## Why this exists

Most PII redaction is regex. Regex breaks on:

- non-ASCII names (`Müller`, `田中`, `O'Connor`)
- formats it wasn't trained on (`+44 (0)20 7946 0958` vs `(212) 555-7890 ext. 405`)
- ambiguous strings (is `4242 4242 4242 4242` a card or a hash?)
- context-dependent fields ("born March 14" vs "March 14 release")

`openai/privacy-filter` is a 1.3B-parameter token classifier trained
specifically for this. It catches what regex misses (names, addresses,
contextual dates), runs locally in ONNX Runtime, and emits
character-level spans you can reverse.

For known formats with low ML coverage (your internal employee ID,
AWS access keys, SWIFT BIC), add custom regex-based recognizers as
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

`nullpii` wraps it with:

- **a vault** — each detected span becomes a typed placeholder
  (`[[NULLPII:private_person:0]]`); the original lives only in an
  in-memory `Map` keyed by an opaque session id
- **a router** — picks CUDA → MPS → ROCm → CPU automatically, all
  optional via `peerDependency`
- **drop-in middleware** — `withNullPii(client)` for `@anthropic-ai/sdk`;
  the proxy preserves your client's TypeScript types
- **a constrained Viterbi pass** — enforces valid BIOES transitions so
  the model can't emit garbage like `O → I-X`

---

## Wow examples

### 1. Customer support agent (Anthropic SDK)

```ts
import Anthropic from '@anthropic-ai/sdk';
import { withNullPii } from 'nullpii/middleware/anthropic';

const safe = withNullPii(new Anthropic());

const ticket = `
  Hi, I'm Maria Rossi (maria.rossi@example.it). My order #ACME-2026-04812
  shipped to via Roma 45, 00184 Roma, Italia, but never arrived. My
  customer card ending 4242 was charged. Help?
`;

const reply = await safe.messages.create({
  model: 'claude-haiku-4-5',
  max_tokens: 400,
  messages: [{ role: 'user', content: ticket }],
});
// reply.content[0].text reads naturally, with Maria, her email, and
// the address restored — but the LLM only ever saw placeholders.
```

### 2. Programmatic for RAG / batch jobs

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });

for (const doc of corpus) {
  const { sanitized, sessionId, spans } = await np.sanitize(doc.text);
  // index sanitized text in your vector DB; keep sessionId for restore
  await indexer.upsert(doc.id, embed(sanitized), { sessionId, spans });
}
```

### 3. CLI for one-off scrubs

```bash
$ npx nullpii sanitize --stdin --format json < customer-email.txt | jq .sanitized
"Hi [[NULLPII:private_person:0]], thanks for reaching out about [[NULLPII:account_number:0]]..."
```

---

## Programmatic API (when middleware is too magic)

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });

const { sessionId, sanitized, spans } = await np.sanitize(
  'Hi, my name is John Smith and my email is john@example.com.',
);
// sanitized = "Hi, my name is [[NULLPII:private_person:0]] and my email is [[NULLPII:private_email:0]]."
// spans     = [{ label: 'private_person', start: 14, end: 24, text: 'John Smith', score: 0.9996 }, ...]

// ... pass `sanitized` to any LLM ...
const reply = `Hello [[NULLPII:private_person:0]]`;

const { restored } = np.restore(reply, sessionId);
// restored = "Hello John Smith"

await np.dispose();
```

---

## Install

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is an **optional peer dependency** — installed only
if you want a Node-side backend (CPU / MPS / CUDA / ROCm).

Requires **Node 24 LTS** (see `.nvmrc`).

---

## What gets detected

Eight categories from `openai/privacy-filter`:

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

Decoded from BIOES tags via a constrained Viterbi pass against the
char-level offsets from the tokenizer.

---

## Backends

| Backend | Platform              | Notes                                              |
| ------- | --------------------- | -------------------------------------------------- |
| `cpu`   | All                   | Universal. Currently fastest on macOS.             |
| `mps`   | Apple Silicon         | CoreML EP; partial op coverage — see BENCHMARK.md. |
| `cuda`  | Linux/Windows + NVIDIA| Tensor cores on Volta+. CUDA EP via ORT.           |
| `rocm`  | Linux + AMD           | MFMA on RDNA3+ / CDNA. ROCm EP via ORT.            |

Auto-selects in priority **CUDA → MPS → ROCm → CPU**. Pin one with
`{ backend: 'cpu', variant: 'fp16' }` (default), or `'int4f16'` for a
~772 MB download (~6% F1 drop).

---

## Architecture

```
input text
   │
   ▼                  ┌──────────────────────────────┐
tokenizer ─offsets─►  │ ONNX Runtime (CPU / MPS /    │
   │                  │             CUDA / ROCm EP)  │
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

See [docs](./docs/) for the full guide and API reference.
See [ROADMAP.md](./ROADMAP.md) for what's coming next.

---

## Privacy guarantees

- The PII detection step **never touches the network**.
- The vault is **in-memory only** — never serialized to disk.
- `destroySession()` purges the mapping; sessions also auto-destroy at
  the end of every middleware-wrapped LLM call.
- No `console.log` of PII; debug logs only carry counts and short ids.
- See [SECURITY.md](SECURITY.md) for the full threat model and how to
  report a vulnerability.

---

## License

Apache 2.0 — see [LICENSE](LICENSE), [NOTICE](NOTICE),
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

The full runtime tree is **100% permissive** (MIT / Apache-2.0 / BSD /
ISC / CC0). Verified by `npm run license-check` in CI.
