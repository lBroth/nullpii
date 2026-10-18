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
  // Package registries. Lockfiles (`package-lock.json`, `yarn.lock`,
  // `poetry.lock`) cite a tarball URL per dependency on these hosts —
  // the npm registry serves from `registry.npmjs.org`, not `npmjs.com`.
  'npmjs.com',
  'npmjs.org',
  'yarnpkg.com',
  'pypi.org',
  'pythonhosted.org',
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
  // Standards bodies and licences
  'iso.org',
  'unicode.org',
  'iana.org',
  'apache.org',
  'typescriptlang.org',
  // Project-infrastructure services READMEs link to: status badges,
  // CI, coverage, dependency and funding pages, public package CDNs.
  // Every URL on these hosts describes a public project, never a person.
  'shields.io',
  'badgen.net',
  'fury.io',
  'nodei.co',
  'npm.im',
  'packagequality.com',
  'travis-ci.org',
  'travis-ci.com',
  'circleci.com',
  'appveyor.com',
  'coveralls.io',
  'codecov.io',
  'david-dm.org',
  'snyk.io',
  'tidelift.com',
  'opencollective.com',
  'jsdelivr.com',
  'jsdelivr.net',
  'unpkg.com',
  // Raw and avatar content of public GitHub repositories, consistent
  // with `github.com` above.
  'githubusercontent.com',
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
  const dropped: PiiSpan[] = [];
  const kept: PiiSpan[] = [];
  for (const s of spans) {
    const parts = splitAtSchemes(s);
    const cuts = parts.map((p) => publicPrefixLength(p, spans));
    if (cuts.every((n) => n === 0)) {
      kept.push(s);
      continue;
    }
    parts.forEach((p, i) => {
      const n = cuts[i] ?? 0;
      if (n > 0) dropped.push(slice(p, 0, n));
      if (n < p.text.length) kept.push(slice(p, n, p.text.length));
    });
  }
  if (dropped.length === 0) return [...spans];
  // A `private_url` span inside a dropped range is a fragment of that same
  // public URL (the model often emits `https:/` or a path piece next to
  // the recognizer's full match). Containment dedupe used to remove it;
  // with its parent gone it would survive and split the URL. A dropped
  // range is one URL token that contains no other scheme or `www.`, so a
  // nested fragment cannot be another URL.
  const inside = (s: PiiSpan) => dropped.some((d) => s.start >= d.start && s.end <= d.end);
  return kept.filter((s) => !(s.label === 'private_url' && inside(s)));
}

/** The URL at the start of a `private_url` span or part: a scheme or
 * `www.`, then characters up to the first whitespace, quote, bracket,
 * comma or semicolon. A span the model drew across text, or across a list
 * of URLs, is cut there, so whatever follows is judged on its own. */
const URL_TOKEN = /^(?:https?:\/\/|www\.)[^\s<>"'`()[\]{}|\\^,;]+/i;

/** Text that may follow a public URL token and still be dropped with it:
 * whitespace and punctuation only, such as the `)](` between two links of
 * a README badge. Anything with a letter or digit stays masked. */
const SEPARATOR_ONLY = /^[\s)\](\[,;:.!?'"`<>]*$/;

/** The scheme or `www.` a URL token starts with. */
const URL_PREFIX = /^(?:https?:\/\/|www\.)/i;

/** A second URL inside a token's body (the token minus `URL_PREFIX`): any
 * scheme, or a `www.` that is not the body's own host. */
const NESTED_URL_START = /[a-z][a-z0-9+.-]*:\/\/|.www\./i;

/**
 * How many leading characters of `part` may be unmasked: 0 when none.
 *
 * Only a public URL token at the very start qualifies (see `URL_TOKEN`),
 * and only when it holds no credentials and no second URL, and no other
 * PII span touches the part. The rest of the part goes with it only when
 * it is separator punctuation; otherwise the rest stays masked. This is the fail-safe
 * rule of the docstring above, applied to the token instead of the whole
 * span: text that the model or the greedy recognizer swept into a URL
 * span is never released on the strength of the URL's host.
 */
function publicPrefixLength(part: PiiSpan, spans: readonly PiiSpan[]): number {
  if (part.label !== 'private_url') return 0;
  const token = URL_TOKEN.exec(part.text)?.[0];
  if (token === undefined || NESTED_URL_START.test(token.replace(URL_PREFIX, ''))) return 0;
  if (!isPublicUrl(token) || hasCredentials(token)) return 0;
  const rest = part.text.slice(token.length);
  const n = SEPARATOR_ONLY.test(rest) ? part.text.length : token.length;
  // Any other PII span touching the part keeps all of it masked, URL
  // included: a reference URL that embeds anything identifying is never
  // released, not even its public prefix.
  const holdsPii = spans.some(
    (t) => t !== part && t.label !== 'private_url' && t.start < part.end && t.end > part.start,
  );
  return holdsPii ? 0 : n;
}

/** `true` when the URL carries a user name or password (`user:pass@host`). */
function hasCredentials(token: string): boolean {
  try {
    const url = new URL(/^www\./i.test(token) ? `http://${token}` : token);
    return url.username !== '' || url.password !== '';
  } catch {
    return true;
  }
}

/** The sub-span of `s` from character `from` to `to` of its text. */
function slice(s: PiiSpan, from: number, to: number): PiiSpan {
  return { ...s, start: s.start + from, end: s.start + to, text: s.text.slice(from, to) };
}

/**
 * Splits a `private_url` span that covers several URLs into one part per
 * URL, cut where each later scheme starts. The model often emits a single
 * span across a README badge, `[![ci](https://img.shields.io/…)](https://travis-ci.org/…)`,
 * and {@link isPublicUrl} refuses to judge a span with two schemes. Each
 * part is judged on its own (`publicPrefixLength`): a public URL can be
 * dropped while a private one next to it stays masked. Text before the
 * first scheme stays with the first part, which is then judged public only
 * if it starts with a URL itself. Any other span is returned as is.
 */
function splitAtSchemes(s: PiiSpan): PiiSpan[] {
  if (s.label !== 'private_url') return [s];
  const starts = [...s.text.matchAll(SCHEME_PATTERN)].map((m) => m.index);
  if (starts.length < 2) return [s];
  const ends = [...starts.slice(1), s.text.length];
  return [0, ...starts.slice(1)].map((from, i) => slice(s, from, ends[i] ?? s.text.length));
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
