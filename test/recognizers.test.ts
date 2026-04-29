import { describe, expect, it } from 'vitest';
import { runRecognizers } from '../src/recognizers.js';
import type { PiiSpan, Recognizer } from '../src/types/index.js';

const awsKey: Recognizer = {
  id: 'aws-access-key',
  pattern: /\bAKIA[0-9A-Z]{16}\b/g,
  label: 'secret',
  confidence: 0.99,
};

const luhnCard: Recognizer = {
  id: 'credit-card',
  pattern: /\b\d{16}\b/g,
  label: 'account_number',
  confidence: 0.95,
  validate: (m) => luhn(m),
};

function luhn(num: string): boolean {
  let sum = 0;
  let alt = false;
  for (let i = num.length - 1; i >= 0; i--) {
    let n = Number(num[i]);
    if (alt) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
    alt = !alt;
  }
  return sum % 10 === 0;
}

describe('runRecognizers', () => {
  it('finds matches and tags them with the recognizer label', () => {
    const text = 'leak: AKIAIOSFODNN7EXAMPLE rotate now';
    const spans = runRecognizers(text, [awsKey], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('secret');
    expect(spans[0]?.text).toBe('AKIAIOSFODNN7EXAMPLE');
  });

  it('skips matches that overlap an existing higher-confidence span', () => {
    const text = 'AKIAIOSFODNN7EXAMPLE';
    const existing: PiiSpan[] = [
      { label: 'secret', start: 0, end: 20, score: 1.0, text: 'AKIAIOSFODNN7EXAMPLE' },
    ];
    expect(runRecognizers(text, [awsKey], existing)).toHaveLength(0);
  });

  it('honours validate() — Luhn rejects an invalid 16-digit string', () => {
    const text = 'card 1234567812345678 charged';
    expect(luhn('1234567812345678')).toBe(false);
    expect(runRecognizers(text, [luhnCard], [])).toHaveLength(0);
  });

  it('honours validate() — Luhn accepts a valid 16-digit string', () => {
    const text = 'card 4242424242424242 charged';
    expect(luhn('4242424242424242')).toBe(true);
    const spans = runRecognizers(text, [luhnCard], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('account_number');
  });

  it('finds multiple non-overlapping matches in one pass', () => {
    const text = 'AKIAIOSFODNN7EXAMPLE and AKIAIOSFODNN7EXAMPLB rotate';
    const spans = runRecognizers(text, [awsKey], []);
    expect(spans).toHaveLength(2);
  });

  it('auto-adds the global flag if missing', () => {
    const reco: Recognizer = { id: 'x', pattern: /foo/, label: 'secret', confidence: 0.5 };
    const spans = runRecognizers('foo foo foo', [reco], []);
    expect(spans).toHaveLength(3);
  });
});
