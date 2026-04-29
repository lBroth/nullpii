# Backends

| Backend | Platform              | Default variant | Notes                                              |
| ------- | --------------------- | --------------- | -------------------------------------------------- |
| `cpu`   | All                   | `int4`          | Universal. F1-equivalent to fp32, ~3× faster.      |
| `mps`   | Apple Silicon         | `int4`          | CoreML EP; partial op coverage — see [Eval results / Backend latency](/guide/eval-results). |
| `cuda`  | Linux/Windows + NVIDIA| `int4`          | Tensor cores on Volta+. CUDA EP via ORT.           |

## Auto-selection

`{ backend: 'auto' }` (default) tries backends in this order:

1. `cuda`
2. `mps`
3. `cpu`

The first one whose `isAvailable()` resolves `true` wins.

## Variants

| Variant | Size    | Tolerance vs fp32 | Recommended for                       |
| ------- | ------: | ----------------: | ------------------------------------- |
| `fp32`  | ~5 GB   | 0.0% (baseline)   | reference / max accuracy              |
| **`int4`** | ~875 MB | ~6%               | **default — small footprint**         |
| `auto`  | n/a     | per-backend       | resolves to `int4`                    |

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

If you need a different probe (containerized GPUs, custom drivers),
construct the backend directly and call `isAvailable()` yourself.
