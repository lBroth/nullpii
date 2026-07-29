// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import type { PiiSpan } from '../src/types/index.js';
import { dropCleanPublicUrlSpans, isPublicUrl } from '../src/url-filter.js';

/** `core:url` is greedy (`[^\s<>"]+`), so PII glued to a URL without
 * whitespace lands inside the URL span. Dropping such a span emits the
 * nested secret as plaintext — verified end-to-end against the real
 * model before this guard existed:
 *
 *   x https://github.com/a,AKIAIOSFODNN7EXAMPLE y
 *     main            → x {{PII_PRIVATE_URL_0}} y
 *     allowlist, pre  → x https://github.com/a,AKIAIOSFODNN7EXAMPLE y   ← leak
 *     allowlist, post → x {{PII_PRIVATE_URL_0}} y
 */
const span = (label: string, start: number, end: number, text: string): PiiSpan =>
  ({ label, start, end, text, score: 0.95 }) as PiiSpan;

describe('dropCleanPublicUrlSpans', () => {
  it('drops a clean allowlisted URL — the feature this exists for', () => {
    const url = span('private_url', 5, 41, 'https://github.com/acme/infra-gitops');
    expect(dropCleanPublicUrlSpans([url])).toEqual([]);
  });

  it('keeps an allowlisted URL that carries a nested secret', () => {
    const url = span('private_url', 2, 43, 'https://github.com/a,AKIAIOSFODNN7EXAMPLE');
    const key = span('secret', 23, 43, 'AKIAIOSFODNN7EXAMPLE');
    // Both survive the filter; cross-label dedupe then collapses them to
    // the outer URL span, so the whole URL is redacted rather than the
    // key being emitted in the clear.
    expect(dropCleanPublicUrlSpans([url, key])).toHaveLength(2);
  });

  it('keeps an allowlisted URL carrying nested credentials in userinfo', () => {
    const text = 'https://user:ghp_ABCDEF@github.com/org/repo.git';
    const url = span('private_url', 0, text.length, text);
    const pat = span('secret', 13, 23, 'ghp_ABCDEF');
    expect(dropCleanPublicUrlSpans([url, pat])).toHaveLength(2);
  });

  it('never touches spans of another label', () => {
    const email = span('private_email', 0, 13, 'a@example.com');
    expect(dropCleanPublicUrlSpans([email])).toEqual([email]);
  });

  it('keeps a non-allowlisted URL even when clean', () => {
    const url = span('private_url', 0, 29, 'https://intranet.acme.local/x');
    expect(dropCleanPublicUrlSpans([url])).toEqual([url]);
  });

  it('ignores a nested span of the same label — only foreign PII counts', () => {
    const url = span('private_url', 0, 36, 'https://github.com/acme/infra-gitops');
    const inner = span('private_url', 8, 18, 'github.com');
    expect(dropCleanPublicUrlSpans([url, inner])).toEqual([inner]);
  });
});

describe('isPublicUrl — concatenated URLs', () => {
  it('refuses to allowlist a span carrying more than one scheme', () => {
    // One greedy span covers both; judging it by the first host would
    // allowlist the internal one on github.com's authority.
    expect(isPublicUrl('https://github.com/foo,https://acme.io/internal')).toBe(false);
    expect(isPublicUrl('https://github.com/x?next=https://acme.io/internal')).toBe(false);
  });

  it('still allowlists a single URL', () => {
    expect(isPublicUrl('https://github.com/acme/infra-gitops')).toBe(true);
  });
});

describe('isPublicUrl — host extraction', () => {
  it('allowlists a non-default port (hostname, not host)', () => {
    expect(isPublicUrl('https://github.com:8443/foo')).toBe(true);
  });

  it('still rejects the near-miss hosts', () => {
    for (const u of [
      'https://evil-github.com/x',
      'https://github.com.attacker.net/x',
      'https://acme-corp.github.io/private',
    ]) {
      expect(isPublicUrl(u), u).toBe(false);
    }
  });
});
