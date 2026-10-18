// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import type { PiiSpan } from '../src/types/index.js';
import { dropCleanPublicUrlSpans, isPublicUrl } from '../src/url-filter.js';

/** Spans must carry realistic, non-overlapping offsets: the drop rule is
 * containment-aware, so a fixture that parks every span at 0 would read
 * as "this URL has PII nested inside it" and keep everything. */
function urlSpan(text: string, start = 0): PiiSpan {
  return { label: 'private_url', start, end: start + text.length, text, score: 0.95 };
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

  it('matches the package-registry tarball hosts lockfiles cite', () => {
    expect(isPublicUrl('https://registry.npmjs.org/fastify/-/fastify-5.2.0.tgz')).toBe(true);
    expect(isPublicUrl('https://registry.yarnpkg.com/debug/-/debug-4.4.3.tgz')).toBe(true);
    expect(isPublicUrl('https://files.pythonhosted.org/packages/ab/cd/numpy-2.0.whl')).toBe(true);
  });

  it('matches README badge, CI, coverage and CDN hosts', () => {
    for (const u of [
      'https://img.shields.io/npm/v/debug.svg',
      'https://travis-ci.org/debug-js/debug.svg?branch=master',
      'https://coveralls.io/repos/github/debug-js/debug/badge.svg',
      'https://badge.fury.io/js/debug.svg',
      'https://cdn.jsdelivr.net/npm/debug@4/src/index.js',
      'https://raw.githubusercontent.com/debug-js/debug/master/README.md',
    ]) {
      expect(isPublicUrl(u), u).toBe(true);
    }
  });

  it('keeps personal websites masked', () => {
    expect(isPublicUrl('https://sindresorhus.com')).toBe(false);
    expect(isPublicUrl('https://feross.org/support')).toBe(false);
  });

  it('does not extend to look-alike or private registry hosts', () => {
    expect(isPublicUrl('https://registry.npmjs.org.attacker.io/x')).toBe(false);
    expect(isPublicUrl('https://npm.acme-corp.internal/pkg/-/pkg-1.0.0.tgz')).toBe(false);
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

describe('dropCleanPublicUrlSpans', () => {
  it('drops private_url spans matching the allowlist, keeps others', () => {
    const spans: PiiSpan[] = [
      urlSpan('https://github.com/foo', 0),
      urlSpan('https://acme.io/internal', 30),
      { label: 'private_email', start: 60, end: 67, text: 'a@b.com', score: 0.95 },
    ];
    const out = dropCleanPublicUrlSpans(spans);
    expect(out).toHaveLength(2);
    expect(out.find((s) => s.text === 'https://github.com/foo')).toBeUndefined();
    expect(out.find((s) => s.text === 'https://acme.io/internal')).toBeDefined();
    expect(out.find((s) => s.label === 'private_email')).toBeDefined();
  });

  it('drops url fragments inside a dropped public URL, keeps fragments of private ones', () => {
    const pub = 'https://registry.npmjs.org/debug/-/debug-4.4.3.tgz';
    const priv = 'https://npm.acme-corp.internal/pkg.tgz';
    const spans: PiiSpan[] = [
      urlSpan(pub, 0),
      { label: 'private_url', start: 0, end: 7, text: 'https:/', score: 0.6 },
      urlSpan(priv, 100),
      { label: 'private_url', start: 100, end: 107, text: 'https:/', score: 0.6 },
    ];
    const out = dropCleanPublicUrlSpans(spans);
    expect(out.map((s) => s.start)).toEqual([100, 100]);
  });

  it('drops a README badge span that covers two public URLs', () => {
    const badge = 'https://img.shields.io/travis/foo/bar.svg)](https://travis-ci.org/foo/bar';
    expect(dropCleanPublicUrlSpans([urlSpan(badge, 10)])).toEqual([]);
  });

  it('keeps the private URL of a span that joins a public and a private one', () => {
    const joined = 'https://github.com/foo,https://acme.io/internal';
    const out = dropCleanPublicUrlSpans([urlSpan(joined, 5)]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      label: 'private_url',
      start: 28,
      end: 52,
      text: 'https://acme.io/internal',
    });
  });

  it('keeps the private URL when it comes first', () => {
    const joined = 'https://acme.io/internal)](https://github.com/foo';
    const out = dropCleanPublicUrlSpans([urlSpan(joined, 0)]);
    expect(out.map((s) => s.text)).toEqual(['https://acme.io/internal)](']);
  });

  it('keeps a multi-URL span whole when none of its URLs is public', () => {
    const span = urlSpan('https://acme.io/a,https://corp.example/b', 0);
    expect(dropCleanPublicUrlSpans([span])).toEqual([span]);
  });

  it('keeps a public part that holds another PII span', () => {
    const joined = 'https://github.com/a,AKIAIOSFODNN7EXAMPLE,https://github.com/b';
    const secret = {
      label: 'secret' as const,
      start: 21,
      end: 41,
      text: 'AKIAIOSFODNN7EXAMPLE',
      score: 0.9,
    };
    const out = dropCleanPublicUrlSpans([urlSpan(joined, 0), secret]);
    expect(out.map((s) => [s.label, s.text])).toEqual([
      ['private_url', 'https://github.com/a,AKIAIOSFODNN7EXAMPLE,'],
      ['secret', 'AKIAIOSFODNN7EXAMPLE'],
    ]);
  });

  it('never judges text before the first scheme as a public URL', () => {
    const span = urlSpan('see:https://github.com/a)](https://github.com/b', 0);
    expect(dropCleanPublicUrlSpans([span]).map((s) => s.text)).toEqual([
      'see:https://github.com/a)](',
    ]);
  });

  it('passes through when no private_url spans are present', () => {
    const spans: PiiSpan[] = [
      { label: 'private_email', start: 0, end: 7, text: 'a@b.com', score: 0.95 },
    ];
    expect(dropCleanPublicUrlSpans(spans)).toEqual(spans);
  });
});
