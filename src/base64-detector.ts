// SPDX-License-Identifier: Apache-2.0

import { Buffer } from 'node:buffer';
import { MAX_INPUT_BYTES } from './defaults.js';
import { normalizeForDetection } from './normalize.js';
import type { PiiCategory, PiiSpan } from './types/index.js';

/**
 * Base64-aware PII detector. A regex recognizer can't see PII wrapped in
 * base64 — `dXNlci4xMjNAZ21haWwuY29t` decodes to `user.123@gmail.com` but
 * matches no email pattern as-is. This pass scans for base64-looking runs,
 * decodes the printable ones, and re-checks the decoded text for the
 * subset of PII patterns whose surface form changes after base64-wrapping:
 * emails, well-known API key prefixes, and long digit runs (card / acct).
 *
 * Spans are emitted at the *source* (base64) coordinates so they round-trip
 * through the vault and align with gold span annotations that mark the
 * encoded substring.
 */

const BASE64_RUN_RE = /[A-Za-z0-9+/]{24,}={0,2}/g;
const EMAIL_RE = /[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/;
const SECRET_PREFIX_RE =
  /\b(?:sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{16}|xox[abp]-[A-Za-z0-9-]{10,}|ya29\.[A-Za-z0-9_\-]{20,})/;
const LONG_DIGITS_RE = /\d{13,19}/;

// Above any plausible ML softmax score (mdeberta-base GLiNER caps near
// ~0.99998) so the decoded label (e.g. `private_email` for a base64-
// wrapped email) wins over the model's "looks like a secret" fallback
// during cross-label dedupe.
const BASE64_SCORE = 0.99999;

interface DecodedHit {
  readonly label: PiiCategory;
}

/** True when the decoded UTF-8 string looks like human text rather than
 * binary garbage. Rejects embedded NUL and other C0 control bytes
 * (except CR/LF/TAB) plus DEL; accepts anything above 0x7F so non-ASCII
 * scripts (Cyrillic, Greek, Arabic, CJK, …) round-trip into
 * `normalizeForDetection` and out the other side as their ASCII
 * transliteration. */
function isLikelyText(decoded: string): boolean {
  if (decoded.length === 0) return false;
  for (let i = 0; i < decoded.length; i++) {
    const c = decoded.charCodeAt(i);
    if ((c < 0x20 && c !== 0x09 && c !== 0x0a && c !== 0x0d) || c === 0x7f) {
      return false;
    }
  }
  return true;
}

/** Run the same adversarial-input normalisation pass over the decoded
 * payload so chained encodings (e.g. `base64(url-encoded email)`,
 * `base64(zero-width-obfuscated email)`) are caught. Plain ASCII text
 * with no escapes round-trips unchanged through `normalizeForDetection`. */
function classify(decoded: string): DecodedHit | null {
  const normalized = normalizeForDetection(decoded).normalized;
  if (EMAIL_RE.test(normalized)) return { label: 'private_email' };
  if (SECRET_PREFIX_RE.test(normalized)) return { label: 'secret' };
  if (LONG_DIGITS_RE.test(normalized)) return { label: 'account_number' };
  return null;
}

/** Per-blob byte cap. Defence in depth — `MAX_INPUT_BYTES` already caps
 * the whole `text` input, but a deployment that bumps that limit upstream
 * should still skip pathological single-blob payloads inside the
 * detector so a 10 MB base64 run never lands in `Buffer.from` + the
 * classifier regex chain. */
const MAX_BASE64_BLOB_BYTES = 1_000_000;

/** Find PII inside base64-wrapped runs. Spans are in `text` coordinates.
 *
 * `existing` is intentionally not consulted: a base64 blob tagged
 * `secret` by the ML model can still contain a decoded `private_email`
 * — the higher `BASE64_SCORE` lets cross-label dedupe pick the correct
 * label downstream rather than us hiding the hit here.
 *
 * Inputs above `MAX_INPUT_BYTES` are refused upfront — matches the
 * recognizer-pack / normalize policy and stops adversarial multi-MB
 * payloads from running the full decode + classify pipeline. */
export function detectBase64Pii(text: string, _existing: readonly PiiSpan[]): PiiSpan[] {
  if (text.length > MAX_INPUT_BYTES) return [];
  const out: PiiSpan[] = [];
  // Re-create the regex each call so `lastIndex` doesn't bleed across calls.
  const re = new RegExp(BASE64_RUN_RE.source, 'g');
  for (let m = re.exec(text); m !== null; m = re.exec(text)) {
    const blob = m[0];
    const start = m.index;
    const end = start + blob.length;
    // Length must be a base64 multiple of 4 (with padding).
    if (blob.length % 4 !== 0) continue;
    // Per-blob cap — see `MAX_BASE64_BLOB_BYTES` rationale above.
    if (blob.length > MAX_BASE64_BLOB_BYTES) continue;
    let decoded: string;
    try {
      decoded = Buffer.from(blob, 'base64').toString('utf8');
    } catch {
      continue;
    }
    // Reject binary / control-char decodes. Non-ASCII text is allowed —
    // normalizeForDetection inside classify() transliterates it before
    // matching, so Cyrillic / German-umlaut / Greek payloads still hit
    // the email + secret + digits checks.
    if (decoded.length < 6 || !isLikelyText(decoded)) continue;
    const hit = classify(decoded);
    if (hit === null) continue;
    out.push({
      label: hit.label,
      start,
      end,
      score: BASE64_SCORE,
      text: blob,
    });
  }
  return out;
}
