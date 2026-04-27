// SPDX-License-Identifier: Apache-2.0
import { DEFAULT_VARIANT } from '../defaults.js';
import type { ModelVariant } from '../types/index.js';
import { type BackendConfig, OrtBackend, type SessionThreads } from './ort-backend.js';

const CPU_CONFIG: BackendConfig = {
  name: 'cpu',
  executionProviders: ['cpu'],
  // fp16 dominates fp32/int8 on CPU ORT for this model: identical F1,
  // ~3× faster than fp32, ~17% faster than int8.
  autoVariant: 'fp16',
};

/** CPU inference backend backed by `onnxruntime-node` (always available). */
export class CpuBackend extends OrtBackend {
  constructor(
    modelDir: string,
    variant: ModelVariant = DEFAULT_VARIANT,
    threads: SessionThreads = {},
  ) {
    super(CPU_CONFIG, modelDir, variant, threads);
  }

  isAvailable(): Promise<boolean> {
    return Promise.resolve(true);
  }
}
