// SPDX-License-Identifier: Apache-2.0

import { MAX_INPUT_BYTES } from './defaults.js';
import type { PiiSpan, Recognizer } from './types/index.js';

/**
 * Run every recognizer against `text`, return non-overlapping spans.
 * Used as a regex post-pass after the ML detector. ML spans take priority
 * on overlap; recognizer spans only fill gaps.
 *
 * Refuses inputs above `MAX_INPUT_BYTES` (1 MB): unbounded `{N,}`
 * quantifiers in upstream secret patterns are quadratic on adversarial
 * padding, well above any realistic LLM prompt.
 */
export function runRecognizers(
  text: string,
  recognizers: readonly Recognizer[],
  existing: readonly PiiSpan[],
): PiiSpan[] {
  if (text.length > MAX_INPUT_BYTES) {
    return [];
  }
  const out: PiiSpan[] = [];
  for (const r of recognizers) {
    out.push(...matchOne(text, r, existing));
  }
  return filterNeverPii(out, text);
}

/**
 * partial port: drop spans that match well-known never-PII
 * patterns. Reserved IP ranges, fictional NANP 555-01XX phones, RFC
 * 6761 reserved domains. Mirrors `_is_never_pii` in
 * `packages/eval/src/nullpii_eval/adapters.py`. Full preprocessor port
 * (`_normalize_for_detection`) is tracked as a separate roadmap item.
 */
function filterNeverPii(spans: readonly PiiSpan[], text: string): PiiSpan[] {
  const out: PiiSpan[] = [];
  for (const s of spans) {
    const value = text.slice(s.start, s.end);
    if (isNeverPii(value, s.label)) continue;
    out.push(s);
  }
  return out;
}

const NANP_FICTIONAL_555 = /^\+?1?[\s\-.()]*[2-9]\d{2}[\s\-.()]*555[\s\-.]*0[01]\d{2}$/;
/** Private RFC1918 IPv4: 10/8, 172.16/12, 192.168/16. */
const RFC1918_PRIVATE = /^(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)/;
/** Loopback IPv4: 127.0.0.0/8. */
const IPV4_LOOPBACK = /^127\./;
/** Link-local IPv4: 169.254.0.0/16. */
const IPV4_LINK_LOCAL = /^169\.254\./;
/** Multicast / class-D IPv4: 224.0.0.0/4 (224–239). */
const IPV4_MULTICAST = /^(?:22[4-9]|23\d)\./;
/** RFC5737 documentation IPv4: 192.0.2/24, 198.51.100/24, 203.0.113/24. */
const IPV4_RFC5737_DOCS = /^(?:192\.0\.2\.|198\.51\.100\.|203\.0\.113\.)/;
/** RFC3849 documentation IPv6 prefix `2001:db8::/32`. */
const IPV6_DOCS = /^2001:0?db8:/i;
/** IPv6 loopback `::1` (also full form `0000:...:0001`). */
const IPV6_LOOPBACK = /^(?:::1|0{1,4}(?::0{1,4}){0,6}:0{0,3}1)$/i;
/** IPv6 link-local `fe80::/10`. */
const IPV6_LINK_LOCAL = /^fe[89ab][0-9a-f]?:/i;
const RFC6761_RESERVED = /(?:^|[@.])(?:example\.(?:com|net|org)|test|invalid|localhost|local)$/i;
const NULL_UUID = /^0{8}-0{4}-0{4}-0{4}-0{12}$/;
const ZERO_MAC = /^(?:[0:]{17}|(?:00[:-]){5}00)$/;

function isNeverPii(value: string, label: string): boolean {
  if (label === 'private_phone' && NANP_FICTIONAL_555.test(value)) return true;
  if (label === 'private_ip') {
    if (
      RFC1918_PRIVATE.test(value) ||
      IPV4_LOOPBACK.test(value) ||
      IPV4_LINK_LOCAL.test(value) ||
      IPV4_MULTICAST.test(value) ||
      IPV4_RFC5737_DOCS.test(value)
    ) {
      return true;
    }
    if (IPV6_DOCS.test(value) || IPV6_LOOPBACK.test(value) || IPV6_LINK_LOCAL.test(value)) {
      return true;
    }
    if (ZERO_MAC.test(value)) return true;
  }
  if (label === 'account_number' && NULL_UUID.test(value)) return true;
  if ((label === 'private_url' || label === 'private_email') && RFC6761_RESERVED.test(value)) {
    return true;
  }
  return false;
}

function matchOne(text: string, recognizer: Recognizer, existing: readonly PiiSpan[]): PiiSpan[] {
  const re = ensureGlobal(recognizer.pattern);
  const out: PiiSpan[] = [];
  let m: RegExpExecArray | null = re.exec(text);
  while (m !== null) {
    const start = m.index;
    const end = start + m[0].length;
    // High-confidence recognizers (≥ 0.9 — secret patterns, IBAN with
    // mod-97 validator, Luhn-validated CCs) always emit; cross-label
    // overlaps with ML output are reconciled later by IoU dedupe in
    // `nullpii.ts`. Lower-confidence recognizers still defer to ML on
    // overlap to avoid noisy double-counting on prose.
    const overrides = recognizer.confidence >= 0.9;
    if ((overrides || !overlaps(start, end, existing)) && passesValidate(m[0], recognizer)) {
      out.push({
        label: recognizer.label,
        start,
        end,
        score: recognizer.confidence,
        text: m[0],
      });
    }
    m = re.exec(text);
  }
  return out;
}

/** Cache of `g`-flagged copies of every recognizer pattern seen so far.
 *
 * `runRecognizers` runs ~50 patterns per `sanitize()` call, and previously
 * allocated a fresh `RegExp` for every pattern on every call. The
 * `WeakMap` keys on the caller-supplied pattern so user-added
 * recognizers benefit automatically; entries are GC'd when the
 * recognizer is released.
 *
 * Returned regex is owned by this module — `lastIndex` is reset to 0
 * on every lookup. Mutating it externally is a bug. Within `matchOne`
 * the regex is driven via synchronous `exec()` and never crosses an
 * `await` boundary, so single-threaded JS guarantees no concurrent
 * mutation in practice. */
const GLOBAL_REGEX_CACHE = new WeakMap<RegExp, RegExp>();

function ensureGlobal(re: RegExp): RegExp {
  let cached = GLOBAL_REGEX_CACHE.get(re);
  if (cached === undefined) {
    cached = re.flags.includes('g')
      ? new RegExp(re.source, re.flags)
      : new RegExp(re.source, `${re.flags}g`);
    GLOBAL_REGEX_CACHE.set(re, cached);
  }
  cached.lastIndex = 0;
  return cached;
}

function overlaps(start: number, end: number, spans: readonly PiiSpan[]): boolean {
  for (const s of spans) {
    if (start < s.end && end > s.start) return true;
  }
  return false;
}

function passesValidate(match: string, recognizer: Recognizer): boolean {
  return recognizer.validate === undefined || recognizer.validate(match);
}
