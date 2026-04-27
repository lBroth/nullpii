// SPDX-License-Identifier: Apache-2.0
import { DEFAULT_VARIANT } from '../defaults.js';
import type { ModelVariant } from '../types/index.js';
import { type BackendConfig, OrtBackend } from './ort-backend.js';

const CPU_CONFIG: BackendConfig = {
  name: 'cpu',
  executionProviders: ['cpu'],
  autoVariant: 'fp32',
};

/** CPU inference backend backed by `onnxruntime-node` (always available). */
export class CpuBackend extends OrtBackend {
  constructor(modelDir: string, variant: ModelVariant = DEFAULT_VARIANT) {
    super(CPU_CONFIG, modelDir, variant);
  }

  isAvailable(): Promise<boolean> {
    return Promise.resolve(true);
  }
}
