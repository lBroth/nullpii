// SPDX-License-Identifier: Apache-2.0

import { DEFAULT_URL_RELEASES } from './defaults.js';
import { InvalidConfigError } from './errors.js';
import type { PiiSpan, UrlAllowlistConfig, UrlRelease } from './types/index.js';

/** How much of a clean URL on a host stays readable (see `UrlRelease`). */
export type UrlPolicy = (host: string) => UrlRelease;

/** A policy key: a lowercase host, or `*.` and a domain. */
const HOST_KEY = /^(?:\*\.)?(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z0-9-]{2,63}$/;
const RELEASES: ReadonlySet<string> = new Set<UrlRelease>(['full', 'host', 'mask']);

/**
 * The URL policy for `config`: the built-in {@link DEFAULT_URL_RELEASES},
 * with `config.hosts` merged over it (or alone, with `replaceDefaults`).
 * Throws {@link InvalidConfigError} on a malformed host key or an unknown
 * release, so a typo never silently releases or masks a host.
 */
export function urlPolicy(config: UrlAllowlistConfig = {}): UrlPolicy {
  const hosts = config.hosts ?? {};
  for (const [key, release] of Object.entries(hosts)) {
    if (!HOST_KEY.test(key)) {
      throw new InvalidConfigError(
        `urlAllowlist.hosts key ${JSON.stringify(key)} is not a lowercase host or *.domain`,
      );
    }
    if (!RELEASES.has(release)) {
      throw new InvalidConfigError(
        `urlAllowlist.hosts[${JSON.stringify(key)}] must be 'full', 'host' or 'mask', got ${JSON.stringify(release)}`,
      );
    }
  }
  const table = new Map(
    Object.entries(config.replaceDefaults === true ? hosts : { ...DEFAULT_URL_RELEASES, ...hosts }),
  );
  return (host) => releaseFor(table, host);
}

/** The most specific entry for `host`: the exact host, then `*.` keys
 * from the host itself up through its parent domains. A leading `www.`
 * is ignored. No entry: `'mask'`. */
function releaseFor(table: ReadonlyMap<string, UrlRelease>, host: string): UrlRelease {
  const lower = host.toLowerCase();
  const bare = lower.startsWith('www.') ? lower.slice(4) : lower;
  const exact = table.get(bare);
  if (exact !== undefined) return exact;
  for (let domain = bare; domain.includes('.'); domain = domain.slice(domain.indexOf('.') + 1)) {
    const wildcard = table.get(`*.${domain}`);
    if (wildcard !== undefined) return wildcard;
  }
  return 'mask';
}

/**
 * How much of `urlText` (a substring matched by the URL recognizer) the
 * policy releases. `'mask'` on malformed input and on a span carrying
 * more than one scheme — over-redact rather than under-redact.
 */
export function urlRelease(urlText: string, policy: UrlPolicy): UrlRelease {
  // `core:url` is greedy (`[^\s<>"]+`) and does not stop at `,` or `#`,
  // so a single span can cover several concatenated URLs:
  // `https://github.com/foo,https://acme.io/internal`. `extractHost`
  // only ever reads the first one, which would release the whole blob
  // on the strength of a host the later URLs do not share.
  if ((urlText.match(SCHEME_PATTERN) ?? []).length > 1) return 'mask';
  const host = extractHost(urlText);
  return host === null ? 'mask' : policy(host);
}

/** Matches every URL scheme occurrence in a span — see {@link urlRelease}. */
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
 * @param policy - how much of a clean URL on each host is released
 */
export function dropCleanPublicUrlSpans(spans: readonly PiiSpan[], policy: UrlPolicy): PiiSpan[] {
  const dropped: PiiSpan[] = [];
  const kept: PiiSpan[] = [];
  for (const s of spans) {
    const parts = splitAtSchemes(s);
    const cuts = parts.map((p) => publicPrefixLength(p, spans, policy));
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

/** A query or fragment parameter that carries a credential: access
 * tokens of raw-content and signed links (`?token=`, `X-Amz-Signature=`,
 * `sig=`), API keys and passwords. Such a URL is never released, on any
 * host, even when no recognizer matched the value. */
const CREDENTIAL_PARAM =
  /[?&#;](?:access[_-]?token|auth[_-]?token|id[_-]?token|token|api[_-]?key|apikey|key|secret|client[_-]?secret|password|passwd|pwd|sig|signature|x-amz-signature|x-amz-credential|x-goog-signature|x-goog-credential|code)=/i;

/** A URL token's scheme (or `www.`) and host, up to its path, query or fragment. */
const URL_ORIGIN = /^(?:https?:\/\/|www\.)[^/?#]*/i;

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
function publicPrefixLength(part: PiiSpan, spans: readonly PiiSpan[], policy: UrlPolicy): number {
  if (part.label !== 'private_url') return 0;
  const token = URL_TOKEN.exec(part.text)?.[0];
  if (token === undefined || NESTED_URL_START.test(token.replace(URL_PREFIX, ''))) return 0;
  const release = urlRelease(token, policy);
  if (release === 'mask' || hasCredentials(token) || CREDENTIAL_PARAM.test(token)) return 0;
  const origin = URL_ORIGIN.exec(token)?.[0].length ?? token.length;
  const rest = part.text.slice(token.length);
  // A `'host'` release keeps the path, query and fragment masked, unless
  // there is none (a bare `https://github.com/`).
  const pathless = token.length - origin <= 1;
  let n: number;
  if (release === 'host' && !pathless) n = origin;
  else n = SEPARATOR_ONLY.test(rest) ? part.text.length : token.length;
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
 * and {@link urlRelease} refuses to judge a span with two schemes. Each
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
