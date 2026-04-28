<p align="center">
  <img src="./assets/logo.png" alt="nullpii" width="128" height="128" />
</p>

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
> **Real numbers** — 7-way head-to-head, 32k samples, 16 datasets, M5
> Pro 48GB. Average PII F1 (excludes WikiAnn = general NER, not PII):
>
> | Tool | avg PII F1 | latency ms/sample |
> | --- | ---: | ---: |
> | **nullpii** | **0.655** | 43.9 |
> | GLiNER (`urchade/gliner_multi_pii-v1`) | 0.603 | 104.7 |
> | Microsoft Presidio | 0.455 | 15.1 |
> | piiranha-v1 (DeBERTa-v3) | 0.439 | 59.0 |
> | OpenAI bare HF (upstream `privacy-filter`) | 0.430 | 90.4 |
> | DeBERTa PII (`lakshyakh93/deberta_finetuned_pii`) | 0.419 | 58.3 |
> | bare spaCy NER | 0.122 | 13.7 |
>
> Highlights:
> - **+0.226 F1 vs OpenAI bare HF** (same upstream model, default HF
>   decoder) — attributable entirely to nullpii's runtime: chunking +
>   constrained Viterbi + forward-backward posterior + recognizer
>   post-pass.
> - **GLiNER is the closest competitor** (0.603 avg). Wins 4/5 bundled
>   non-English locales but **scores 0.000 on long-prompts-en** —
>   max-length truncation, no chunking.
> - **`long-prompts-en` (chunking proof)**: nullpii 0.600, every other
>   tool <0.36 — bare pipelines silently truncate PII past 512 tokens.
> - **Presidio synthetic 5k**: GLiNER 0.656 narrowly tops everyone (it
>   was trained on synthetic-pii data); nullpii second 0.591.
> - WikiAnn (Wikipedia NER): spaCy wins as expected — not a PII test.
>
> Detection runs locally via OpenAI's
> [`privacy-filter`](https://huggingface.co/openai/privacy-filter)
> (Apache 2.0, 1.3B param token classifier, ONNX fp16 by default;
> int4f16 for edge installs) — no cloud calls. Throughput tradeoff:
> nullpii sits in the middle of the latency curve, ~3× faster than
> the slowest competitor (GLiNER) and ~3× slower than Presidio.
> See [Comparisons](docs/guide/comparisons.md) for full multi-locale
> tables + reproduce script.

**With nullpii ✅** — every prompt sent through Claude Code:

```text
"Email John Smith at john@acme.com about his SSN 123-45-6789"
        ↓ sanitize ↓
"Email [[NULLPII:private_person:0]] at [[NULLPII:private_email:0]] about
 his [[NULLPII:secret:0]]"
        ↓ goes on the wire ↓
        ↓ Claude responds, placeholders restored in-place ↓
"Drafted: Hi John Smith, regarding your SSN 123-45-6789…"
```

John's PII never leaves your process.

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
- **a constrained Viterbi pass** — enforces valid BIOES transitions so
  the model can't emit garbage like `O → I-X`

---

## Wow examples

### 1. Programmatic for RAG / batch jobs

```ts
import { NullPii } from 'nullpii';

const np = new NullPii({ backend: 'auto' });

for (const doc of corpus) {
  const { sanitized, sessionId, spans } = await np.sanitize(doc.text);
  // index sanitized text in your vector DB; keep sessionId for restore
  await indexer.upsert(doc.id, embed(sanitized), { sessionId, spans });
}
```

### 2. CLI for one-off scrubs

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

## nullpii-bench (eval dataset)

We ship our own multilingual PII evaluation set under
`packages/eval/datasets/nullpii-bench.jsonl`:

- **271 samples**, **680 PII spans**, **5 locales** (en / it / de /
  fr / es), Apache-2.0.
- Three subsets: `bundled` (202 dev-style prompts — PR reviews,
  deploy logs, RFCs, customer-support tickets), `adversarial` (decoy
  strings that look like PII but aren't), `long-prompts` (62 ~3k-char
  prompts with PII positioned past the 512-token mark — chunking
  stress test).
- Schema: `{ id, locale, subset, text, spans }` per row. See
  [`packages/eval/datasets/README.md`](packages/eval/datasets/README.md)
  for full description.

Used as the bundled and long-prompts columns in every comparison
table above. Anyone can run other PII tools against the same set
to reproduce or extend the eval — patches welcome.

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
- `destroySession()` purges the mapping; the Claude Code plugin also
  auto-destroys sessions at the end of each prompt round-trip.
- No `console.log` of PII; debug logs only carry counts and short ids.
- See [SECURITY.md](SECURITY.md) for the full threat model and how to
  report a vulnerability.

---

## License

Apache 2.0 — see [LICENSE](LICENSE), [NOTICE](NOTICE),
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

The full runtime tree is **100% permissive** (MIT / Apache-2.0 / BSD /
ISC / CC0). Verified by `npm run license-check` in CI.
