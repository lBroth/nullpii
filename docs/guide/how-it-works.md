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

| Variant         | Size    | Use case                               |
| --------------- | ------- | -------------------------------------- |
| `model_fp16`    | 2.6 GiB | **default — best CPU + GPU/ANE**       |
| `model_q4f16`   | 772 MiB | edge / browser, ~6% F1 drop            |
| `model_quant`   | 1.5 GiB | int8 dynamic, legacy CPU               |

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
