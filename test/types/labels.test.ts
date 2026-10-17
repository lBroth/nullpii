import { describe, expect, it } from 'vitest';
import {
  GLINER_EXTENDED_CATEGORIES,
  GLINER_MODEL_CATEGORIES,
  GLINER_ZERO_SHOT_EXTRA,
  PII_LABELS,
} from '../../src/types/labels.js';

describe('PII_LABELS', () => {
  it('contains exactly 20 labels (19 PII + O)', () => {
    expect(PII_LABELS).toHaveLength(20);
  });

  it('starts with O and contains every PII category', () => {
    expect(PII_LABELS[0]).toBe('O');
    expect(PII_LABELS).toEqual([
      'O',
      'account_number',
      'private_address',
      'private_date',
      'private_demographic',
      'private_driver_license',
      'private_email',
      'private_geolocation',
      'private_ip',
      'private_mac',
      'private_occupation',
      'private_organization',
      'private_passport',
      'private_person',
      'private_phone',
      'private_sensitive',
      'private_title',
      'private_url',
      'private_vehicle_id',
      'secret',
    ]);
  });

  it('is frozen as a tuple (readonly)', () => {
    const tuple: readonly string[] = PII_LABELS;
    expect(Array.isArray(tuple)).toBe(true);
  });
});

describe('GLINER_MODEL_CATEGORIES', () => {
  it('is the 8-class subset the GLiNER was trained on', () => {
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

  it('excludes labels not in the trained set (zero-shot + recognizer-only)', () => {
    const set: readonly string[] = GLINER_MODEL_CATEGORIES;
    for (const notTrained of ['O', 'private_ip', 'private_mac', ...GLINER_ZERO_SHOT_EXTRA]) {
      expect(set).not.toContain(notTrained);
    }
  });
});

describe('GLINER_ZERO_SHOT_EXTRA', () => {
  it('lists the 4 inference-time zero-shot labels', () => {
    expect(GLINER_ZERO_SHOT_EXTRA).toEqual([
      'private_passport',
      'private_driver_license',
      'private_vehicle_id',
      'private_geolocation',
    ]);
  });

  it('is disjoint from the trained set', () => {
    const trained: readonly string[] = GLINER_MODEL_CATEGORIES;
    for (const z of GLINER_ZERO_SHOT_EXTRA) expect(trained).not.toContain(z);
  });
});

describe('GLINER_EXTENDED_CATEGORIES', () => {
  it('lists the 5 quasi-identifier and special-category labels', () => {
    expect(GLINER_EXTENDED_CATEGORIES).toEqual([
      'private_organization',
      'private_occupation',
      'private_demographic',
      'private_sensitive',
      'private_title',
    ]);
  });

  it('is disjoint from the trained and zero-shot sets', () => {
    const prompted: readonly string[] = [...GLINER_MODEL_CATEGORIES, ...GLINER_ZERO_SHOT_EXTRA];
    for (const e of GLINER_EXTENDED_CATEGORIES) expect(prompted).not.toContain(e);
  });

  it('is part of PII_LABELS', () => {
    const all: readonly string[] = PII_LABELS;
    for (const e of GLINER_EXTENDED_CATEGORIES) expect(all).toContain(e);
  });
});
