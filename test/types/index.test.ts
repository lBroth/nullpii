// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import * as api from '../../src/types/index.js';

describe('public API surface', () => {
  it('re-exports PII_LABELS, constants, and helpers', () => {
    expect(api.PII_LABELS).toBeDefined();
    expect(api.MAX_SEQUENCE_LENGTH).toBeDefined();
    expect(api.PLACEHOLDER_TEMPLATE('secret', 0)).toContain('NULLPII');
    expect(api.PLACEHOLDER_REGEX).toBeInstanceOf(RegExp);
  });

  it('does not export anything not in the documented surface', () => {
    const allowed = new Set([
      'PII_LABELS',
      'CHUNK_OVERLAP_TOKENS',
      'DEFAULT_MODEL_DIR',
      'MAX_INPUT_TOKENS',
      'MAX_SEQUENCE_LENGTH',
      'MODEL_DOWNLOAD_TIMEOUT_MS',
      'PLACEHOLDER_REGEX',
      'PLACEHOLDER_TEMPLATE',
    ]);
    for (const name of Object.keys(api)) {
      expect(allowed.has(name)).toBe(true);
    }
  });
});
