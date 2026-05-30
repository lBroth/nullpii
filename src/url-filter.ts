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

/** Drop `private_url` spans whose host is in the public-URL allowlist. */
export function dropPublicUrlSpans(spans: readonly PiiSpan[]): PiiSpan[] {
  return spans.filter((s) => s.label !== 'private_url' || !isPublicUrl(s.text));
}

function extractHost(urlText: string): string | null {
  // The recognizer pattern allows `https?://` and `www.` prefixes. Try
  // both shapes — URL constructor needs a scheme.
  try {
    if (/^https?:\/\//i.test(urlText)) {
      return new URL(urlText).host;
    }
    if (/^www\./i.test(urlText)) {
      return new URL(`http://${urlText}`).host;
    }
  } catch {
    return null;
  }
  return null;
}
