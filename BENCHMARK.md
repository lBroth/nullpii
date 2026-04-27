# Benchmarks

## Methodology

- Hardware matrix: CPU, Apple M-series (MPS), NVIDIA (CUDA), AMD (ROCm)
- Metrics: latency (ms), throughput (tokens/s)
- 3 runs per sequence length after a single warmup
- Source: `npx tsx test/backend/benchmark.ts`

## Results

`int8` (CPU) and `fp16` (MPS) variants of `openai/privacy-filter`.
`onnxruntime-node@1.24`. F1 vs upstream pending.

| Backend | Variant | seq=128 (ms / tok/s) | seq=256 (ms / tok/s) | seq=512 (ms / tok/s) |
| ------- | ------- | -------------------- | -------------------- | -------------------- |
| CPU     | int8    | 24.1 / 5313          | 34.5 / 7427          | 57.3 / 8929          |
| MPS     | fp16    | 44.8 / 2856          | 71.8 / 3566          | 159.0 / 3219         |
| CUDA    | —       | pending              | pending              | pending              |
| ROCm    | —       | pending              | pending              | pending              |

## Notes

**MPS slower than CPU on this model.** ORT's `CoreMLExecutionProvider`
cannot service every op in the custom architecture
(`OpenAIPrivacyFilterForTokenClassification`) and falls back to CPU
mid-graph, costing latency for tensor marshalling. On Apple Silicon with
int8, the CPU path is currently the fastest. Recommend `'cpu'` for
production on macOS today.
