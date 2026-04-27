// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { PII_LABELS } from '../../src/types/labels.js';

describe('PII_LABELS', () => {
  it('contains exactly 9 labels (8 PII + O)', () => {
    expect(PII_LABELS).toHaveLength(9);
  });

  it('starts with O and contains the eight upstream categories', () => {
    expect(PII_LABELS[0]).toBe('O');
    expect(PII_LABELS).toEqual([
      'O',
      'account_number',
      'private_address',
      'private_date',
      'private_email',
      'private_person',
      'private_phone',
      'private_url',
      'secret',
    ]);
  });

  it('is frozen as a tuple (readonly)', () => {
    const tuple: readonly string[] = PII_LABELS;
    expect(Array.isArray(tuple)).toBe(true);
  });
});
