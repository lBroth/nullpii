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

  it('high-confidence recognizers (≥0.9) emit even when overlapping ML output', () => {
    // ML mislabels (e.g., narrative adapter classifies an AWS key as
    // `account_number`); the regex's `secret` label at 0.99 must still
    // be emitted so cross-label dedupe in `nullpii.ts` can pick the
    // correct label.
    const text = 'AKIAIOSFODNN7EXAMPLE';
    const existing: PiiSpan[] = [
      { label: 'account_number', start: 0, end: 20, score: 0.6, text: 'AKIAIOSFODNN7EXAMPLE' },
    ];
    const spans = runRecognizers(text, [awsKey], existing);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('secret');
  });

  it('low-confidence recognizers still defer to ML on overlap', () => {
    const text = 'foo bar baz';
    const lowConf: Recognizer = {
      id: 'noise',
      pattern: /bar/g,
      label: 'private_person',
      confidence: 0.5,
    };
    const existing: PiiSpan[] = [
      { label: 'private_person', start: 4, end: 7, score: 0.8, text: 'bar' },
    ];
    expect(runRecognizers(text, [lowConf], existing)).toHaveLength(0);
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

  // F-39 regression. A recognizer with a `validate` fn whose candidate
  // passes the validator is structurally-correct evidence — much
  // stronger than an ML classifier's guess. The emitted score is bumped
  // above plausible ML softmax (~0.99998 for the GLiNER) so
  // cross-label IoU dedupe in nullpii.ts picks the recognizer's label,
  // not an ML mislabel (e.g. spaced IBAN tagged `private_address`).
  it('boosts emitted score above ML softmax for validator-passing matches', () => {
    const validatedReco: Recognizer = {
      id: 'validated',
      pattern: /\b1234\b/g,
      label: 'account_number',
      confidence: 0.95,
      validate: () => true,
    };
    const spans = runRecognizers('seq 1234 end', [validatedReco], []);
    expect(spans).toHaveLength(1);
    const s = spans[0];
    expect(s?.score).toBeGreaterThan(0.9999);
    expect(s?.score).toBeGreaterThan(validatedReco.confidence);
  });

  it('leaves emitted score at recognizer.confidence when no validator set', () => {
    const unvalidatedReco: Recognizer = {
      id: 'plain',
      pattern: /\b1234\b/g,
      label: 'account_number',
      confidence: 0.95,
    };
    const spans = runRecognizers('seq 1234 end', [unvalidatedReco], []);
    expect(spans[0]?.score).toBe(0.95);
  });

  // F-19 regression. The fast-path indexOf-based prefix scan must
  // produce the EXACT same span set as the legacy regex-only path for
  // the canonical recognizer pack across a representative corpus.
  it('fast-path and slow-path produce identical spans across DEFAULT_RECOGNIZERS', async () => {
    const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
    // Curated corpus exercising both anchored prefixes and structural
    // patterns; mix in negatives + noise to flush boundary handling.
    const corpus = [
      'leak: AKIAIOSFODNN7EXAMPLE rotate now',
      'token: ghp_AbCdEfGhIjKlMnOpQrStUvWxYz1234567890',
      `sk-ant-api03-${'a'.repeat(93)}AA in note`,
      'STRIPE=sk_live_aBcDeFgHiJkLmNoPqRsTuVwX trailing',
      'google api AIzaSyA0123456789ABCDEFGHIJklmnoPQRSTUV0',
      'slack xoxb-1234567890-abcdefghijklmn',
      'gitlab glpat-abcdefghij1234567890',
      'npm token npm_abcdefghijklmnopqrstuvwxyz0123456789',
      'huggingface hf_abcdefghijklmnopqrstuvwxyz01234567ZZ',
      'IBAN GB29 NWBK 6016 1331 9268 19 ok',
      'visa 4242 4242 4242 4242 charged',
      'IPv4 8.8.8.8 reachable',
      'private 10.0.0.1 (RFC1918) and 224.0.0.1 (multicast)',
      'email john@acme.io and 12345 67890 noise',
      'no PII here just words and numbers 99999999',
      // boundary stress: prefix appears mid-word (should NOT trigger)
      'mid-word XAKIAIOSFODNN7EXAMPLE',
      // adjacent placeholders
      'AKIAIOSFODNN7EXAMPLE and AKIAIOSFODNN7EXAMPLB rotate',
    ].join('\n\n');

    // Slow-path reference: run each recognizer independently.
    const referenceSpans: PiiSpan[] = [];
    for (const r of DEFAULT_RECOGNIZERS) {
      referenceSpans.push(...runRecognizers(corpus, [r], []));
    }

    // Fast + slow combined (current implementation):
    const actualSpans = runRecognizers(corpus, DEFAULT_RECOGNIZERS, []);

    // Sort by (start, end, label) for stable comparison.
    const sort = (arr: PiiSpan[]) =>
      [...arr].sort(
        (a, b) =>
          a.start - b.start || a.end - b.end || a.label.localeCompare(b.label) || a.score - b.score,
      );
    expect(sort(actualSpans)).toEqual(sort(referenceSpans));
  });

  // F-28 regression. MAC addresses used to ride on the `private_ip` label
  // even though they identify hardware, not network endpoints. The
  // dedicated `private_mac` label keeps grouping accurate for consumers
  // that bucket spans by label.
  it('emits the core:mac recognizer span with the private_mac label', async () => {
    const { DEFAULT_RECOGNIZERS } = await import('../src/defaults.js');
    const mac = DEFAULT_RECOGNIZERS.find((r) => r.id === 'core:mac');
    expect(mac).toBeDefined();
    expect(mac?.label).toBe('private_mac');
    const spans = runRecognizers('mac 01:23:45:67:89:ab end', mac ? [mac] : [], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('private_mac');
  });
});
