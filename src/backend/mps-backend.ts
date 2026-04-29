import { DEFAULT_VARIANT } from '../defaults.js';
import type { ModelVariant } from '../types/index.js';
import { type BackendConfig, OrtBackend, type SessionThreads } from './ort-backend.js';

/**
 * MPS (Apple Silicon) backend backed by `onnxruntime-node` with the
 * `CoreMLExecutionProvider`. Falls back to CPU within ORT if CoreML cannot
 * service a node. macOS-only.
 */
const MPS_CONFIG: BackendConfig = {
  name: 'mps',
  // CoreML first, CPU as fallback within the same session
  executionProviders: [{ name: 'coreml' }, 'cpu'],
  // Default to int4 (~875 MB, ~6% F1 vs fp32). Pin fp32 for accuracy.
  autoVariant: 'int4',
};

export class MpsBackend extends OrtBackend {
  constructor(
    modelDir: string,
    variant: ModelVariant = DEFAULT_VARIANT,
    threads: SessionThreads = {},
  ) {
    super(MPS_CONFIG, modelDir, variant, threads);
  }

  isAvailable(): Promise<boolean> {
    if (process.platform !== 'darwin') return Promise.resolve(false);
    if (process.arch !== 'arm64' && process.arch !== 'x64') return Promise.resolve(false);
    return Promise.resolve(true);
  }
}
