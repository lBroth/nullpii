import { describe, expect, it } from 'vitest';
import { SessionMismatchError, SessionNotFoundError } from '../src/errors.js';
import type { PiiSpan } from '../src/types/index.js';
import { PiiVault } from '../src/vault.js';

const UUID_V4_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const PLACEHOLDER_RE = /\{\{PII_[A-Z_]+_\d+_[0-9a-f]{16}\}\}/;
const SESSION_PREFIX_RE = /[0-9a-f]{16}/;

function span(label: PiiSpan['label'], start: number, end: number, text: string): PiiSpan {
  return { label, start, end, text, score: 1.0 };
}

function expectedPrefix(id: string): string {
  return id.replace(/-/g, '').slice(0, 16).toLowerCase();
}

describe('PiiVault.createSession', () => {
  it('returns a UUID v4', () => {
    const v = new PiiVault();
    expect(UUID_V4_RE.test(v.createSession())).toBe(true);
  });

  it('returns a unique id every call', () => {
    const v = new PiiVault();
    const ids = new Set([v.createSession(), v.createSession(), v.createSession()]);
    expect(ids.size).toBe(3);
  });
});

describe('PiiVault.sanitize', () => {
  it('replaces a single span with the typed session-tagged placeholder', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const text = 'Hi John there.';
    const result = v.sanitize(text, [span('private_person', 3, 7, 'John')], id);
    expect(result.sanitized).toBe(`Hi {{PII_PRIVATE_PERSON_0_${expectedPrefix(id)}}} there.`);
  });

  it('replaces multiple spans of different labels correctly', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const p = expectedPrefix(id);
    const text = 'Email john@x.com or call 555-1212.';
    const spans = [
      span('private_email', 6, 16, 'john@x.com'),
      span('private_phone', 25, 33, '555-1212'),
    ];
    const result = v.sanitize(text, spans, id);
    expect(result.sanitized).toBe(
      `Email {{PII_PRIVATE_EMAIL_0_${p}}} or call {{PII_PRIVATE_PHONE_0_${p}}}.`,
    );
  });

  it('assigns distinct indices to same-label spans', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const p = expectedPrefix(id);
    const text = 'Alice and Bob met.';
    const spans = [span('private_person', 0, 5, 'Alice'), span('private_person', 10, 13, 'Bob')];
    const result = v.sanitize(text, spans, id);
    expect(result.sanitized).toBe(
      `{{PII_PRIVATE_PERSON_0_${p}}} and {{PII_PRIVATE_PERSON_1_${p}}} met.`,
    );
  });

  it('preserves char offsets when many spans are present (back-to-front)', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const text = 'a@x.com / b@y.com / c@z.com';
    const spans = [
      span('private_email', 0, 7, 'a@x.com'),
      span('private_email', 10, 17, 'b@y.com'),
      span('private_email', 20, 27, 'c@z.com'),
    ];
    const result = v.sanitize(text, spans, id);
    const restored = v.restore(result.sanitized, id);
    expect(restored.restored).toBe(text);
  });

  it('returns text unchanged when no spans are given', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const r = v.sanitize('hello', [], id);
    expect(r.sanitized).toBe('hello');
    expect(r.spans).toEqual([]);
  });

  it('throws SessionNotFoundError for unknown session', () => {
    const v = new PiiVault();
    expect(() => v.sanitize('x', [], 'not-real')).toThrow(SessionNotFoundError);
  });

  it('embeds the session prefix in every placeholder', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const result = v.sanitize('Hi John', [span('private_person', 3, 7, 'John')], id);
    const match = PLACEHOLDER_RE.exec(result.sanitized);
    expect(match).not.toBeNull();
    expect(SESSION_PREFIX_RE.test(match?.[0] ?? '')).toBe(true);
  });
});

describe('PiiVault.restore', () => {
  it('round-trips byte-for-byte for a typical input', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const text = 'My name is Alice and email is alice@x.com.';
    const spans = [
      span('private_person', 11, 16, 'Alice'),
      span('private_email', 30, 41, 'alice@x.com'),
    ];
    const r = v.sanitize(text, spans, id);
    const back = v.restore(r.sanitized, id);
    expect(back.restored).toBe(text);
    expect(back.replacements).toBe(2);
  });

  it('returns text unchanged when no placeholders are present', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const r = v.restore('plain text, no placeholders here', id);
    expect(r.restored).toBe('plain text, no placeholders here');
    expect(r.replacements).toBe(0);
  });

  it('leaves unknown placeholders (with matching session prefix) as-is', () => {
    const v = new PiiVault();
    const id = v.createSession();
    const p = expectedPrefix(id);
    const text = `text {{PII_SECRET_42_${p}}} foreign`;
    const r = v.restore(text, id);
    expect(r.restored).toBe(text);
    expect(r.replacements).toBe(0);
  });

  it('surfaces foreign-prefix placeholders in foreignPlaceholders (default mode)', () => {
    const v = new PiiVault();
    const idA = v.createSession();
    const idB = v.createSession();
    const result = v.sanitize('Hi John', [span('private_person', 3, 7, 'John')], idA);
    const r = v.restore(result.sanitized, idB);
    expect(r.foreignPlaceholders).toHaveLength(1);
    expect(r.replacements).toBe(0);
    expect(r.restored).toBe(result.sanitized);
  });

  it('throws SessionMismatchError with strict: true on foreign-prefix placeholder', () => {
    const v = new PiiVault();
    const idA = v.createSession();
    const idB = v.createSession();
    const result = v.sanitize('Hi John', [span('private_person', 3, 7, 'John')], idA);
    expect(() => v.restore(result.sanitized, idB, { strict: true })).toThrow(SessionMismatchError);
  });

  it('throws SessionNotFoundError for unknown session', () => {
    const v = new PiiVault();
    expect(() => v.restore('x', 'unknown')).toThrow(SessionNotFoundError);
  });
});

describe('PiiVault.destroySession', () => {
  it('subsequent sanitize/restore on a destroyed session throws', () => {
    const v = new PiiVault();
    const id = v.createSession();
    v.destroySession(id);
    expect(() => v.sanitize('x', [], id)).toThrow(SessionNotFoundError);
    expect(() => v.restore('x', id)).toThrow(SessionNotFoundError);
  });

  it('is a no-op for unknown sessions', () => {
    const v = new PiiVault();
    expect(() => v.destroySession('does-not-exist')).not.toThrow();
  });

  it('decrements sessionCount', () => {
    const v = new PiiVault();
    const id = v.createSession();
    expect(v.sessionCount).toBe(1);
    v.destroySession(id);
    expect(v.sessionCount).toBe(0);
  });
});

describe('PiiVault.clear', () => {
  it('drops every session', () => {
    const v = new PiiVault();
    v.createSession();
    v.createSession();
    expect(v.sessionCount).toBe(2);
    v.clear();
    expect(v.sessionCount).toBe(0);
  });

  it('subsequent sanitize on a cleared session throws', () => {
    const v = new PiiVault();
    const id = v.createSession();
    v.clear();
    expect(() => v.sanitize('x', [], id)).toThrow(SessionNotFoundError);
  });
});
