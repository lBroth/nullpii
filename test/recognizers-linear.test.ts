// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { DEFAULT_RECOGNIZERS, MAX_INPUT_CHARS } from '../src/defaults.js';
import { runRecognizers } from '../src/recognizers.js';

/** Repeated units that made unbounded quantifiers backtrack: separator
 * runs after a context keyword, local-part characters before an `@`,
 * and repeated PEM headers without an END line. */
const ADVERSARIAL_UNITS = [' ', '.', '-', 'a.', 'a-', '%2', '1-', '1 ', 'a ', '1.1.'];
const SIZE = 100_000;
/** A quadratic pattern takes seconds at this size (certificate-context
 * took over 20 s at 10k characters); every linear one takes a few ms. */
const BUDGET_MS = 250;

function timeMatch(pattern: RegExp, text: string): number {
  const re = new RegExp(
    pattern.source,
    pattern.flags.includes('g') ? pattern.flags : `${pattern.flags}g`,
  );
  const t0 = performance.now();
  text.match(re);
  return performance.now() - t0;
}

describe('recognizer patterns run in linear time', () => {
  for (const unit of ADVERSARIAL_UNITS) {
    it(`every default recognizer on ${SIZE} characters of ${JSON.stringify(unit)}`, () => {
      const text = unit.repeat(Math.ceil(SIZE / unit.length)).slice(0, SIZE);
      const slow = DEFAULT_RECOGNIZERS.map((r) => ({
        id: r.id,
        ms: timeMatch(r.pattern, text),
      })).filter((r) => r.ms > BUDGET_MS);
      expect(slow).toEqual([]);
    });
  }

  // At MAX_INPUT_CHARS, where a quadratic scan from each header takes
  // seconds; 100k characters took only ~20 ms even then. Headers are
  // built from parts so the source holds no PEM marker for the secret
  // scanner to flag.
  const begin = (label: string): string => `${'-'.repeat(5)}BEGIN ${label}${'-'.repeat(5)}`;
  for (const header of [
    `${begin('RSA PRIVATE KEY')}\n`,
    `${begin('PRIVATE KEY')}\n`,
    begin('PRIVATE KEY'),
    `${begin('PRIVATE KEY')}\n${'Q'.repeat(64)}\n`,
    `${begin('PGP PRIVATE KEY BLOCK')}\n`,
  ]) {
    it(`the PEM pattern on ${MAX_INPUT_CHARS} characters of ${JSON.stringify(header)}, no END line`, () => {
      const text = header
        .repeat(Math.ceil(MAX_INPUT_CHARS / header.length))
        .slice(0, MAX_INPUT_CHARS);
      const pem = DEFAULT_RECOGNIZERS.find((r) => r.id === 'core:pem-private-key');
      expect(pem).toBeDefined();
      if (pem) expect(timeMatch(pem.pattern, text)).toBeLessThan(BUDGET_MS);
    });
  }
});

describe('runRecognizers', () => {
  it('scans text longer than the sanitize() input cap (normalised text can grow)', () => {
    const text = `${'word '.repeat(220_000)}contact john.doe@acme-mail.io`;
    expect(text.length).toBeGreaterThan(1_000_000);
    const spans = runRecognizers(text, DEFAULT_RECOGNIZERS, []);
    expect(
      spans.some((s) => s.label === 'private_email' && s.text === 'john.doe@acme-mail.io'),
    ).toBe(true);
  });

  // Reserved documentation domains (example.com, RFC 6761) are never PII,
  // so the fixtures use other hosts.
  it('still matches valid emails after bounding the local and domain parts', () => {
    const text = 'Write to first_last-99%tag@mail-server.acme.io or a+b@sub.domain.co.uk.';
    const emails = runRecognizers(text, DEFAULT_RECOGNIZERS, [])
      .filter((s) => s.label === 'private_email')
      .map((s) => s.text);
    expect(emails).toEqual(['first_last-99%tag@mail-server.acme.io', 'a+b@sub.domain.co.uk']);
  });
});
