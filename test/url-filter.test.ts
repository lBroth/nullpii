// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { InvalidConfigError } from '../src/errors.js';
import type { PiiSpan, UrlRelease } from '../src/types/index.js';
import { dropCleanPublicUrlSpans, urlPolicy, urlRelease } from '../src/url-filter.js';

/** Spans must carry realistic, non-overlapping offsets: the drop rule is
 * containment-aware, so a fixture that parks every span at 0 would read
 * as "this URL has PII nested inside it" and keep everything. */
function urlSpan(text: string, start = 0): PiiSpan {
  return { label: 'private_url', start, end: start + text.length, text, score: 0.95 };
}

const POLICY = urlPolicy();

describe('urlRelease, built-in policy', () => {
  it('releases code-hosting URLs whole by default', () => {
    for (const u of [
      'https://github.com/foo/bar',
      'https://gist.github.com/alice/0123abcd',
      'https://gitlab.com/group/project/-/issues/3',
      'https://raw.githubusercontent.com/debug-js/debug/master/README.md',
      'https://huggingface.co/alice/private-model',
    ]) {
      expect(urlRelease(u, POLICY), u).toBe('full');
    }
  });

  it('releases reference and documentation URLs whole', () => {
    expect(urlRelease('https://anthropic.com/news', POLICY)).toBe('full');
    expect(urlRelease('https://docs.python.org/3/library/', POLICY)).toBe('full');
    expect(urlRelease('https://developer.mozilla.org/en-US/', POLICY)).toBe('full');
  });

  it('releases the package-registry tarball hosts lockfiles cite', () => {
    for (const u of [
      'https://registry.npmjs.org/fastify/-/fastify-5.2.0.tgz',
      'https://registry.yarnpkg.com/debug/-/debug-4.4.3.tgz',
      'https://files.pythonhosted.org/packages/ab/cd/numpy-2.0.whl',
    ]) {
      expect(urlRelease(u, POLICY), u).toBe('full');
    }
  });

  it('releases README badge, CI, coverage and CDN hosts', () => {
    for (const u of [
      'https://img.shields.io/npm/v/debug.svg',
      'https://travis-ci.org/debug-js/debug.svg?branch=master',
      'https://coveralls.io/repos/github/debug-js/debug/badge.svg',
      'https://badge.fury.io/js/debug.svg',
      'https://cdn.jsdelivr.net/npm/debug@4/src/index.js',
    ]) {
      expect(urlRelease(u, POLICY), u).toBe('full');
    }
  });

  it('keeps customer consoles under a vendor domain masked', () => {
    for (const u of [
      'https://console.aws.amazon.com/ec2/home?region=eu-west-1#Instances:',
      'https://console.anthropic.com/settings/keys',
      'https://storage.cloud.google.com/acme-private-bucket/report.pdf',
    ]) {
      expect(urlRelease(u, POLICY), u).toBe('mask');
    }
  });

  it('keeps personal websites masked', () => {
    expect(urlRelease('https://sindresorhus.com', POLICY)).toBe('mask');
    expect(urlRelease('https://feross.org/support', POLICY)).toBe('mask');
  });

  it('does not extend to look-alike or private registry hosts', () => {
    expect(urlRelease('https://registry.npmjs.org.attacker.io/x', POLICY)).toBe('mask');
    expect(urlRelease('https://npm.acme-corp.internal/pkg/-/pkg-1.0.0.tgz', POLICY)).toBe('mask');
  });

  it('ignores a leading `www.`', () => {
    expect(urlRelease('https://www.wikipedia.org/wiki/Foo', POLICY)).toBe('full');
    expect(urlRelease('www.github.com/issues', POLICY)).toBe('full');
  });

  it('masks unrelated hosts and malformed input (over-redact stance)', () => {
    expect(urlRelease('https://acme.io/internal/dashboard', POLICY)).toBe('mask');
    expect(urlRelease('https://example.com/foo', POLICY)).toBe('mask');
    expect(urlRelease('not a url', POLICY)).toBe('mask');
    expect(urlRelease('javascript:alert(1)', POLICY)).toBe('mask');
    expect(urlRelease('', POLICY)).toBe('mask');
  });
});

describe('urlPolicy, configured', () => {
  it('merges configured hosts over the built-in policy', () => {
    const policy = urlPolicy({ hosts: { '*.github.com': 'full', 'intranet.acme.io': 'host' } });
    expect(policy('github.com')).toBe('full');
    expect(policy('intranet.acme.io')).toBe('host');
    expect(policy('docs.python.org')).toBe('full');
  });

  it('switches a built-in host off with `mask`', () => {
    expect(urlPolicy({ hosts: { '*.python.org': 'mask' } })('docs.python.org')).toBe('mask');
  });

  it('lets the most specific key win', () => {
    const policy = urlPolicy({ hosts: { '*.github.com': 'mask', 'docs.github.com': 'full' } });
    expect(policy('docs.github.com')).toBe('full');
    expect(policy('github.com')).toBe('mask');
    expect(policy('gist.github.com')).toBe('mask');
  });

  it('uses only the configured hosts with `replaceDefaults`', () => {
    const policy = urlPolicy({ replaceDefaults: true, hosts: { 'acme.io': 'full' } });
    expect(policy('acme.io')).toBe('full');
    expect(policy('github.com')).toBe('mask');
  });

  it('rejects a malformed host key or an unknown release', () => {
    for (const key of ['https://github.com', 'GitHub.com', '*github.com', 'github', '*.', '']) {
      expect(() => urlPolicy({ hosts: { [key]: 'full' } }), key).toThrow(InvalidConfigError);
    }
    expect(() => urlPolicy({ hosts: { 'github.com': 'partial' as UrlRelease } })).toThrow(
      InvalidConfigError,
    );
  });
});

describe('dropCleanPublicUrlSpans', () => {
  it('drops private_url spans matching the allowlist, keeps others', () => {
    const spans: PiiSpan[] = [
      urlSpan('https://python.org/foo', 0),
      urlSpan('https://acme.io/internal', 30),
      { label: 'private_email', start: 60, end: 67, text: 'a@b.com', score: 0.95 },
    ];
    const out = dropCleanPublicUrlSpans(spans, POLICY);
    expect(out).toHaveLength(2);
    expect(out.find((s) => s.text === 'https://python.org/foo')).toBeUndefined();
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
    const out = dropCleanPublicUrlSpans(spans, POLICY);
    expect(out.map((s) => s.start)).toEqual([100, 100]);
  });

  it('drops a README badge span that covers two public URLs', () => {
    const badge = 'https://img.shields.io/travis/foo/bar.svg)](https://travis-ci.org/foo/bar';
    expect(dropCleanPublicUrlSpans([urlSpan(badge, 10)], POLICY)).toEqual([]);
  });

  it('keeps the private URL of a span that joins a public and a private one', () => {
    const joined = 'https://python.org/foo,https://acme.io/internal';
    const out = dropCleanPublicUrlSpans([urlSpan(joined, 5)], POLICY);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({
      label: 'private_url',
      start: 28,
      end: 52,
      text: 'https://acme.io/internal',
    });
  });

  it('keeps the private URL when it comes first', () => {
    const joined = 'https://acme.io/internal)](https://python.org/foo';
    const out = dropCleanPublicUrlSpans([urlSpan(joined, 0)], POLICY);
    expect(out.map((s) => s.text)).toEqual(['https://acme.io/internal)](']);
  });

  it('keeps a multi-URL span whole when none of its URLs is public', () => {
    const span = urlSpan('https://acme.io/a,https://corp.example/b', 0);
    expect(dropCleanPublicUrlSpans([span], POLICY)).toEqual([span]);
  });

  it('keeps a public part that holds another PII span', () => {
    const joined = 'https://python.org/a,AKIAIOSFODNN7EXAMPLE,https://python.org/b';
    const secret = {
      label: 'secret' as const,
      start: 21,
      end: 41,
      text: 'AKIAIOSFODNN7EXAMPLE',
      score: 0.9,
    };
    const out = dropCleanPublicUrlSpans([urlSpan(joined, 0), secret], POLICY);
    expect(out.map((s) => [s.label, s.text])).toEqual([
      ['private_url', 'https://python.org/a,AKIAIOSFODNN7EXAMPLE,'],
      ['secret', 'AKIAIOSFODNN7EXAMPLE'],
    ]);
  });

  it('keeps text the model swept into a public URL span masked', () => {
    // A model span is built from words, so it can cross whitespace.
    const swept = 'https://python.org/a) and Jane Doe notes](https://acme.io/x';
    const out = dropCleanPublicUrlSpans([urlSpan(swept, 0)], POLICY);
    expect(out.map((s) => s.text)).toEqual([') and Jane Doe notes](', 'https://acme.io/x']);
  });

  it('keeps the trailing text of a single public URL span masked', () => {
    const out = dropCleanPublicUrlSpans(
      [urlSpan('https://python.org/foo and the new pin 4821', 0)],
      POLICY,
    );
    expect(out.map((s) => s.text)).toEqual([' and the new pin 4821']);
  });

  it('keeps a private www. URL glued to a public one with a comma', () => {
    const joined = 'https://python.org/a,www.private-host.io/admin,https://python.org/b';
    const inner = { ...urlSpan('www.private-host.io/admin', 21) };
    const out = dropCleanPublicUrlSpans([urlSpan(joined, 0), inner], POLICY);
    expect(out.map((s) => s.text)).toEqual([
      ',www.private-host.io/admin,',
      'www.private-host.io/admin',
    ]);
  });

  it('never releases a URL that carries credentials', () => {
    const span = urlSpan('https://deploy:hunter2@python.org/org/repo.git', 0);
    expect(dropCleanPublicUrlSpans([span], POLICY)).toEqual([span]);
  });

  it('never releases a token with a second URL glued inside it', () => {
    const span = urlSpan('https://python.org/x/www.acme-internal.io', 0);
    expect(dropCleanPublicUrlSpans([span], POLICY)).toEqual([span]);
  });

  it('never judges text before the first scheme as a public URL', () => {
    const span = urlSpan('see:https://python.org/a)](https://python.org/b', 0);
    expect(dropCleanPublicUrlSpans([span], POLICY).map((s) => s.text)).toEqual([
      'see:https://python.org/a)](',
    ]);
  });

  it("keeps the path, query and fragment masked on a 'host' release", () => {
    const hostOnly = urlPolicy({
      hosts: { '*.github.com': 'host', '*.githubusercontent.com': 'host' },
    });
    const out = dropCleanPublicUrlSpans(
      [urlSpan('https://github.com/alice/private-repo', 4)],
      hostOnly,
    );
    expect(out).toEqual([
      { label: 'private_url', start: 22, end: 41, text: '/alice/private-repo', score: 0.95 },
    ]);
    const raw = 'https://raw.githubusercontent.com/a/b/main/x.env';
    expect(dropCleanPublicUrlSpans([urlSpan(raw, 0)], hostOnly).map((s) => s.text)).toEqual([
      '/a/b/main/x.env',
    ]);
    expect(dropCleanPublicUrlSpans([urlSpan('https://github.com/', 0)], hostOnly)).toEqual([]);
  });

  it('never releases a URL whose query carries a credential, on any host', () => {
    for (const u of [
      'https://raw.githubusercontent.com/acme/private/main/.env?token=GHSAT0AAAAAB',
      'https://docs.python.org/3/?api_key=abc123',
      'https://img.shields.io/badge.svg?X-Amz-Signature=abcdef',
      'https://github.com/login/oauth/callback?state=x&code=4f2a9c',
    ]) {
      const span = urlSpan(u, 0);
      expect(dropCleanPublicUrlSpans([span], POLICY), u).toEqual([span]);
    }
  });

  it('passes through when no private_url spans are present', () => {
    const spans: PiiSpan[] = [
      { label: 'private_email', start: 0, end: 7, text: 'a@b.com', score: 0.95 },
    ];
    expect(dropCleanPublicUrlSpans(spans, POLICY)).toEqual(spans);
  });
});
