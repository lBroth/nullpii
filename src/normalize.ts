import anyAscii from 'any-ascii';

/**
 * Adversarial-resistant input normalisation with offset map.
 *
 * Mirrors `_normalize_for_detection` in
 * `packages/eval/src/nullpii_eval/adapters.py`. The Python-side
 * preprocessor lifts adversarial F1 measurably:
 *   adv-unicode    0.466 → 0.936  (+0.470)
 *   adv-whitespace 0.106 → 0.393  (+0.287)
 *   adv-typo       baseline → 0.940
 *
 * Applies in order:
 *   - Whitespace-obfuscated PII collapse (`g i a n l u c a` → `gianluca`),
 *     gated by post-check (≥4 digits OR (≥1 `@` + ≥1 letter)) to
 *     avoid mangling prose with sparse digits (`Mary J. Doe age 4 7`).
 *   - URL `%XX` decode (`%40` → `@`), with email-anchor guard.
 *   - HTML numeric entity decode (`&#115;` / `&#x73;` → `s`),
 *     with email-anchor guard.
 *   - Zero-width / soft-hyphen / word-joiner strip.
 *   - Per-char NFKC normalisation.
 *   - Per-char ASCII transliteration via `any-ascii` (handles Cyrillic
 *     homoglyphs, fullwidth digits, mathematical fonts → ASCII
 *     equivalent).
 *
 * Returns `{ normalized, normToOrig }`. `normToOrig[i]` is the
 * original-text index of the i-th char in the normalised text;
 * sentinel at the end equals `text.length` so span ends remap cleanly.
 *
 * Span offsets emitted by the detector against the normalised text
 * are remapped back to original-text offsets via `remapSpan` before
 * the vault stores them.
 */
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

const EMAIL_ANCHOR_CHARS = new Set(['@', '.', '+', '-']);

const NORMALIZE_INPUT_MAX_BYTES = 1_000_000;

export function normalizeForDetection(text: string): NormalizeResult {
  // Refuse pathological input. Quadratic behaviour on
  // SPACED_PII_RE / per-char loops makes adversarial 1 MB+ payloads
  // a DoS vector. Same cap as the regex pack.
  if (text.length > NORMALIZE_INPUT_MAX_BYTES) {
    const passthrough: number[] = [];
    for (let i = 0; i <= text.length; i++) passthrough.push(i);
    return { normalized: text, normToOrig: passthrough };
  }
  // Strict ASCII fast-path: only short-circuit when there's no
  // possibility of despace, URL %XX, or HTML entity decode work.
  // mirror — narrower than the Python proposal because
  // despace + decode legitimately apply to ASCII input.
  if (isPureAsciiNoDecodeNeeded(text)) {
    const passthrough: number[] = [];
    for (let i = 0; i <= text.length; i++) passthrough.push(i);
    return { normalized: text, normToOrig: passthrough };
  }

  const out: string[] = [];
  const normToOrig: number[] = [];
  const n = text.length;
  let i = 0;
  while (i < n) {
    // Whitespace-obfuscated PII collapse.
    const spacedRun = matchSpacedPii(text, i);
    if (spacedRun !== null) {
      let digitCount = 0;
      let hasAt = false;
      let hasAlpha = false;
      for (const ch of spacedRun) {
        if (ASCII_DIGIT_RE.test(ch)) digitCount++;
        else if (ch === '@') hasAt = true;
        else if (ASCII_ALPHA_RE.test(ch)) hasAlpha = true;
      }
      if (digitCount >= 4 || (hasAt && hasAlpha)) {
        for (let j = 0; j < spacedRun.length; j++) {
          const ch = spacedRun[j];
          if (ch === undefined) continue;
          if (/\s/.test(ch)) continue;
          out.push(ch);
          normToOrig.push(i + j);
        }
        i += spacedRun.length;
        continue;
      }
    }

    // URL %XX decode.
    const urlMatch = URL_PERCENT_RE.exec(text.slice(i, i + 3));
    if (urlMatch !== null && urlMatch[1] !== undefined) {
      const code = Number.parseInt(urlMatch[1], 16);
      const decoded = Number.isFinite(code) ? String.fromCharCode(code) : '';
      // Email-anchor guard: keep `@` / `.` / `+` / `-` unchanged so
      // the email regex still matches. Same behaviour as Python F03.
      if (decoded && !EMAIL_ANCHOR_CHARS.has(decoded)) {
        out.push(decoded);
        // map decoded char to END of the triplet.
        normToOrig.push(i + 2);
        i += 3;
        continue;
      }
    }

    // HTML numeric entity decode.
    const htmlMatch = HTML_ENTITY_RE.exec(text.slice(i, i + 12));
    if (htmlMatch !== null) {
      const dec = htmlMatch[1];
      const hex = htmlMatch[2];
      let decodedCode = Number.NaN;
      if (dec !== undefined) decodedCode = Number.parseInt(dec, 10);
      else if (hex !== undefined) decodedCode = Number.parseInt(hex, 16);
      const decoded = Number.isFinite(decodedCode) ? String.fromCodePoint(decodedCode) : '';
      // skip email-anchor chars to preserve email regex.
      if (decoded && !EMAIL_ANCHOR_CHARS.has(decoded)) {
        for (const ch of decoded) {
          out.push(ch);
          normToOrig.push(i);
        }
        i += htmlMatch[0].length;
        continue;
      }
    }

    const ch = text[i];
    if (ch === undefined) {
      i += 1;
      continue;
    }
    if (ZERO_WIDTH_CHARS.has(ch)) {
      i += 1;
      continue;
    }
    const nfkc = ch.normalize('NFKC');
    if (containsNonAscii(nfkc)) {
      const transliterated = anyAscii(nfkc);
      if (transliterated.length > 0) {
        for (const tc of transliterated) {
          out.push(tc);
          normToOrig.push(i);
        }
        i += 1;
        continue;
      }
    }
    for (const nc of nfkc) {
      out.push(nc);
      normToOrig.push(i);
    }
    i += 1;
  }
  normToOrig.push(n);
  return { normalized: out.join(''), normToOrig };
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
