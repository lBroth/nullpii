// SPDX-License-Identifier: Apache-2.0
import type { ModelVariant } from '../types/index.js';

/** Map a `ModelVariant` to the ONNX filename within `<modelDir>/onnx/`. */
export const VARIANT_TO_FILE: Readonly<Record<Exclude<ModelVariant, 'auto'>, string>> = {
  fp32: 'model.onnx',
  fp16: 'model_fp16.onnx',
  int8: 'model_quantized.onnx',
  int4: 'model_q4.onnx',
  int4f16: 'model_q4f16.onnx',
};

/**
 * Resolve a `ModelVariant` (including `'auto'`) to its concrete file.
 * Each backend supplies its own `autoVariant` (CPU prefers fp32, MPS prefers
 * fp16, etc.); this keeps the resolver pure and testable.
 */
export function resolveVariantFile(
  variant: ModelVariant,
  autoVariant: Exclude<ModelVariant, 'auto'>,
): string {
  const concrete = variant === 'auto' ? autoVariant : variant;
  return VARIANT_TO_FILE[concrete];
}
