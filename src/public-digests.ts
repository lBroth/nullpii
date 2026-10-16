// SPDX-License-Identifier: Apache-2.0

/**
 * Subresource-integrity digests: `sha512-<base64>` and its siblings, as
 * lockfiles (`package-lock.json`, `yarn.lock`) and `<script integrity>`
 * attributes carry them. Each is the hash of a published artifact, so it
 * identifies a package tarball, not a person or a credential. The model
 * reads the base64 body as `secret` or `account_number` and masks pieces
 * of it, one per dependency.
 *
 * The prefix plus at least 20 base64 characters is the SRI grammar
 * (W3C Subresource Integrity, `hash-algo "-" base64-value`); requiring
 * the algorithm prefix keeps free-standing base64 (which can be a real
 * secret) out of scope.
 */
const SRI_DIGEST = /\b(?:sha1|sha256|sha384|sha512)-[A-Za-z0-9+/]{20,}={0,2}/g;

/**
 * Drop spans that lie entirely inside a subresource-integrity digest.
 * A span that extends past the digest is kept: it may carry something
 * the digest does not explain.
 *
 * @param spans - candidate spans, ML and recognizer, pre-dedupe
 * @param text - the text the span offsets index into
 */
export function dropSpansInsidePublicDigests<T extends { start: number; end: number }>(
  spans: T[],
  text: string,
): T[] {
  const digests = [...text.matchAll(SRI_DIGEST)].map((m) => [m.index, m.index + m[0].length]);
  if (digests.length === 0) return spans;
  return spans.filter(
    (s) =>
      !digests.some(([a, b]) => a !== undefined && b !== undefined && s.start >= a && s.end <= b),
  );
}
