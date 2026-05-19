// SPDX-License-Identifier: Apache-2.0

import { createHash } from 'node:crypto';

/** Post-match checksum / range validators wired via `Recognizer.validate`.
 * Each function below carries its own algorithm doc. */

const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';
const BASE58_INDEX = new Map<string, bigint>();
for (let i = 0; i < BASE58_ALPHABET.length; i++) {
  const ch = BASE58_ALPHABET[i];
  if (ch !== undefined) BASE58_INDEX.set(ch, BigInt(i));
}

/** BIP-0013 base58check: decode → payload + 4-byte checksum;
 * `SHA256(SHA256(payload))[:4]` must equal checksum. */
export function base58CheckValid(addr: string): boolean {
  if (addr.length < 25 || addr.length > 35) return false;
  let n = 0n;
  for (const ch of addr) {
    const idx = BASE58_INDEX.get(ch);
    if (idx === undefined) return false;
    n = n * 58n + idx;
  }
  // Convert bigint to bytes (big-endian).
  const body: number[] = [];
  let v = n;
  while (v > 0n) {
    body.unshift(Number(v & 0xffn));
    v >>= 8n;
  }
  // Re-attach leading-zero bytes encoded as leading `1`s in base58.
  let leadingOnes = 0;
  for (const ch of addr) {
    if (ch === '1') leadingOnes++;
    else break;
  }
  const decoded = Buffer.from([...new Array(leadingOnes).fill(0), ...body]);
  if (decoded.length < 5) return false;
  const payload = decoded.subarray(0, decoded.length - 4);
  const checksum = decoded.subarray(decoded.length - 4);
  const expected = createHash('sha256')
    .update(createHash('sha256').update(payload).digest())
    .digest()
    .subarray(0, 4);
  return checksum.equals(expected);
}

// ─── Luhn (credit card) ────────────────────────────────────────────

/**
 * Luhn / mod-10 checksum for credit-card numbers. Strips any
 * `-`/`.`/space separators before validating. Returns `false` on
 * non-digit residue or length out of [13, 19].
 *
 * NB: the lower bound is 13 (smallest issued card today), not 12
 * — 12-digit Luhn-passing strings occur naturally in long phone
 * numbers and IDs; tagging them as `account_number` is a high-volume
 * FP source on bench corpora.
 */
export function luhnValid(value: string): boolean {
  const digits = value.replace(/[\s\-.]/g, '');
  if (digits.length < 13 || digits.length > 19) return false;
  if (!/^\d+$/.test(digits)) return false;
  let sum = 0;
  let alt = false;
  for (let i = digits.length - 1; i >= 0; i--) {
    const d = digits.charCodeAt(i) - 48;
    let x = d;
    if (alt) {
      x = x * 2;
      if (x > 9) x -= 9;
    }
    sum += x;
    alt = !alt;
  }
  return sum % 10 === 0;
}

// ─── IBAN mod-97 ───────────────────────────────────────────────────

/**
 * IBAN validator (ISO 13616). Rotates first 4 chars to the end,
 * substitutes letters A=10..Z=35, and checks `mod 97 === 1`.
 * Strips any whitespace separators (NBSP / U+202F included via the
 * `\s` class).
 */
export function iban97Valid(value: string): boolean {
  const compact = value.replace(/\s+/g, '').toUpperCase();
  if (compact.length < 15 || compact.length > 34) return false;
  if (!/^[A-Z]{2}\d{2}[A-Z0-9]+$/.test(compact)) return false;
  const rotated = compact.slice(4) + compact.slice(0, 4);
  let buf = '';
  for (const ch of rotated) {
    if (ch >= '0' && ch <= '9') buf += ch;
    else buf += (ch.charCodeAt(0) - 55).toString(); // A=10..Z=35
  }
  // mod-97 over a long numeric string, processed in chunks.
  let rem = 0;
  for (let i = 0; i < buf.length; i += 7) {
    rem = Number.parseInt(rem.toString() + buf.slice(i, i + 7), 10) % 97;
  }
  return rem === 1;
}

// ─── Brazilian CPF (mod-11 × 2) ────────────────────────────────────

/**
 * Brazilian CPF validator. 11 digits in `XXX.XXX.XXX-XX` form. Two
 * check digits computed by mod-11 over weighted sums; CPFs with all
 * 11 digits identical (e.g. `000.000.000-00`, `111.111.111-11`) are
 * valid by formula but rejected by convention.
 */
export function cpfValid(value: string): boolean {
  const digits = value.replace(/[.\-]/g, '');
  if (digits.length !== 11) return false;
  if (!/^\d{11}$/.test(digits)) return false;
  if (/^(\d)\1{10}$/.test(digits)) return false;
  const calc = (slice: string, weight: number) => {
    let sum = 0;
    for (let i = 0; i < slice.length; i++) {
      sum += (slice.charCodeAt(i) - 48) * (weight - i);
    }
    const r = (sum * 10) % 11;
    return r === 10 ? 0 : r;
  };
  const d1 = calc(digits.slice(0, 9), 10);
  const d2 = calc(digits.slice(0, 10), 11);
  return d1 === Number(digits[9]) && d2 === Number(digits[10]);
}

// ─── Italian Codice Fiscale (16-char personal tax id) ──────────────

const CF_ODD_VALUES: Record<string, number> = {
  '0': 1,
  '1': 0,
  '2': 5,
  '3': 7,
  '4': 9,
  '5': 13,
  '6': 15,
  '7': 17,
  '8': 19,
  '9': 21,
  A: 1,
  B: 0,
  C: 5,
  D: 7,
  E: 9,
  F: 13,
  G: 15,
  H: 17,
  I: 19,
  J: 21,
  K: 2,
  L: 4,
  M: 18,
  N: 20,
  O: 11,
  P: 3,
  Q: 6,
  R: 8,
  S: 12,
  T: 14,
  U: 16,
  V: 10,
  W: 22,
  X: 25,
  Y: 24,
  Z: 23,
};
const CF_EVEN_VALUES: Record<string, number> = {
  '0': 0,
  '1': 1,
  '2': 2,
  '3': 3,
  '4': 4,
  '5': 5,
  '6': 6,
  '7': 7,
  '8': 8,
  '9': 9,
  A: 0,
  B: 1,
  C: 2,
  D: 3,
  E: 4,
  F: 5,
  G: 6,
  H: 7,
  I: 8,
  J: 9,
  K: 10,
  L: 11,
  M: 12,
  N: 13,
  O: 14,
  P: 15,
  Q: 16,
  R: 17,
  S: 18,
  T: 19,
  U: 20,
  V: 21,
  W: 22,
  X: 23,
  Y: 24,
  Z: 25,
};
const CF_CHECK_LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

/**
 * Italian Codice Fiscale validator. Format: 6 alpha + 2 digit +
 * month-letter (one of A-EHLMPRST) + 2 digit day + alpha + 3 digit +
 * 1 control letter.
 *
 * Checksum: sum odd-position weights + even-position weights over
 * the first 15 chars; (sum mod 26) maps to check letter A-Z. Match
 * against the 16th character.
 */
export function codiceFiscaleValid(value: string): boolean {
  const cf = value.toUpperCase();
  if (cf.length !== 16) return false;
  if (!/^[A-Z]{6}\d{2}[A-EHLMPRST]\d{2}[A-Z]\d{3}[A-Z]$/.test(cf)) return false;
  let sum = 0;
  for (let i = 0; i < 15; i++) {
    const ch = cf[i];
    if (ch === undefined) return false;
    // Position is 1-indexed for the official spec; odd positions in
    // 1-indexed = even indices in 0-indexed.
    const isOddPosition = i % 2 === 0;
    const value = isOddPosition ? CF_ODD_VALUES[ch] : CF_EVEN_VALUES[ch];
    if (value === undefined) return false;
    sum += value;
  }
  const expected = CF_CHECK_LETTERS[sum % 26];
  return expected !== undefined && expected === cf[15];
}

// ─── MAC address (reject reserved / non-personal values) ───────────

/**
 * Treat a syntactically-valid MAC address as PII only if it doesn't
 * fall into a well-known reserved range. Rejects:
 *
 *   - broadcast: `ff:ff:ff:ff:ff:ff`
 *   - null: `00:00:00:00:00:00`
 *   - IPv4 multicast: `01:00:5e:*`
 *   - IPv6 multicast: `33:33:*`
 *   - STP / bridge multicast: `01:80:c2:*`
 *
 * These identify protocol groups or uninitialised state, not a
 * device assignable to a person. Matches the convention used by
 * `core:ip` for `0.0.0.0` / `127.0.0.1` / link-local etc.
 */
export function macAddressNonReserved(value: string): boolean {
  const hex = value.replace(/[-:]/g, '').toLowerCase();
  if (hex.length !== 12 || !/^[0-9a-f]{12}$/.test(hex)) return false;
  if (hex === 'ffffffffffff') return false;
  if (hex === '000000000000') return false;
  if (hex.startsWith('01005e')) return false; // IPv4 multicast
  if (hex.startsWith('3333')) return false; // IPv6 multicast
  if (hex.startsWith('0180c2')) return false; // STP / bridge multicast
  return true;
}

// ─── VIN (ISO 3779 mod-11 weighted check digit) ────────────────────

const VIN_TRANSLIT: Record<string, number> = {
  A: 1,
  B: 2,
  C: 3,
  D: 4,
  E: 5,
  F: 6,
  G: 7,
  H: 8,
  J: 1,
  K: 2,
  L: 3,
  M: 4,
  N: 5,
  P: 7,
  R: 9,
  S: 2,
  T: 3,
  U: 4,
  V: 5,
  W: 6,
  X: 7,
  Y: 8,
  Z: 9,
  '0': 0,
  '1': 1,
  '2': 2,
  '3': 3,
  '4': 4,
  '5': 5,
  '6': 6,
  '7': 7,
  '8': 8,
  '9': 9,
};
const VIN_WEIGHTS = [8, 7, 6, 5, 4, 3, 2, 10, 0, 9, 8, 7, 6, 5, 4, 3, 2];

/**
 * Vehicle Identification Number (ISO 3779). 17 chars excluding `I`,
 * `O`, `Q` (avoid digit confusion). Check digit at position 9
 * (0-indexed 8) computed as `sum(translit[i] * weight[i]) mod 11`,
 * with remainder 10 represented as `X`. Note: pre-1981 VINs and
 * some non-North-American manufacturers omit the check digit — this
 * validator only passes strict ISO 3779; relax to syntactic match
 * if your dataset includes legacy VINs.
 */
export function vinValid(value: string): boolean {
  const vin = value.toUpperCase();
  if (vin.length !== 17) return false;
  if (!/^[A-HJ-NPR-Z0-9]{17}$/.test(vin)) return false;
  let sum = 0;
  for (let i = 0; i < 17; i++) {
    const ch = vin[i];
    if (ch === undefined) return false;
    const t = VIN_TRANSLIT[ch];
    if (t === undefined) return false;
    const w = VIN_WEIGHTS[i];
    if (w === undefined) return false;
    sum += t * w;
  }
  const remainder = sum % 11;
  const expected = remainder === 10 ? 'X' : String(remainder);
  return vin[8] === expected;
}

// ─── Geolocation (lat/lon range) ───────────────────────────────────

/**
 * A bare decimal in `[-90, 90]` or `[-180, 180]` is far too common in
 * arbitrary text to flag in isolation (any percentage, score, sensor
 * reading would match). This validator is intended for the paired
 * `lat,lon` recognizer below — passed a single string of the form
 * `"<lat>, <lon>"` (any whitespace between).
 */
export function latLonPairInRange(value: string): boolean {
  const parts = value.split(/[,\s]+/).filter((p) => p.length > 0);
  if (parts.length !== 2) return false;
  const lat = Number(parts[0]);
  const lon = Number(parts[1]);
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return false;
  if (lat < -90 || lat > 90) return false;
  if (lon < -180 || lon > 180) return false;
  // Reject the obvious null-island / origin point — almost always a
  // sensor default or test value, not a real location.
  if (lat === 0 && lon === 0) return false;
  return true;
}
