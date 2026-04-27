# Backends

| Backend | Platform              | Default variant | Notes                                              |
| ------- | --------------------- | --------------- | -------------------------------------------------- |
| `cpu`   | All                   | `fp16`          | Universal. F1-equivalent to fp32, ~3× faster.      |
| `mps`   | Apple Silicon         | `fp16`          | CoreML EP; partial op coverage — see BENCHMARK.md. |
| `cuda`  | Linux/Windows + NVIDIA| `fp16`          | Tensor cores on Volta+. CUDA EP via ORT.           |
| `rocm`  | Linux + AMD           | `fp16`          | MFMA on RDNA3+ / CDNA. ROCm EP via ORT.            |

## Auto-selection

`{ backend: 'auto' }` (default) tries backends in this order:

1. `cuda`
2. `mps`
3. `rocm`
4. `cpu`

The first one whose `isAvailable()` resolves `true` wins.

## Variants

| Variant   | Size  | Tolerance vs fp32 | Recommended for                       |
| --------- | ----: | ----------------- | ------------------------------------- |
| `fp32`    | ~5 GB | 0.0% (baseline)   | reference, regression tests           |
| **`fp16`**|~3 GB  | ~0.0%             | **default — best CPU + GPU**          |
| `int8`    |~1.5 GB| ~0.5%             | legacy CPU; superseded by fp16        |
| `int4`    | ~772 MB | ~5.5%           | edge / memory-constrained             |
| `int4f16` | ~772 MB | ~5.5%           | edge with fp16 activations            |
| `auto`    | n/a   | per-backend       | most setups (resolves to fp16 on CPU) |

The validation pipeline (`packages/convert/`) enforces these tolerances
on every fetch with a `consistency` step.

## Optional peer dependency

```bash
npm install nullpii onnxruntime-node
```

`onnxruntime-node` is the only peer needed for the Node-side backends.
Apache-2.0 / MIT permissive — no LGPL/GPL anywhere in the dep tree.

## Hardware probe

| Backend | Probe                                                   |
| ------- | ------------------------------------------------------- |
| `cpu`   | always available                                        |
| `mps`   | `process.platform === 'darwin'`                         |
| `cuda`  | `/dev/nvidia0` (Linux) or `CUDA_PATH` env (Windows)     |
| `rocm`  | `/dev/kfd` (Linux only)                                 |

If you need a different probe (containerized GPUs, custom drivers),
construct the backend directly and call `isAvailable()` yourself.
