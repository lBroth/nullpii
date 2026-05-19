// SPDX-License-Identifier: Apache-2.0
//
// PLAN §2 — Streaming-safe placeholder restoration. SSE chunks from
// upstream LLM providers can split a placeholder mid-token
// (`{{PII_PRIV` | `ATE_PERSON_0_a1b2c3d4e5f6a7b8}}`). The naive approach
// (`restore()` on each chunk independently) would emit the unfinished
// `{{PII_PRIV` as literal text downstream, leaking the placeholder
// shape and breaking the downstream display.
//
// RestoreStream buffers until each placeholder is complete OR until
// the safety cap forces a flush, then resolves complete placeholders
// against the vault on `push()`.

import { describe, expect, it } from 'vitest';
import { SessionMismatchError } from '../src/errors.js';
import { RestoreStream } from '../src/restore-stream.js';
import type { PiiSpan } from '../src/types/index.js';
import { PiiVault } from '../src/vault.js';
import { span } from './helpers.js';

function makeSession(
  text: string,
  spans: PiiSpan[],
): { vault: PiiVault; id: string; sanitized: string } {
  const vault = new PiiVault();
  const id = vault.createSession();
  const r = vault.sanitize(text, spans, id);
  return { vault, id, sanitized: r.sanitized };
}

describe('RestoreStream', () => {
  it('round-trips a single placeholder fed in one chunk', () => {
    const { vault, id, sanitized } = makeSession('Hi John', [span('private_person', 3, 7, 'John')]);
    const stream = new RestoreStream(vault, id);
    const emitted = stream.push(sanitized);
    const final = stream.end();
    expect(emitted + final.restored).toBe('Hi John');
    expect(final.replacements).toBe(1);
  });

  it('buffers an incomplete placeholder across two chunks', () => {
    const { vault, id, sanitized } = makeSession('Hi John', [span('private_person', 3, 7, 'John')]);
    // Split the placeholder mid-way through the hex segment.
    const mid = Math.floor(sanitized.length / 2);
    const part1 = sanitized.slice(0, mid);
    const part2 = sanitized.slice(mid);
    const stream = new RestoreStream(vault, id);
    const out1 = stream.push(part1);
    const out2 = stream.push(part2);
    const final = stream.end();
    expect(out1 + out2 + final.restored).toBe('Hi John');
  });

  it('round-trips when the placeholder is fragmented at EVERY byte offset', () => {
    const { vault, id, sanitized } = makeSession('Email john@acme.io now', [
      span('private_email', 6, 18, 'john@acme.io'),
    ]);
    for (let split = 0; split <= sanitized.length; split++) {
      const a = sanitized.slice(0, split);
      const b = sanitized.slice(split);
      const stream = new RestoreStream(vault, id);
      const out = stream.push(a) + stream.push(b) + stream.end().restored;
      expect(out, `split at ${split}`).toBe('Email john@acme.io now');
    }
  });

  it('round-trips when the input is fed one byte at a time', () => {
    const { vault, id, sanitized } = makeSession('Hi Alice and Bob met', [
      span('private_person', 3, 8, 'Alice'),
      span('private_person', 13, 16, 'Bob'),
    ]);
    const stream = new RestoreStream(vault, id);
    let out = '';
    for (const ch of sanitized) out += stream.push(ch);
    out += stream.end().restored;
    expect(out).toBe('Hi Alice and Bob met');
  });

  it('emits literal text up to the safe boundary so downstream sees progressive output', () => {
    const { vault, id, sanitized } = makeSession('Hello {{not-a-placeholder}} and John', [
      span('private_person', 32, 36, 'John'),
    ]);
    const stream = new RestoreStream(vault, id);
    // Feed everything up to (but not including) the placeholder start —
    // including the literal `{{not-a-placeholder}}` (the open `{{` closes
    // before any session-prefix-bearing pattern, so it's safe to flush).
    const placeholderStart = sanitized.indexOf('{{PII_');
    const head = sanitized.slice(0, placeholderStart);
    const out1 = stream.push(head);
    expect(out1.length).toBeGreaterThan(0);
    expect(out1).toContain('Hello');
    // Feed the placeholder.
    const out2 = stream.push(sanitized.slice(placeholderStart));
    const final = stream.end();
    expect(out1 + out2 + final.restored).toBe('Hello {{not-a-placeholder}} and John');
  });

  it('surfaces unknown placeholders just like vault.restore() does', () => {
    const { vault, id, sanitized } = makeSession('Hi John', [span('private_person', 3, 7, 'John')]);
    const sessionPrefix = id.replace(/-/g, '').slice(0, 16).toLowerCase();
    const llmReply = `${sanitized} also {{PII_PRIVATE_PERSON_42_${sessionPrefix}}}`;
    const stream = new RestoreStream(vault, id);
    stream.push(llmReply);
    const final = stream.end();
    expect(final.unknownPlaceholders).toHaveLength(1);
    expect(final.replacements).toBe(1);
  });

  it('strict mode throws when a foreign-prefix placeholder appears mid-stream', () => {
    const vaultA = new PiiVault();
    const idA = vaultA.createSession();
    const idB = vaultA.createSession();
    const prefixB = idB.replace(/-/g, '').slice(0, 16).toLowerCase();
    vaultA.sanitize('John', [span('private_person', 0, 4, 'John')], idA);
    const text = `Hi {{PII_PRIVATE_PERSON_0_${prefixB}}}!`;
    const stream = new RestoreStream(vaultA, idA, { strict: true });
    expect(() => {
      stream.push(text);
      stream.end();
    }).toThrow(SessionMismatchError);
  });

  it('forces a flush when the open-brace buffer exceeds the safety cap', () => {
    const { vault, id } = makeSession('placeholder text', [
      span('private_person', 0, 11, 'placeholder'),
    ]);
    // Feed `{{` followed by 1 KB of innocuous text with no closing `}}`.
    // The buffer cannot grow without bound — past the cap, the open `{{`
    // is emitted as literal so the stream stays bounded.
    const stream = new RestoreStream(vault, id);
    const out1 = stream.push('{{');
    // Should NOT have emitted yet — `{{` looks like a placeholder start.
    expect(out1).toBe('');
    const padding = 'a'.repeat(2000); // exceed the safety cap
    const out2 = stream.push(padding);
    const final = stream.end();
    // Combined output preserves the literal `{{aaa…`
    expect(out1 + out2 + final.restored).toBe(`{{${padding}`);
  });

  it('handles multiple complete placeholders in a single chunk', () => {
    const { vault, id, sanitized } = makeSession('a@x.com and b@x.com', [
      span('private_email', 0, 7, 'a@x.com'),
      span('private_email', 12, 19, 'b@x.com'),
    ]);
    const stream = new RestoreStream(vault, id);
    const out = stream.push(sanitized) + stream.end().restored;
    expect(out).toBe('a@x.com and b@x.com');
  });
});
