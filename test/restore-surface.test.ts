// SPDX-License-Identifier: Apache-2.0
//
// F-07 + F-08 + F-13 regression tests. `PiiVault.restore` previously:
//   - silently left "unknown" placeholders (matching session prefix, no
//     vault entry — typically LLM hallucinations) as literal strings in
//     the restored output, returning no signal to the caller (F-07);
//   - threw `SessionMismatchError` on a foreign-prefix placeholder AFTER
//     the entire replace pass, discarding all the legit replacements it
//     had already computed (F-08 + F-13).
//
// New contract: default mode collects both anomaly classes into
// `RestoreResult.unknownPlaceholders` and `.foreignPlaceholders`,
// keeps the literal placeholders in the restored text, and substitutes
// every matching entry. Callers opt into the throwing variant with
// `{ strict: true }`.

import { describe, expect, it } from 'vitest';
import { SessionMismatchError, UnknownPlaceholderError } from '../src/errors.js';
import { sessionPrefixOf as expectedPrefix } from '../src/session-prefix.js';
import type { PiiSpan } from '../src/types/index.js';
import { PiiVault } from '../src/vault.js';
import { span } from './helpers.js';

// F-32 regression block lives at the bottom of this file.

describe('F-07 · unknown placeholder (matching prefix, unknown idx)', () => {
  it('returns unknownPlaceholders, leaves literal, does not throw', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const p = expectedPrefix(id);

    // Sanitize a real span so the vault has entry idx=0.
    const sanitized = v.sanitize('Hi John', [span('private_person', 3, 7, 'John')], id);

    // LLM hallucinates idx=42 placeholder using the same session prefix.
    const llmReply = `${sanitized.sanitized} and {{PII_PRIVATE_PERSON_42_${p}}}`;

    const r = v.restore(llmReply, id);
    // Real placeholder restored.
    expect(r.restored).toContain('John');
    expect(r.replacements).toBe(1);
    // Hallucination surfaced + left literal.
    expect(r.unknownPlaceholders).toEqual([`{{PII_PRIVATE_PERSON_42_${p}}}`]);
    expect(r.restored).toContain(`{{PII_PRIVATE_PERSON_42_${p}}}`);
    expect(r.foreignPlaceholders).toEqual([]);
  });

  it('strict: true throws UnknownPlaceholderError', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const p = expectedPrefix(id);
    const sanitized = v.sanitize('Hi John', [span('private_person', 3, 7, 'John')], id);
    const llmReply = `${sanitized.sanitized} and {{PII_PRIVATE_PERSON_42_${p}}}`;
    expect(() => v.restore(llmReply, id, { strict: true })).toThrow(UnknownPlaceholderError);
  });
});

describe('F-08 / F-13 · foreign-prefix placeholder', () => {
  it('returns foreignPlaceholders, replaces matching entries, does not throw by default', () => {
    const v = new PiiVault();
    const idA = v.createSession();
    const idB = v.createSession();
    const pA = expectedPrefix(idA);
    const pB = expectedPrefix(idB);

    // Session A mints a real placeholder.
    const sanitizedA = v.sanitize('Hi John', [span('private_person', 3, 7, 'John')], idA);

    // User input also carries a foreign placeholder for session B.
    const mixed = `${sanitizedA.sanitized} and stray {{PII_PRIVATE_PERSON_0_${pB}}}`;

    const r = v.restore(mixed, idA);
    // F-08 fix: legitimate replacements survive, no throw.
    expect(r.restored).toContain('John');
    expect(r.replacements).toBe(1);
    // Foreign placeholder surfaced + left literal.
    expect(r.foreignPlaceholders).toEqual([`{{PII_PRIVATE_PERSON_0_${pB}}}`]);
    expect(r.restored).toContain(`{{PII_PRIVATE_PERSON_0_${pB}}}`);
    expect(r.unknownPlaceholders).toEqual([]);
    // Sanity: both placeholders accounted for.
    expect(pA).not.toBe(pB);
  });

  it('strict: true throws SessionMismatchError on first foreign-prefix hit', () => {
    const v = new PiiVault();
    const idA = v.createSession();
    const idB = v.createSession();
    const pB = expectedPrefix(idB);
    const sanitizedA = v.sanitize('Hi John', [span('private_person', 3, 7, 'John')], idA);
    const mixed = `${sanitizedA.sanitized} stray {{PII_PRIVATE_PERSON_0_${pB}}}`;
    expect(() => v.restore(mixed, idA, { strict: true })).toThrow(SessionMismatchError);
  });

  it('collects multiple foreign + unknown placeholders in one pass', () => {
    const v = new PiiVault();
    const idA = v.createSession();
    const idB = v.createSession();
    const pA = expectedPrefix(idA);
    const pB = expectedPrefix(idB);
    const sanitized = v.sanitize('Hi John', [span('private_person', 3, 7, 'John')], idA);
    const text =
      `${sanitized.sanitized} ` +
      `stray-foreign-1 {{PII_PRIVATE_EMAIL_0_${pB}}} ` +
      `stray-foreign-2 {{PII_SECRET_5_${pB}}} ` +
      `hallucinated {{PII_PRIVATE_PERSON_99_${pA}}}`;
    const r = v.restore(text, idA);
    expect(r.replacements).toBe(1);
    expect(r.foreignPlaceholders).toHaveLength(2);
    expect(r.unknownPlaceholders).toHaveLength(1);
    expect(r.restored).toContain('John');
  });
});

// F-32 regression. `RestoreResult.replacementsByLabel` exposes per-label
// substitution counts for downstream observability — "did the LLM
// preserve placeholders?" / "which categories actually round-tripped?"
// Caller-visible without spelunking through `spans`.
describe('F-32 · RestoreResult.replacementsByLabel', () => {
  it('counts substitutions grouped by PII label', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const text = 'Hi Alice, then Bob and email a@x.com or b@x.com';
    const spans: PiiSpan[] = [
      { label: 'private_person', start: 3, end: 8, text: 'Alice', score: 1 },
      { label: 'private_person', start: 15, end: 18, text: 'Bob', score: 1 },
      { label: 'private_email', start: 29, end: 36, text: 'a@x.com', score: 1 },
      { label: 'private_email', start: 40, end: 47, text: 'b@x.com', score: 1 },
    ];
    const sanitized = v.sanitize(text, spans, id).sanitized;
    const r = v.restore(sanitized, id);
    expect(r.replacements).toBe(4);
    expect(r.replacementsByLabel).toEqual({
      private_person: 2,
      private_email: 2,
    });
  });

  it('returns an empty object when nothing is restored', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const r = v.restore('plain text no placeholders', id);
    expect(r.replacements).toBe(0);
    expect(r.replacementsByLabel).toEqual({});
  });

  it('does not count anomalous (unknown/foreign) placeholders', () => {
    const v = new PiiVault();
    const idA = v.createSession();
    const idB = v.createSession();
    const pB = idB.replace(/-/g, '').slice(0, 16).toLowerCase();
    const sanitized = v.sanitize(
      'Hi John',
      [{ label: 'private_person', start: 3, end: 7, text: 'John', score: 1 }],
      idA,
    ).sanitized;
    const text = `${sanitized} stray-foreign {{PII_PRIVATE_EMAIL_0_${pB}}}`;
    const r = v.restore(text, idA);
    expect(r.replacementsByLabel).toEqual({ private_person: 1 });
    expect(r.foreignPlaceholders).toHaveLength(1);
  });
});
