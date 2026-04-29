// SPDX-License-Identifier: Apache-2.0
import { DEFAULT_VARIANT } from '../defaults.js';
import type { ModelVariant } from '../types/index.js';
import { type BackendConfig, OrtBackend, type SessionThreads } from './ort-backend.js';

const CPU_CONFIG: BackendConfig = {
  name: 'cpu',
  executionProviders: ['cpu'],
  // Default to int4 (~875 MB, ~6% F1 vs fp32). Pin fp32 for accuracy.
  autoVariant: 'int4',
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
