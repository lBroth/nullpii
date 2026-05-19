// SPDX-License-Identifier: Apache-2.0

import anyAscii from 'any-ascii';
import { MAX_INPUT_BYTES } from './defaults.js';

/** Adversarial-resistant input normalisation with offset map.
 * Steps in order: whitespace-PII collapse (gated by digit/@ post-check),
 * URL `%XX` decode, HTML numeric-entity decode, zero-width strip,
 * NFKC, per-char ASCII transliteration via `any-ascii`.
 * `normToOrig[i]` = original index of the i-th normalised char;
 * sentinel at `length` equals `text.length`. Used by `remapSpan`. */
export interface NormalizeResult {
  readonly normalized: string;
  /** Length = normalized.length + 1; sentinel at end equals original text length. */
  readonly normToOrig: readonly number[];
}

const ZERO_WIDTH_CHARS = new Set([
  '​', // ZERO WIDTH SPACE
  '‌', // ZERO WIDTH NON-JOINER
  '‍', // ZERO WIDTH JOINER
  '﻿', // ZERO WIDTH NO-BREAK SPACE / BOM
  '⁠', // WORD JOINER
  '­', // SOFT HYPHEN
]);

/** Same characters as the Python `_SPACED_PII_RE`. Word-anchored on
 * the left via `(?<!\w)` lookbehind; matches a run of `[\w@.+\-:/]`
 * separated by whitespace runs `\s+`, length ≥ 4. */
const SPACED_PII_RE = /(?<!\w)(?:[\w@.+\-:/]\s+){3,}[\w@.+\-:/]/g;

/** URL percent-encoded byte. */
const URL_PERCENT_RE = /^%([0-9a-fA-F]{2})/;

/** HTML numeric character reference. Group 1 = decimal, group 2 = hex. */
const HTML_ENTITY_RE = /^(?:&#(\d+);|&#x([0-9a-fA-F]+);)/;

const ASCII_DIGIT_RE = /\d/;
const ASCII_ALPHA_RE = /[A-Za-z]/;

/** Maximum nested URL %XX decode rounds per input position. Caps work
 * on adversarial payloads where every byte is multiply percent-encoded.
 * Two rounds is enough for the practical attack (`%2540` → `%40` → `@`)
 * while keeping plain ASCII single-decode O(1). */
const URL_DECODE_MAX_DEPTH = 2;
/** Symmetric cap for HTML numeric-entity decode iterations
 * (`&#x26;#64;` → `&#64;` → `@`). Bounded so a pathological input
 * can't trap the preprocessor in an exponential decode loop. */
const HTML_DECODE_MAX_DEPTH = 2;

export function normalizeForDetection(text: string): NormalizeResult {
  // Refuse pathological input. Quadratic behaviour on
  // SPACED_PII_RE / per-char loops makes adversarial 1 MB+ payloads
  // a DoS vector. Same cap as the regex pack (`MAX_INPUT_BYTES`).
  if (text.length > MAX_INPUT_BYTES || isPureAsciiNoDecodeNeeded(text)) {
    return passthroughResult(text);
  }

  const out: string[] = [];
  const normToOrig: number[] = [];
  const n = text.length;
  let i = 0;
  while (i < n) {
    const consumed =
      tryDespace(text, i, out, normToOrig) ||
      tryUrlDecode(text, i, out, normToOrig) ||
      tryHtmlDecode(text, i, out, normToOrig);
    if (consumed > 0) {
      i += consumed;
      continue;
    }
    transcodeChar(text, i, out, normToOrig);
    i += 1;
  }
  normToOrig.push(n);
  return { normalized: out.join(''), normToOrig };
}

function passthroughResult(text: string): NormalizeResult {
  const normToOrig: number[] = [];
  for (let i = 0; i <= text.length; i++) normToOrig.push(i);
  return { normalized: text, normToOrig };
}

/** Whitespace-obfuscated PII collapse. Returns characters consumed
 * from `text` at offset `i`, or 0 when the despace gate (≥ 4 digits,
 * or `@` + alpha) declines to fire. */
function tryDespace(text: string, i: number, out: string[], normToOrig: number[]): number {
  const spacedRun = matchSpacedPii(text, i);
  if (spacedRun === null) return 0;
  let digitCount = 0;
  let hasAt = false;
  let hasAlpha = false;
  for (const ch of spacedRun) {
    if (ASCII_DIGIT_RE.test(ch)) digitCount++;
    else if (ch === '@') hasAt = true;
    else if (ASCII_ALPHA_RE.test(ch)) hasAlpha = true;
  }
  if (!(digitCount >= 4 || (hasAt && hasAlpha))) return 0;
  for (let j = 0; j < spacedRun.length; j++) {
    const ch = spacedRun[j];
    if (ch === undefined) continue;
    if (/\s/.test(ch)) continue;
    out.push(ch);
    normToOrig.push(i + j);
  }
  return spacedRun.length;
}

/** URL %XX decode. Decode email-anchor bytes too (`%40`→`@`, `%2E`→`.`,
 * …): a fully percent-encoded email (`john%40acme%2Ecom`) only matches
 * the email recognizer after the literal `@`/`.` are restored — the
 * old "keep anchors encoded" guard left those rows undetectable
 * (adversarial-encoding ≈ 0.13).
 *
 * Iterates up to {@link URL_DECODE_MAX_DEPTH} times so chained encodings
 * (`%2540` → `%40` → `@`) collapse to their final form. */
function tryUrlDecode(text: string, i: number, out: string[], normToOrig: number[]): number {
  let consumed = 0;
  let decoded: string | null = null;
  for (let depth = 0; depth < URL_DECODE_MAX_DEPTH; depth++) {
    const innerMatch = URL_PERCENT_RE.exec(text.slice(i + consumed, i + consumed + 3));
    if (innerMatch === null || innerMatch[1] === undefined) break;
    const code = Number.parseInt(innerMatch[1], 16);
    if (!Number.isFinite(code)) break;
    decoded = String.fromCharCode(code);
    consumed += 3;
    // Stop unless the decoded byte is itself `%` and a deeper %XX
    // triplet immediately follows — only then is another pass
    // meaningful. This keeps single-encoded inputs O(1).
    if (decoded !== '%') break;
    decoded = null;
  }
  if (decoded === null || consumed === 0) return 0;
  out.push(decoded);
  // map decoded char to END of the consumed run.
  normToOrig.push(i + consumed - 1);
  return consumed;
}

/** HTML numeric entity decode. Iterates up to {@link HTML_DECODE_MAX_DEPTH}
 * times so chained encodings (`&#x26;#64;` → `&#64;` → `@`) collapse
 * to their final form — same rationale as the URL %XX loop. */
function tryHtmlDecode(text: string, i: number, out: string[], normToOrig: number[]): number {
  let consumed = 0;
  let decoded: string | null = null;
  for (let depth = 0; depth < HTML_DECODE_MAX_DEPTH; depth++) {
    const slice = text.slice(i + consumed, i + consumed + 12);
    const inner = HTML_ENTITY_RE.exec(slice);
    if (inner === null) break;
    const dec = inner[1];
    const hex = inner[2];
    let code = Number.NaN;
    if (dec !== undefined) code = Number.parseInt(dec, 10);
    else if (hex !== undefined) code = Number.parseInt(hex, 16);
    if (!Number.isFinite(code)) break;
    decoded = String.fromCodePoint(code);
    consumed += inner[0].length;
    // Only re-iterate if the decoded byte is `&` AND the next chars
    // begin another `&#…;` triplet — otherwise we'd waste cycles.
    if (decoded !== '&') break;
    decoded = null;
  }
  if (decoded === null || consumed === 0) return 0;
  for (const ch of decoded) {
    out.push(ch);
    normToOrig.push(i + consumed - 1);
  }
  return consumed;
}

/** Per-char NFKC + zero-width strip + ASCII transliteration fallback. */
function transcodeChar(text: string, i: number, out: string[], normToOrig: number[]): void {
  const ch = text[i];
  if (ch === undefined) return;
  if (ZERO_WIDTH_CHARS.has(ch)) return;
  const nfkc = ch.normalize('NFKC');
  if (containsNonAscii(nfkc)) {
    const transliterated = anyAscii(nfkc);
    if (transliterated.length > 0) {
      for (const tc of transliterated) {
        out.push(tc);
        normToOrig.push(i);
      }
      return;
    }
  }
  for (const nc of nfkc) {
    out.push(nc);
    normToOrig.push(i);
  }
}

/**
 * Map a span `[start, end)` from normalised-text offsets back to
 * original-text offsets.
 *
 * Mirrors `_remap_span` in the Python adapter (strict
 * `min(idx, max_idx)` clamp — never use `>=` because the sentinel
 * at index `len(normToOrig) - 1` is the valid end-exclusive
 * position). Returns `[origStart, origEnd]`.
 */
export function remapSpan(
  normStart: number,
  normEnd: number,
  normToOrig: readonly number[],
): [number, number] {
  const maxIdx = normToOrig.length - 1;
  const ns = Math.max(0, Math.min(normStart, maxIdx));
  const ne = Math.max(0, Math.min(normEnd, maxIdx));
  const origStart = normToOrig[ns];
  const origEnd = normToOrig[ne];
  if (origStart === undefined || origEnd === undefined) {
    throw new RangeError('remapSpan: index out of bounds');
  }
  return [origStart, origEnd];
}

// ─── Internals ─────────────────────────────────────────────────────

function isPureAsciiNoDecodeNeeded(text: string): boolean {
  // Reject if any byte > 127 (non-ASCII → may need NFKC + translit).
  // Reject if `&#` present (HTML entity candidate).
  // Reject if `%` present (URL %XX candidate).
  // Reject if 4+ consecutive whitespace-separated single chars (despace
  // candidate). The 4-char threshold matches SPACED_PII_RE's `{3,}+1`.
  if (text.includes('&#') || text.includes('%')) return false;
  for (let i = 0; i < text.length; i++) {
    if (text.charCodeAt(i) > 127) return false;
  }
  // Quick despace pre-check: scan for `[\w] \s [\w] \s [\w] \s [\w]`
  // pattern — if absent, despace can't fire.
  return !/(?:[\w@.+\-:/]\s+){3,}[\w@.+\-:/]/.test(text);
}

function containsNonAscii(text: string): boolean {
  for (let i = 0; i < text.length; i++) {
    if (text.charCodeAt(i) > 127) return true;
  }
  return false;
}

function matchSpacedPii(text: string, start: number): string | null {
  // Use sticky `y` flag against the FULL text (not a slice) so the
  // `(?<!\w)` lookbehind in SPACED_PII_RE can still see the
  // preceding character. Slicing would break lookbehind context and
  // mis-match runs that start mid-word.
  const re = new RegExp(SPACED_PII_RE.source, 'y');
  re.lastIndex = start;
  const m = re.exec(text);
  return m !== null && m.index === start ? m[0] : null;
}
