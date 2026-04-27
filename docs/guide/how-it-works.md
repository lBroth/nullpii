# How it works

```
Input text
   │
   ▼
Tokenizer (offsets)──┐
   │                 │
   ▼                 │
ONNX Runtime         │
   │                 │
   ▼                 │
Constrained Viterbi──┘
   │
   ▼
Span decoder ── PiiSpan[] ─→ Vault.sanitize ── (sanitized, sessionId)
                                                     │
                                                     ▼
                                       (LLM call with sanitized text)
                                                     │
                                                     ▼
                                           Vault.restore(sessionId)
```

## Tokenizer

The upstream `tokenizer.json` is loaded directly via
[`@anush008/tokenizers`](https://www.npmjs.com/package/@anush008/tokenizers)
(NAPI bindings to the Rust `tokenizers` crate). We bypass the
`AutoTokenizer` factory because the upstream `tokenizer_config.json`
references a custom `TokenizersBackend` class that the `transformers` JS
port does not know about.

The encoder emits three aligned arrays:

- `inputIds: BigInt64Array` — the model's input.
- `attentionMask: BigInt64Array` — all 1s for non-padded inputs.
- `offsetMapping: Array<[number, number]>` — `[startChar, endChar]` per
  token, in the **original** text. Critical for span reconstruction.

## Inference

The selected `BackendProvider` runs ONNX Runtime against one of the five
ONNX variants in the upstream repo:

| Variant       | Bytes (approx.) | Use case                          |
| ------------- | --------------- | --------------------------------- |
| `model.onnx`              | 5.4 GiB | full precision baseline            |
| `model_fp16.onnx`         | 2.6 GiB | accelerated GPU/Neural Engine      |
| `model_quantized.onnx`    | 1.5 GiB | int8 dynamic, CPU-friendly          |
| `model_q4.onnx`           | 875 MiB | int4, edge devices                 |
| `model_q4f16.onnx`        | 772 MiB | int4 + fp16, browser memory budget |

Output: a `[1, seqLen, 33]` tensor of logits per BIOES label.

## Constrained Viterbi

The model can in principle emit any label per token — including invalid
sequences like `O → I-X` or `B-X → S-Y`. A naive argmax gives wrong
spans whenever the transition is illegal.

We run a constrained Viterbi pass with the BIOES transition rules:

- `O / E-* / S-*` → `O / B-* / S-*`
- `B-X / I-X` → `I-X / E-X` (same entity)

Invalid transitions get score `-Infinity`; the forward-backward pass
finds the globally optimal sequence under the constraint, and a
backtrack reconstructs the per-token labels.

## Span decoder

Coalesce contiguous label runs into character-level `PiiSpan` objects
using the `offsetMapping` from the tokenizer. Each span's score is the
mean softmax score of its constituent tokens.

## Vault

In-memory `Map<sessionId, Map<placeholder, original>>`. Sanitize:

1. Allocate placeholders **in document order** so indices are predictable.
2. Replace **back-to-front** so each replacement preserves earlier offsets.
3. Store `placeholder → original` in the session map.

Restore: `text.replaceAll(PLACEHOLDER_REGEX, ...)` looks up each
match in the session map. Unknown placeholders are passed through
untouched (defensive — never throw on the restore path).

`destroySession` deletes the underlying Map; subsequent calls throw
`SessionNotFoundError`.
