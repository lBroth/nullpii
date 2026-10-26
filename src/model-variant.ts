// SPDX-License-Identifier: Apache-2.0

import { MODEL_FILES } from './defaults.js';
import type { BackendName, ModelVariant } from './types/index.js';

/**
 * The ONNX files to try for `variant` on `backend`, best first.
 *
 * fp16 is for the CUDA execution provider. There it runs about 15% faster
 * than fp32 with no measured recall loss; ORT's CPU and CoreML kernels gain
 * nothing from it. So `'auto'` asks for fp16 only on CUDA, and falls back to
 * fp32 when a model directory or revision does not ship it. An explicit
 * `'fp16'` has no fallback: a missing file is an error.
 */
export function onnxCandidates(variant: ModelVariant, backend: BackendName): readonly string[] {
  switch (variant) {
    case 'fp32':
      return [MODEL_FILES.fp32];
    case 'fp16':
      return [MODEL_FILES.fp16];
    case 'auto':
      return backend === 'cuda' ? [MODEL_FILES.fp16, MODEL_FILES.fp32] : [MODEL_FILES.fp32];
    default:
      throw new TypeError(`unknown model variant: ${String(variant)}`);
  }
}
