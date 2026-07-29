// SPDX-License-Identifier: Apache-2.0

import type { PiiSpan } from './types/index.js';

/**
 * Hosts whose URLs are public reference / documentation surfaces and
 * are never PII on their own. Matching `private_url` spans are dropped
 * from the final span set so that, e.g., a link to
 * `https://github.com/anthropics/claude-code/issues` in a system prompt
 * stays verbatim instead of becoming `{{PII_PRIVATE_URL_*}}`.
 *
 * Match is on the URL's host (case-insensitive). A leading `www.` is
 * stripped before lookup. Subdomains of an allowlisted host also match
 * (`docs.python.org` is covered by `python.org`).
 */
export const PUBLIC_URL_HOSTS: ReadonlySet<string> = new Set([
  // Source hosting
  'github.com',
  'gitlab.com',
  'bitbucket.org',
  'codeberg.org',
  'sourceforge.net',
  // Package registries
  'npmjs.com',
  'pypi.org',
  'crates.io',
  'rubygems.org',
  'packagist.org',
  'nuget.org',
  'maven.org',
  // Docs / encyclopedias
  'wikipedia.org',
  'wikimedia.org',
  'mozilla.org',
  'developer.mozilla.org',
  'w3.org',
  'whatwg.org',
  'rfc-editor.org',
  'ietf.org',
  // AI / ML vendors (public marketing / docs surfaces)
  'anthropic.com',
  'openai.com',
  'huggingface.co',
  'deepmind.com',
  'mistral.ai',
  // Language / runtime official sites
  'python.org',
  'nodejs.org',
  'rust-lang.org',
  'golang.org',
  'go.dev',
  'oracle.com',
  'kotlinlang.org',
  'scala-lang.org',
  // Cloud vendor docs (the marketing top-level — not customer subdomains)
  'aws.amazon.com',
  'cloud.google.com',
  'azure.microsoft.com',
  'docs.microsoft.com',
  'learn.microsoft.com',
  // Q&A
  'stackoverflow.com',
  'stackexchange.com',
  'serverfault.com',
  'superuser.com',
  // Standards bodies
  'iso.org',
  'unicode.org',
]);

/**
 * Returns `true` when `urlText` (a substring matched by the URL
 * recognizer) targets one of the {@link PUBLIC_URL_HOSTS}, OR a
 * subdomain of one. Returns `false` on malformed input — over-redact
 * rather than under-redact.
 */
export function isPublicUrl(urlText: string): boolean {
  // `core:url` is greedy (`[^\s<>"]+`) and does not stop at `,` or `#`,
  // so a single span can cover several concatenated URLs:
  // `https://github.com/foo,https://acme.io/internal`. `extractHost`
  // only ever reads the first one, which would allowlist the whole
  // blob on the strength of a host the later URLs do not share. Refuse
  // to judge a span carrying more than one scheme — over-redact.
  if ((urlText.match(SCHEME_PATTERN) ?? []).length > 1) return false;
  const host = extractHost(urlText);
  if (host === null) return false;
  const lower = host.toLowerCase();
  const stripped = lower.startsWith('www.') ? lower.slice(4) : lower;
  if (PUBLIC_URL_HOSTS.has(stripped)) return true;
  // Subdomain match: walk parents (`docs.python.org` → `python.org`).
  let cursor = stripped;
  while (cursor.includes('.')) {
    const dot = cursor.indexOf('.');
    cursor = cursor.slice(dot + 1);
    if (PUBLIC_URL_HOSTS.has(cursor)) return true;
  }
  return false;
}

/** Matches every URL scheme occurrence in a span — see {@link isPublicUrl}. */
const SCHEME_PATTERN = /https?:\/\//gi;

/**
 * Drop `private_url` spans that target an allowlisted host **and carry
 * no other PII inside them**.
 *
 * The containment condition is the security-critical half. `core:url`
 * matches `[^\s<>"]+`, so any PII glued to a URL without whitespace is
 * swallowed into the URL span — and `removeContainedSpans` then deletes
 * the inner `secret` / `private_email` span regardless of its score.
 * Dropping the surviving URL span would therefore emit the nested
 * secret as plaintext:
 *
 * ```
 * https://github.com/a,AKIAIOSFODNN7EXAMPLE     → AWS key in the clear
 * https://user:ghp_…@github.com/org/repo.git    → GitHub PAT in the clear
 * https://anthropic.com/x?key=sk-ant-api03-…    → Anthropic key in the clear
 * ```
 *
 * A 20-character allowlisted prefix would otherwise disable redaction
 * for an arbitrary secret. So the rule is fail-safe: a reference URL
 * that embeds anything identifying reverts to whole-URL redaction, and
 * only a genuinely clean reference URL survives into the output.
 *
 * Must run **before** cross-label dedupe, while the nested spans still
 * exist to be seen.
 *
 * @param spans - candidate spans, ML and recognizer, pre-dedupe
 */
export function dropCleanPublicUrlSpans(spans: readonly PiiSpan[]): PiiSpan[] {
  return spans.filter((s) => {
    if (s.label !== 'private_url' || !isPublicUrl(s.text)) return true;
    return spans.some(
      (t) => t !== s && t.label !== 'private_url' && t.start >= s.start && t.end <= s.end,
    );
  });
}

function extractHost(urlText: string): string | null {
  // The recognizer pattern allows `https?://` and `www.` prefixes. Try
  // both shapes — URL constructor needs a scheme. `.hostname` not
  // `.host`: the latter keeps a non-default port (`github.com:8443`),
  // which misses the set lookup and then misses the parent walk too
  // (`com:8443`), silently disabling the allowlist on any such URL.
  try {
    if (/^https?:\/\//i.test(urlText)) {
      return new URL(urlText).hostname;
    }
    if (/^www\./i.test(urlText)) {
      return new URL(`http://${urlText}`).hostname;
    }
  } catch {
    return null;
  }
  return null;
}
