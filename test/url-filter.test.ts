// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import type { PiiSpan } from '../src/types/index.js';
import { dropPublicUrlSpans, isPublicUrl } from '../src/url-filter.js';

function urlSpan(text: string): PiiSpan {
  return { label: 'private_url', start: 0, end: text.length, text, score: 0.95 };
}

describe('isPublicUrl', () => {
  it('matches direct hosts (github.com, anthropic.com)', () => {
    expect(isPublicUrl('https://github.com/foo/bar')).toBe(true);
    expect(isPublicUrl('https://anthropic.com/news')).toBe(true);
  });

  it('matches subdomains of allowlisted hosts', () => {
    expect(isPublicUrl('https://docs.python.org/3/library/')).toBe(true);
    expect(isPublicUrl('https://developer.mozilla.org/en-US/')).toBe(true);
  });

  it('strips `www.` prefix before lookup', () => {
    expect(isPublicUrl('https://www.wikipedia.org/wiki/Foo')).toBe(true);
    expect(isPublicUrl('www.github.com/issues')).toBe(true);
  });

  it('rejects unrelated hosts', () => {
    expect(isPublicUrl('https://acme.io/internal/dashboard')).toBe(false);
    expect(isPublicUrl('https://example.com/foo')).toBe(false);
  });

  it('rejects malformed input (over-redact stance)', () => {
    expect(isPublicUrl('not a url')).toBe(false);
    expect(isPublicUrl('javascript:alert(1)')).toBe(false);
    expect(isPublicUrl('')).toBe(false);
  });
});

describe('dropPublicUrlSpans', () => {
  it('drops private_url spans matching the allowlist, keeps others', () => {
    const spans: PiiSpan[] = [
      urlSpan('https://github.com/foo'),
      urlSpan('https://acme.io/internal'),
      { label: 'private_email', start: 0, end: 13, text: 'a@b.com', score: 0.95 },
    ];
    const out = dropPublicUrlSpans(spans);
    expect(out).toHaveLength(2);
    expect(out.find((s) => s.text === 'https://github.com/foo')).toBeUndefined();
    expect(out.find((s) => s.text === 'https://acme.io/internal')).toBeDefined();
    expect(out.find((s) => s.label === 'private_email')).toBeDefined();
  });

  it('passes through when no private_url spans are present', () => {
    const spans: PiiSpan[] = [
      { label: 'private_email', start: 0, end: 7, text: 'a@b.com', score: 0.95 },
    ];
    expect(dropPublicUrlSpans(spans)).toEqual(spans);
  });
});
