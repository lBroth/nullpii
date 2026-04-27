// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { VARIANT_TO_FILE, resolveVariantFile } from '../../src/backend/variant.js';

describe('VARIANT_TO_FILE', () => {
  it('covers every concrete ModelVariant', () => {
    const expected = ['fp32', 'fp16', 'int8', 'int4', 'int4f16'];
    for (const k of expected) {
      expect(VARIANT_TO_FILE).toHaveProperty(k);
      expect(VARIANT_TO_FILE[k as keyof typeof VARIANT_TO_FILE]).toMatch(/\.onnx$/);
    }
  });
});

describe('resolveVariantFile', () => {
  it('maps explicit variants to their file', () => {
    expect(resolveVariantFile('int8', 'fp32')).toBe('model_quantized.onnx');
    expect(resolveVariantFile('fp16', 'fp32')).toBe('model_fp16.onnx');
  });

  it('maps auto to the supplied autoVariant (per-backend policy)', () => {
    expect(resolveVariantFile('auto', 'fp32')).toBe('model.onnx');
    expect(resolveVariantFile('auto', 'fp16')).toBe('model_fp16.onnx');
    expect(resolveVariantFile('auto', 'int8')).toBe('model_quantized.onnx');
  });
});
