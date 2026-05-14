// SPDX-License-Identifier: Apache-2.0

import { Buffer } from 'node:buffer';
import { describe, expect, it } from 'vitest';
import { detectBase64Pii } from '../src/base64-detector.js';

function b64(s: string): string {
  return Buffer.from(s, 'utf8').toString('base64');
}

describe('detectBase64Pii', () => {
  it('tags a base64-wrapped email as private_email', () => {
    // `dXNlci4xMjNAZ21haWwuY29t` decodes to `user.123@gmail.com`.
    const blob = b64('user.123@gmail.com');
    const text = `(payload) ${blob}`;
    const spans = detectBase64Pii(text, []);
    expect(spans).toHaveLength(1);
    const s = spans[0];
    if (!s) throw new Error('no span');
    expect(s.label).toBe('private_email');
    expect(s.start).toBe('(payload) '.length);
    expect(s.end).toBe(text.length);
    // Score is set higher than typical ML softmax so cross-label dedupe
    // picks the decoded label over the model's `secret` fallback.
    expect(s.score).toBeGreaterThan(0.999);
  });

  it('tags a base64-wrapped sk- API key as secret', () => {
    const blob = b64('sk-ant-api03-aBcDeFgHiJkLmNoP01234567');
    const spans = detectBase64Pii(blob, []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('secret');
  });

  it('tags a base64-wrapped long-digit run as account_number', () => {
    const blob = b64('order 4111111111111111 confirmed');
    const spans = detectBase64Pii(blob, []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('account_number');
  });

  it('skips base64 of innocuous text (no classified pattern)', () => {
    const blob = b64('just a friendly greeting message here');
    expect(detectBase64Pii(blob, [])).toEqual([]);
  });

  it('skips short base64-looking runs (length < 24)', () => {
    const text = 'hello YWJj world'; // YWJj = "abc"
    expect(detectBase64Pii(text, [])).toEqual([]);
  });

  it('skips runs whose length is not a multiple of 4', () => {
    // `alice@acme.com` → 20 b64 chars *with* `==` padding; stripping the
    // padding gives 18 chars (length % 4 === 2) — must be rejected.
    // Pad with non-b64 punctuation to push the regex run over the 24-char
    // minimum length threshold, isolating the multiple-of-4 check.
    const blob = b64('verylonguser@realdomain-example.com').replace(/=+$/, '');
    expect(blob.length).toBeGreaterThanOrEqual(24);
    expect(blob.length % 4).not.toBe(0);
    expect(detectBase64Pii(blob, [])).toEqual([]);
  });

  it('skips base64 that decodes to non-printable bytes', () => {
    // 24 random binary bytes → base64 stays the same length, decoded
    // contains control chars.
    const binary = Buffer.from([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23,
    ]);
    const blob = binary.toString('base64');
    expect(detectBase64Pii(blob, [])).toEqual([]);
  });

  it('skips non-base64 text', () => {
    expect(detectBase64Pii('just a normal sentence about nothing', [])).toEqual([]);
  });

  it('detects multiple distinct base64 PII blobs in one input', () => {
    // Both blobs must be ≥24 chars for the regex to fire on them.
    const e = b64('verylonguser@really-cool-domain.example.com');
    const s = b64('sk-ant-api03-aBcDeFgHiJkLmNoP01234567');
    const text = `email: ${e} | key: ${s}`;
    expect(e.length).toBeGreaterThanOrEqual(24);
    expect(s.length).toBeGreaterThanOrEqual(24);
    const spans = detectBase64Pii(text, []);
    expect(spans).toHaveLength(2);
    const labels = spans.map((sp) => sp.label).sort();
    expect(labels).toEqual(['private_email', 'secret']);
  });

  it('ignores the `existing` arg (cross-label dedupe handles overlap)', () => {
    // A pre-existing `secret` span over the blob must NOT suppress the
    // detector — it still emits a `private_email` so dedupe can pick
    // the correct label later.
    const blob = b64('verylonguser@really-cool-domain.example.com');
    expect(blob.length).toBeGreaterThanOrEqual(24);
    const spans = detectBase64Pii(blob, [
      { label: 'secret', start: 0, end: blob.length, score: 0.99, text: blob },
    ]);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('private_email');
  });
});
