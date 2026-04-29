# How it works

```
text → tokenizer → ONNX model → BIOES decoder → spans → vault → placeholders
                                                              ↓
                                              (LLM call sees placeholders)
                                                              ↓
                                              vault.restore → original text
```

## Tokenizer

`@anush008/tokenizers` (Rust NAPI). Returns `inputIds`,
`attentionMask`, and `offsetMapping` (char offsets per token, needed
for char-level span reconstruction).

## Inference

ONNX Runtime against one of the upstream `openai/privacy-filter`
variants:

| Variant      | Size    | Use case                              |
| ------------ | ------- | ------------------------------------- |
| `model.onnx` | 5.4 GiB | fp32 baseline / regression tests      |
| `model_q4`   | 875 MiB | **default — small footprint, ~6% F1** |

Output: `[1, seqLen, 33]` logits per BIOES label (8 categories × 4
boundary tags + `O`).

## BIOES decoder

The model emits per-token logits; a constrained decoder enforces
valid BIOES transitions (`O→B`, `B→I`, `I→E`, etc.) so spans are
coherent. Span scores are mean softmax over their tokens.

## Vault

`Map<sessionId, Map<placeholder, original>>`. Sanitize replaces
spans back-to-front to preserve offsets. Restore swaps placeholders
back. In-memory only; `destroySession` purges. See
[Security model](/guide/security) for the threat model.
