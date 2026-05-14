import { describe, expect, it } from 'vitest';
import { CREDIT_CARD, IBAN, iban97, luhn } from '../../packages/recognizers-finance/src/index.js';
import { runRecognizers } from '../../src/recognizers.js';

describe('@nullpii/recognizers-finance — luhn', () => {
  it('accepts known test PANs', () => {
    expect(luhn('4242424242424242')).toBe(true); // Stripe Visa test
    expect(luhn('5555555555554444')).toBe(true); // Stripe MC test
    expect(luhn('4111111111111111')).toBe(true);
  });
  it('rejects sequential garbage', () => {
    expect(luhn('1234567812345678')).toBe(false);
    expect(luhn('1111111111111111')).toBe(false);
  });
});

describe('@nullpii/recognizers-finance — iban97', () => {
  it('accepts known valid IBANs', () => {
    expect(iban97('GB29 NWBK 6016 1331 9268 19')).toBe(true);
    expect(iban97('DE89 3704 0044 0532 0130 00')).toBe(true);
  });
  it('rejects fail-checksum IBAN', () => {
    expect(iban97('GB29 NWBK 6016 1331 9268 18')).toBe(false);
  });
});

describe('CREDIT_CARD recognizer', () => {
  it('emits a span only on Luhn-valid 16-digit strings', () => {
    const text = 'card 4242424242424242 ok; card 1234567812345678 not';
    const spans = runRecognizers(text, [CREDIT_CARD], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.text).toBe('4242424242424242');
  });
});

describe('IBAN recognizer', () => {
  it('emits a span on valid IBAN', () => {
    const text = 'wire to GB29 NWBK 6016 1331 9268 19 today';
    const spans = runRecognizers(text, [IBAN], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('account_number');
  });
});
