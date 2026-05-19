// SPDX-License-Identifier: Apache-2.0

import { MAX_INPUT_BYTES } from './defaults.js';
import type { PiiSpan, Recognizer } from './types/index.js';

/** Score assigned to a recognizer match whose `validate()` returned true.
 *
 * The motivation is correctness, not confidence calibration: structural
 * checksums (mod-97 for IBAN, Luhn for cards, base58check for BTC, the
 * CF / CPF letter-weighted checks) verify the candidate satisfies a
 * deterministic, well-defined format. Such matches are stronger
 * evidence than any ML softmax, including the ~0.99998 ceiling we
 * routinely see from the GLiNER head. Sitting at this value
 * lets cross-label IoU dedupe (`acrossLabels: true` in
 * `dedupeOverlappingSpans`) pick the structurally-correct label rather
 * than an ML mislabel (e.g. spaced IBAN tagged `private_address`
 * 0.9999). Stays strictly below `BASE64_SCORE` (0.99999) so a base64-
 * wrapped recognizer hit can still override a validator-passing
 * surface match if needed. */
export const VALIDATED_RECOGNIZER_SCORE = 0.99998;

/**
 * Run every recognizer against `text`, return non-overlapping spans.
 * Used as a regex post-pass after the ML detector. ML spans take priority
 * on overlap; recognizer spans only fill gaps.
 *
 * Refuses inputs above `MAX_INPUT_BYTES` (1 MB): unbounded `{N,}`
 * quantifiers in upstream secret patterns are quadratic on adversarial
 * padding, well above any realistic LLM prompt.
 *
 * Two scan paths:
 *
 *  - **Fast path** for recognizers whose pattern begins with a literal
 *    prefix (`\b<literal>…`) ≥ 3 chars — most secret-token patterns
 *    (AKIA, ghp_, sk-ant-, AIza, glpat-, npm_, hf_, …). A single
 *    `String.prototype.indexOf` per prefix finds all candidate
 *    positions; the full regex is only re-run with the sticky flag at
 *    each candidate. V8's indexOf is heavily optimised — much cheaper
 *    than 50 separate regex passes over the whole input.
 *
 *  - **Slow path** unchanged for patterns without an extractable
 *    literal prefix (alternations, character-class starts, structural
 *    patterns like IBAN / Luhn / IPv4 / PEM).
 *
 * Output is identical to the slow-path-only implementation; behaviour
 * verified by the equivalence test in `test/recognizers.test.ts`.
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
  const { fast, slow } = partitionRecognizers(recognizers);
  if (fast.size > 0) {
    out.push(...matchAnchored(text, fast, existing));
  }
  for (const r of slow) {
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
  }
  if (label === 'private_mac' && ZERO_MAC.test(value)) return true;
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
      // Validator-passing matches use VALIDATED_RECOGNIZER_SCORE so
      // cross-label dedupe picks the structurally-correct label over ML
      // mislabels.
      const score =
        recognizer.validate !== undefined ? VALIDATED_RECOGNIZER_SCORE : recognizer.confidence;
      out.push({
        label: recognizer.label,
        start,
        end,
        score,
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

// ─── Fast-path: literal-prefix scan ───────────────────────────────

/** Extract the literal-prefix anchor from a recognizer regex source if
 * it starts with `\b<literal>` where literal is ≥ 3 ASCII identifier
 * chars. Returns null for alternation-prefixed (`\b(?:A|B)…`),
 * character-class-start (`\b[A-Z]…`), or non-anchored patterns. */
const LITERAL_PREFIX_RE = /^\\b([A-Za-z0-9_-]{3,})/;
function extractLiteralPrefix(re: RegExp): string | null {
  const m = LITERAL_PREFIX_RE.exec(re.source);
  return m && typeof m[1] === 'string' ? m[1] : null;
}

/** Memo of recognizer → literal prefix (or `null` for slow-path).
 * Keyed by the user-supplied `RegExp` — WeakMap so user-added recognizer
 * patterns are GC'd cleanly. */
const PREFIX_CACHE = new WeakMap<RegExp, string | null>();
function getLiteralPrefix(re: RegExp): string | null {
  const cached = PREFIX_CACHE.get(re);
  if (cached !== undefined) return cached;
  const prefix = extractLiteralPrefix(re);
  PREFIX_CACHE.set(re, prefix);
  return prefix;
}

interface PartitionedRecognizers {
  /** prefix → recognizers that share that prefix (typically 1). */
  readonly fast: Map<string, Recognizer[]>;
  /** recognizers without an extractable literal prefix (alternation,
   * char-class start, etc.) — keep on the slow path. */
  readonly slow: readonly Recognizer[];
}

function partitionRecognizers(recognizers: readonly Recognizer[]): PartitionedRecognizers {
  const fast = new Map<string, Recognizer[]>();
  const slow: Recognizer[] = [];
  for (const r of recognizers) {
    const prefix = getLiteralPrefix(r.pattern);
    if (prefix === null) {
      slow.push(r);
      continue;
    }
    const bucket = fast.get(prefix);
    if (bucket === undefined) fast.set(prefix, [r]);
    else bucket.push(r);
  }
  return { fast, slow };
}

/** True when char at `i` would NOT cause `\b` to match between i-1 and i,
 * i.e. the char *before* `i` is a word char (so we're INSIDE a word).
 * Used to skip false candidate hits (`AKIA` inside `XAKIA…`). */
function prevIsWordChar(text: string, i: number): boolean {
  if (i === 0) return false;
  const c = text.charCodeAt(i - 1);
  // word char = [A-Za-z0-9_]
  return (
    (c >= 0x30 && c <= 0x39) || (c >= 0x41 && c <= 0x5a) || (c >= 0x61 && c <= 0x7a) || c === 0x5f
  );
}

function matchAnchored(
  text: string,
  fast: Map<string, Recognizer[]>,
  existing: readonly PiiSpan[],
): PiiSpan[] {
  const out: PiiSpan[] = [];
  for (const [prefix, recs] of fast) {
    let i = text.indexOf(prefix);
    while (i !== -1) {
      if (!prevIsWordChar(text, i)) {
        for (const r of recs) {
          const re = ensureGlobal(r.pattern);
          re.lastIndex = i;
          const m = re.exec(text);
          if (m !== null && m.index === i) {
            const start = m.index;
            const end = start + m[0].length;
            const overrides = r.confidence >= 0.9;
            if ((overrides || !overlaps(start, end, existing)) && passesValidate(m[0], r)) {
              const score = r.validate !== undefined ? VALIDATED_RECOGNIZER_SCORE : r.confidence;
              out.push({ label: r.label, start, end, score, text: m[0] });
            }
          }
        }
      }
      // Advance by 1 char so overlapping prefixes like `AKIAAKIA…`
      // still emit both candidate positions.
      i = text.indexOf(prefix, i + 1);
    }
  }
  return out;
}
