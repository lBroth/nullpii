// SPDX-License-Identifier: Apache-2.0
import { DEFAULT_VARIANT } from '../defaults.js';
import { fileExists } from '../paths.js';
import type { ModelVariant } from '../types/index.js';
import { type BackendConfig, OrtBackend, type SessionThreads } from './ort-backend.js';

const ROCM_KFD_DEVICE = '/dev/kfd';

const ROCM_CONFIG: BackendConfig = {
  name: 'rocm',
  executionProviders: [{ name: 'rocm' }, 'cpu'],
  // ROCm: fp16 leverages MFMA on RDNA3+ / CDNA — same rationale as CUDA.
  autoVariant: 'fp16',
};

/**
 * AMD ROCm backend (Linux-only) backed by `onnxruntime-node`'s
 * `ROCMExecutionProvider`. `isAvailable()` checks for the AMD KFD char
 * device which the ROCm runtime uses to talk to the GPU.
 */
export class RocmBackend extends OrtBackend {
  constructor(
    modelDir: string,
    variant: ModelVariant = DEFAULT_VARIANT,
    threads: SessionThreads = {},
  ) {
    super(ROCM_CONFIG, modelDir, variant, threads);
  }

  async isAvailable(): Promise<boolean> {
    if (process.platform !== 'linux') return false;
    return await fileExists(ROCM_KFD_DEVICE);
  }
}
