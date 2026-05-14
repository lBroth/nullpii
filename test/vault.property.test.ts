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

describe('PiiVault — property: cross-session restore mismatch', () => {
  it('restoring placeholders minted in session A using session B throws SessionMismatchError', () => {
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
          expect(() => v.restore(sanitized, b)).toThrow();
        },
      ),
      { numRuns: 100 },
    );
  });
});
