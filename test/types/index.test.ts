import { describe, expect, it } from 'vitest';
import * as api from '../../src/types/index.js';

describe('public API surface', () => {
  it('re-exports PII_LABELS, constants, and helpers', () => {
    expect(api.PII_LABELS).toBeDefined();
    expect(api.MAX_SEQUENCE_LENGTH).toBeDefined();
    expect(api.SESSION_PREFIX_LEN).toBeDefined();
    expect(api.PLACEHOLDER_TEMPLATE('secret', 0, 'abcd1234')).toBe('{{PII_SECRET_0_abcd1234}}');
    expect(api.PLACEHOLDER_REGEX).toBeInstanceOf(RegExp);
  });

  it('does not export anything not in the documented surface', () => {
    const allowed = new Set([
      'PII_LABELS',
      'GLINER_MODEL_CATEGORIES',
      'GLINER_ZERO_SHOT_EXTRA',
      'CHUNK_OVERLAP_TOKENS',
      'MAX_INPUT_TOKENS',
      'MAX_SEQUENCE_LENGTH',
      'MODEL_DOWNLOAD_TIMEOUT_MS',
      'PLACEHOLDER_REGEX',
      'PLACEHOLDER_TEMPLATE',
      'SESSION_PREFIX_LEN',
    ]);
    for (const name of Object.keys(api)) {
      expect(allowed.has(name)).toBe(true);
    }
  });
});
