import { describe, expect, it } from 'vitest';
import { VARIANT_TO_FILE, resolveVariantFile } from '../../src/backend/variant.js';

describe('VARIANT_TO_FILE', () => {
  it('covers every concrete ModelVariant', () => {
    const expected = ['fp32', 'int4'] as const;
    for (const k of expected) {
      expect(VARIANT_TO_FILE).toHaveProperty(k);
      expect(VARIANT_TO_FILE[k]).toMatch(/\.onnx$/);
    }
  });
});

describe('resolveVariantFile', () => {
  it('maps explicit variants to their file', () => {
    expect(resolveVariantFile('fp32', 'int4')).toBe('model.onnx');
    expect(resolveVariantFile('int4', 'fp32')).toBe('model_q4.onnx');
  });

  it('maps auto to the supplied autoVariant (per-backend policy)', () => {
    expect(resolveVariantFile('auto', 'fp32')).toBe('model.onnx');
    expect(resolveVariantFile('auto', 'int4')).toBe('model_q4.onnx');
  });
});
