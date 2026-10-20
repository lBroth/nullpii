// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import type { PiiSpan } from '../src/types/index.js';
import { dropCleanPublicUrlSpans, urlPolicy, urlRelease } from '../src/url-filter.js';

const POLICY = urlPolicy();

/** `core:url` is greedy (`[^\s<>"]+`), so PII glued to a URL without
 * whitespace lands inside the URL span. Dropping such a span emits the
 * nested secret as plaintext — verified end-to-end against the real
 * model before this guard existed:
 *
 *   x https://python.org/a,AKIAIOSFODNN7EXAMPLE y
 *     main            → x {{PII_PRIVATE_URL_0}} y
 *     allowlist, pre  → x https://python.org/a,AKIAIOSFODNN7EXAMPLE y   ← leak
 *     allowlist, post → x {{PII_PRIVATE_URL_0}} y
 */
const span = (label: string, start: number, end: number, text: string): PiiSpan =>
  ({ label, start, end, text, score: 0.95 }) as PiiSpan;

describe('dropCleanPublicUrlSpans', () => {
  it('drops a clean allowlisted URL — the feature this exists for', () => {
    const url = span('private_url', 5, 41, 'https://python.org/acme/infra-gitops');
    expect(dropCleanPublicUrlSpans([url], POLICY)).toEqual([]);
  });

  it('keeps an allowlisted URL that carries a nested secret', () => {
    const url = span('private_url', 2, 43, 'https://python.org/a,AKIAIOSFODNN7EXAMPLE');
    const key = span('secret', 23, 43, 'AKIAIOSFODNN7EXAMPLE');
    // Both survive the filter; cross-label dedupe then collapses them to
    // the outer URL span, so the whole URL is redacted rather than the
    // key being emitted in the clear.
    expect(dropCleanPublicUrlSpans([url, key], POLICY)).toHaveLength(2);
  });

  it('keeps an allowlisted URL carrying nested credentials in userinfo', () => {
    const text = 'https://user:ghp_ABCDEF@python.org/org/repo.git';
    const url = span('private_url', 0, text.length, text);
    const pat = span('secret', 13, 23, 'ghp_ABCDEF');
    expect(dropCleanPublicUrlSpans([url, pat], POLICY)).toHaveLength(2);
  });

  it('never touches spans of another label', () => {
    const email = span('private_email', 0, 13, 'a@example.com');
    expect(dropCleanPublicUrlSpans([email], POLICY)).toEqual([email]);
  });

  it('keeps a non-allowlisted URL even when clean', () => {
    const url = span('private_url', 0, 29, 'https://intranet.acme.local/x');
    expect(dropCleanPublicUrlSpans([url], POLICY)).toEqual([url]);
  });

  it('ignores a nested span of the same label — only foreign PII counts', () => {
    // The nested url fragment does not block the drop, and it goes with
    // its parent: keeping it would mask `python.org` inside a URL the
    // allowlist just declared public, shredding the reference.
    const url = span('private_url', 0, 36, 'https://python.org/acme/infra-gitops');
    const inner = span('private_url', 8, 18, 'python.org');
    expect(dropCleanPublicUrlSpans([url, inner], POLICY)).toEqual([]);
  });
});

describe('urlRelease — concatenated URLs', () => {
  it('refuses to allowlist a span carrying more than one scheme', () => {
    // One greedy span covers both; judging it by the first host would
    // allowlist the internal one on github.com's authority.
    expect(urlRelease('https://github.com/foo,https://acme.io/internal', POLICY)).toBe('mask');
    expect(urlRelease('https://github.com/x?next=https://acme.io/internal', POLICY)).toBe('mask');
  });

  it('still judges a single URL', () => {
    expect(urlRelease('https://github.com/acme/infra-gitops', POLICY)).toBe('host');
  });
});

describe('urlRelease — host extraction', () => {
  it('judges a non-default port by its hostname', () => {
    expect(urlRelease('https://github.com:8443/foo', POLICY)).toBe('host');
  });

  it('still rejects the near-miss hosts', () => {
    for (const u of [
      'https://evil-github.com/x',
      'https://github.com.attacker.net/x',
      'https://acme-corp.github.io/private',
    ]) {
      expect(urlRelease(u, POLICY), u).toBe('mask');
    }
  });
});
