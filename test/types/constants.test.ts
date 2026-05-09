import { describe, expect, it } from 'vitest';
import {
  MAX_SEQUENCE_LENGTH,
  MODEL_DOWNLOAD_TIMEOUT_MS,
  PLACEHOLDER_REGEX,
  PLACEHOLDER_TEMPLATE,
} from '../../src/types/constants.js';

describe('numeric constants', () => {
  it('MAX_SEQUENCE_LENGTH is a positive integer', () => {
    expect(Number.isInteger(MAX_SEQUENCE_LENGTH)).toBe(true);
    expect(MAX_SEQUENCE_LENGTH).toBeGreaterThan(0);
  });

  it('MODEL_DOWNLOAD_TIMEOUT_MS is at least one minute', () => {
    expect(MODEL_DOWNLOAD_TIMEOUT_MS).toBeGreaterThanOrEqual(60_000);
  });
});

describe('PLACEHOLDER_TEMPLATE', () => {
  it('builds a Mustache placeholder for a typical span', () => {
    expect(PLACEHOLDER_TEMPLATE('private_email', 0)).toBe('{{PII_PRIVATE_EMAIL_0}}');
  });

  it('uses the literal index for large numbers', () => {
    expect(PLACEHOLDER_TEMPLATE('secret', 9999)).toBe('{{PII_SECRET_9999}}');
  });

  it('round-trips through PLACEHOLDER_REGEX', () => {
    const placeholder = PLACEHOLDER_TEMPLATE('private_person', 3);
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    const match = re.exec(placeholder);
    expect(match).not.toBeNull();
    expect(match?.[1]).toBe('PRIVATE_PERSON');
    expect(match?.[2]).toBe('3');
  });
});

describe('PLACEHOLDER_REGEX', () => {
  it('finds every placeholder in mixed text', () => {
    const text = 'Hi {{PII_PRIVATE_PERSON_0}}, your card {{PII_ACCOUNT_NUMBER_1}} was charged.';
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    const matches = [...text.matchAll(re)];
    expect(matches).toHaveLength(2);
    expect(matches[0]?.[1]).toBe('PRIVATE_PERSON');
    expect(matches[1]?.[1]).toBe('ACCOUNT_NUMBER');
  });

  it('does not match malformed placeholders', () => {
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    expect(re.test('{PII_FOO_0}')).toBe(false);
    expect(re.test('{{PII__0}}')).toBe(false);
    expect(re.test('{{PII_FOO_abc}}')).toBe(false);
    expect(re.test('[[NULLPII:foo:0]]')).toBe(false);
  });
});
