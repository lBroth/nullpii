import { hasCudaPath } from '../config.js';
import { DEFAULT_VARIANT } from '../defaults.js';
import { fileExists } from '../paths.js';
import type { ModelVariant } from '../types/index.js';
import { type BackendConfig, OrtBackend, type SessionThreads } from './ort-backend.js';

const CUDA_CONFIG: BackendConfig = {
  name: 'cuda',
  executionProviders: [{ name: 'cuda' }, 'cpu'],
  // Default to int4 (~875 MB, ~6% F1 vs fp32). Pin fp32 for accuracy.
  autoVariant: 'int4',
};

const LINUX_HINTS = ['/dev/nvidia0', '/proc/driver/nvidia/version'] as const;

/**
 * NVIDIA CUDA backend backed by `onnxruntime-node`'s `CUDAExecutionProvider`.
 *
 * The standard `onnxruntime-node` package ships with the CUDA EP on Linux
 * and Windows. It loads `libcudart` (or `cudart64_*.dll`) at runtime;
 * `isAvailable()` probes the well-known driver entry points before
 * promising the backend can run.
 */
export class CudaBackend extends OrtBackend {
  constructor(
    modelDir: string,
    variant: ModelVariant = DEFAULT_VARIANT,
    threads: SessionThreads = {},
  ) {
    super(CUDA_CONFIG, modelDir, variant, threads);
  }

  async isAvailable(): Promise<boolean> {
    if (process.platform === 'darwin') return false;
    return await hasCudaDriver();
  }
}

async function hasCudaDriver(): Promise<boolean> {
  if (process.platform === 'win32') return hasCudaPath();
  for (const hint of LINUX_HINTS) {
    if (await fileExists(hint)) return true;
  }
  return false;
}
