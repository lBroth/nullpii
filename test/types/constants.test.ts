import { describe, expect, it } from 'vitest';
import {
  MAX_SEQUENCE_LENGTH,
  MODEL_DOWNLOAD_TIMEOUT_MS,
  PLACEHOLDER_REGEX,
  PLACEHOLDER_TEMPLATE,
  SESSION_PREFIX_LEN,
} from '../../src/types/constants.js';

// F-15: 16 hex chars = 64 bits of session entropy. Collision-free up to
// ~2^32 sessions (vs ~2^16 birthday with the prior 8-char / 32-bit prefix).
const SESSION = 'abcd1234deadbeef';

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
    expect(PLACEHOLDER_TEMPLATE('private_email', 0, SESSION)).toBe(
      `{{PII_PRIVATE_EMAIL_0_${SESSION}}}`,
    );
  });

  it('uses the literal index for large numbers', () => {
    expect(PLACEHOLDER_TEMPLATE('secret', 9999, SESSION)).toBe(`{{PII_SECRET_9999_${SESSION}}}`);
  });

  it('round-trips through PLACEHOLDER_REGEX', () => {
    const placeholder = PLACEHOLDER_TEMPLATE('private_person', 3, SESSION);
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    const match = re.exec(placeholder);
    expect(match).not.toBeNull();
    expect(match?.[1]).toBe('PRIVATE_PERSON');
    expect(match?.[2]).toBe('3');
    expect(match?.[3]).toBe(SESSION);
  });
});

describe('PLACEHOLDER_REGEX', () => {
  it('finds every placeholder in mixed text', () => {
    const text = `Hi {{PII_PRIVATE_PERSON_0_${SESSION}}}, your card {{PII_ACCOUNT_NUMBER_1_${SESSION}}} was charged.`;
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    const matches = [...text.matchAll(re)];
    expect(matches).toHaveLength(2);
    expect(matches[0]?.[1]).toBe('PRIVATE_PERSON');
    expect(matches[0]?.[3]).toBe(SESSION);
    expect(matches[1]?.[1]).toBe('ACCOUNT_NUMBER');
  });

  it('does not match malformed placeholders', () => {
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    expect(re.test(`{PII_FOO_0_${SESSION}}`)).toBe(false);
    expect(re.test(`{{PII__0_${SESSION}}}`)).toBe(false);
    expect(re.test(`{{PII_FOO_abc_${SESSION}}}`)).toBe(false);
    expect(re.test('{{PII_FOO_0}}')).toBe(false); // missing session prefix
    expect(re.test('[[NULLPII:foo:0]]')).toBe(false);
    // Old 8-hex prefix no longer matches the bumped 16-hex format.
    expect(re.test('{{PII_FOO_0_abcd1234}}')).toBe(false);
  });

  it('SESSION_PREFIX_LEN is 16 (64-bit entropy, F-15)', () => {
    expect(SESSION_PREFIX_LEN).toBe(16);
  });
});
