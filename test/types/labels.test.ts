import { describe, expect, it } from 'vitest';
import { GLINER_MODEL_CATEGORIES, PII_LABELS } from '../../src/types/labels.js';

describe('PII_LABELS', () => {
  it('contains exactly 11 labels (10 PII + O)', () => {
    expect(PII_LABELS).toHaveLength(11);
  });

  it('starts with O and contains all PII categories including private_mac', () => {
    expect(PII_LABELS[0]).toBe('O');
    expect(PII_LABELS).toEqual([
      'O',
      'account_number',
      'private_address',
      'private_date',
      'private_email',
      'private_ip',
      'private_mac',
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

describe('GLINER_MODEL_CATEGORIES', () => {
  it('is the 8-class subset the unified GLiNER was trained on', () => {
    expect(GLINER_MODEL_CATEGORIES).toEqual([
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

  it('excludes O, private_ip, and private_mac (post-pass recognizer-only labels)', () => {
    const set: readonly string[] = GLINER_MODEL_CATEGORIES;
    expect(set).not.toContain('O');
    expect(set).not.toContain('private_ip');
    expect(set).not.toContain('private_mac');
  });
});
