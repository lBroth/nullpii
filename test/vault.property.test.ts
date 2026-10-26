// SPDX-License-Identifier: Apache-2.0

import * as fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import type { PiiCategory, PiiSpan } from '../src/types/index.js';
import { PiiVault } from '../src/vault.js';

const CATEGORIES: readonly PiiCategory[] = [
  'account_number',
  'private_address',
  'private_date',
  'private_email',
  'private_person',
  'private_phone',
  'private_url',
  'secret',
];

/** Generate non-overlapping spans inside `text`. */
function spansArbitrary(text: string): fc.Arbitrary<PiiSpan[]> {
  if (text.length === 0) return fc.constant([]);
  return fc
    .array(
      fc.tuple(
        fc.integer({ min: 0, max: Math.max(0, text.length - 1) }),
        fc.integer({ min: 1, max: 6 }),
        fc.constantFrom(...CATEGORIES),
        fc.float({ min: 0, max: 1, noNaN: true }),
      ),
      { maxLength: 8 },
    )
    .map((tuples) => {
      const sorted = tuples
        .map(([s, l, label, score]) => ({ s, l, label, score }))
        .sort((a, b) => a.s - b.s);
      const out: PiiSpan[] = [];
      let cursor = 0;
      for (const t of sorted) {
        if (t.s < cursor) continue;
        const end = Math.min(t.s + t.l, text.length);
        if (end <= t.s) continue;
        out.push({
          label: t.label,
          start: t.s,
          end,
          score: t.score,
          text: text.slice(t.s, end),
        });
        cursor = end;
      }
      return out;
    });
}

describe('PiiVault — property: sanitize ↔ restore round-trip', () => {
  it('every (text, non-overlapping spans) survives sanitize → restore unchanged', () => {
    fc.assert(
      fc.property(
        fc
          .string({ minLength: 1, maxLength: 200 })
          .chain((text) => spansArbitrary(text).map((spans) => ({ text, spans }))),
        ({ text, spans }) => {
          const v = new PiiVault();
          const id = v.createSession();
          const out = v.sanitize(text, spans, id);
          const back = v.restore(out.sanitized, id);
          expect(back.restored).toBe(text);
        },
      ),
      { numRuns: 200 },
    );
  });
});

/** Generate arbitrary spans: overlapping, nested, duplicated, and
 * reaching past either end of `text`, as a detector can emit them. */
function anySpansArbitrary(text: string): fc.Arbitrary<PiiSpan[]> {
  return fc.array(
    fc
      .tuple(
        fc.integer({ min: -3, max: text.length + 3 }),
        fc.integer({ min: 0, max: 12 }),
        fc.constantFrom(...CATEGORIES),
        fc.float({ min: 0, max: 1, noNaN: true }),
      )
      .map(([start, len, label, score]) => ({
        label,
        start,
        end: start + len,
        score,
        text: text.slice(Math.max(0, start), Math.max(0, start + len)),
      })),
    { maxLength: 10 },
  );
}

describe('PiiVault — property: any span set (overlapping, out of range)', () => {
  const textAndSpans = fc
    .string({ minLength: 1, maxLength: 200 })
    .chain((text) => anySpansArbitrary(text).map((spans) => ({ text, spans })));

  it('sanitize → restore is byte-exact', () => {
    fc.assert(
      fc.property(textAndSpans, ({ text, spans }) => {
        const v = new PiiVault();
        const id = v.createSession();
        const out = v.sanitize(text, spans, id);
        expect(v.restore(out.sanitized, id).restored).toBe(text);
      }),
      { numRuns: 500 },
    );
  });

  it('every character an input span covered is masked by a returned span', () => {
    fc.assert(
      fc.property(textAndSpans, ({ text, spans }) => {
        const v = new PiiVault();
        const out = v.sanitize(text, spans, v.createSession());
        for (const s of spans) {
          for (let i = Math.max(0, s.start); i < Math.min(text.length, s.end); i++) {
            expect(out.spans.some((m) => m.start <= i && i < m.end)).toBe(true);
          }
        }
      }),
      { numRuns: 500 },
    );
  });

  it('returned spans are sorted, disjoint, in range, and carry their exact text', () => {
    fc.assert(
      fc.property(textAndSpans, ({ text, spans }) => {
        const v = new PiiVault();
        const out = v.sanitize(text, spans, v.createSession());
        let cursor = 0;
        for (const m of out.spans) {
          expect(m.start).toBeGreaterThanOrEqual(cursor);
          expect(m.end).toBeLessThanOrEqual(text.length);
          expect(m.text).toBe(text.slice(m.start, m.end));
          cursor = m.end;
        }
      }),
      { numRuns: 500 },
    );
  });
});

describe('PiiVault — property: cross-session restore mismatch', () => {
  it('restoring placeholders minted in session A using session B with strict surfaces or throws', () => {
    fc.assert(
      fc.property(
        fc.string({ minLength: 1, maxLength: 100 }).chain((text) =>
          spansArbitrary(text)
            .filter((s) => s.length > 0)
            .map((spans) => ({ text, spans })),
        ),
        ({ text, spans }) => {
          const v = new PiiVault();
          const a = v.createSession();
          const b = v.createSession();
          const sanitized = v.sanitize(text, spans, a).sanitized;
          if (sanitized === text) return; // no placeholders emitted
          // Default mode surfaces foreign-prefix placeholders, no throw,
          // zero replacements (none belong to session b).
          const r = v.restore(sanitized, b);
          expect(r.foreignPlaceholders.length).toBeGreaterThan(0);
          expect(r.replacements).toBe(0);
          // strict: true still throws — legacy guarantee preserved.
          expect(() => v.restore(sanitized, b, { strict: true })).toThrow();
        },
      ),
      { numRuns: 100 },
    );
  });
});
