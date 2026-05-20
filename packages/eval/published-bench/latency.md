# Public-runtime latency

M5 Pro CPU · Node v24.14.1 · 2026-05-20

Cold start (first `sanitize()` incl. ONNX load + warmup): **755.9 ms**

| Input size (chars) | n | p50 ms | p95 ms | p99 ms | mean ms |
|---:|---:|---:|---:|---:|---:|
| 100 | 50 | 23.1 | 24.5 | 26.5 | 23 |
| 1,000 | 50 | 94.6 | 113.3 | 114.2 | 95.9 |
| 10,000 | 50 | 937.7 | 971.9 | 1122 | 940.3 |

Measured with `NullPii({ backend: "cpu" })` against the
published `lBroth/nullpii` ONNX. Per-sample input is a
reproducible mix of PII + neutral filler padded to the target
size; first 5 calls per size are discarded as warmup.
