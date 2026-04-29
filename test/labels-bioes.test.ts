import { describe, expect, it } from 'vitest';
import {
  LABEL_MAP,
  NUM_LABELS,
  isValidStart,
  isValidTransition,
  parseLabel,
} from '../src/labels-bioes.js';

describe('LABEL_MAP', () => {
  it('starts with O and contains 33 entries (8 categories × BIOES + O)', () => {
    expect(LABEL_MAP[0]).toBe('O');
    expect(NUM_LABELS).toBe(33);
    expect(LABEL_MAP.length).toBe(33);
  });

  it('contains all four BIOES tags for every category', () => {
    const expected = [
      'B-account_number',
      'I-account_number',
      'E-account_number',
      'S-account_number',
      'B-secret',
      'I-secret',
      'E-secret',
      'S-secret',
    ];
    for (const e of expected) {
      expect(LABEL_MAP).toContain(e);
    }
  });
});

describe('parseLabel', () => {
  it('parses O', () => {
    expect(parseLabel('O')).toEqual({ tag: 'O' });
  });

  it('parses tagged labels', () => {
    expect(parseLabel('B-private_email')).toEqual({ tag: 'B', entity: 'private_email' });
    expect(parseLabel('S-secret')).toEqual({ tag: 'S', entity: 'secret' });
  });

  it('throws on malformed input', () => {
    expect(() => parseLabel('X-foo')).toThrow();
    expect(() => parseLabel('-foo')).toThrow();
    expect(() => parseLabel('B-')).toThrow();
  });
});

describe('isValidTransition', () => {
  it('allows O → O / B / S', () => {
    expect(isValidTransition('O', 'O')).toBe(true);
    expect(isValidTransition('O', 'B-secret')).toBe(true);
    expect(isValidTransition('O', 'S-private_email')).toBe(true);
  });

  it('forbids O → I and O → E', () => {
    expect(isValidTransition('O', 'I-secret')).toBe(false);
    expect(isValidTransition('O', 'E-secret')).toBe(false);
  });

  it('B-X → I-X / E-X (same entity), nothing else', () => {
    expect(isValidTransition('B-secret', 'I-secret')).toBe(true);
    expect(isValidTransition('B-secret', 'E-secret')).toBe(true);
    expect(isValidTransition('B-secret', 'I-private_email')).toBe(false);
    expect(isValidTransition('B-secret', 'O')).toBe(false);
    expect(isValidTransition('B-secret', 'S-secret')).toBe(false);
    expect(isValidTransition('B-secret', 'B-secret')).toBe(false);
  });

  it('I-X → I-X / E-X (same entity)', () => {
    expect(isValidTransition('I-secret', 'I-secret')).toBe(true);
    expect(isValidTransition('I-secret', 'E-secret')).toBe(true);
    expect(isValidTransition('I-secret', 'O')).toBe(false);
  });

  it('E-X / S-X → O / B / S (any entity)', () => {
    expect(isValidTransition('E-secret', 'O')).toBe(true);
    expect(isValidTransition('E-secret', 'B-private_email')).toBe(true);
    expect(isValidTransition('E-secret', 'S-private_email')).toBe(true);
    expect(isValidTransition('S-secret', 'O')).toBe(true);
    expect(isValidTransition('S-secret', 'B-private_url')).toBe(true);
  });
});

describe('isValidStart', () => {
  it('accepts only O / B-* / S-*', () => {
    expect(isValidStart('O')).toBe(true);
    expect(isValidStart('B-secret')).toBe(true);
    expect(isValidStart('S-secret')).toBe(true);
    expect(isValidStart('I-secret')).toBe(false);
    expect(isValidStart('E-secret')).toBe(false);
  });
});
