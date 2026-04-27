// SPDX-License-Identifier: Apache-2.0
import type { Recognizer } from 'nullpii';

const ODD_VALUES: Readonly<Record<string, number>> = {
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
const EVEN_VALUES: Readonly<Record<string, number>> = {
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
const ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ';

/** Codice fiscale (Italian taxpayer id) — 16-char checksum. */
export function validateCodiceFiscale(raw: string): boolean {
  const s = raw.toUpperCase();
  if (!/^[A-Z0-9]{16}$/.test(s)) return false;
  let sum = 0;
  for (let i = 0; i < 15; i++) {
    const ch = s[i];
    if (ch === undefined) return false;
    const v = i % 2 === 0 ? ODD_VALUES[ch] : EVEN_VALUES[ch];
    if (v === undefined) return false;
    sum += v;
  }
  return ALPHABET[sum % 26] === s[15];
}

/** Partita IVA (Italian VAT) — 11-digit Luhn-style mod-10 (Italian variant). */
export function validatePartitaIva(raw: string): boolean {
  const s = raw.replace(/\D/g, '');
  if (s.length !== 11) return false;
  let sum = 0;
  for (let i = 0; i < 11; i++) {
    let n = Number(s[i]);
    if (i % 2 === 1) {
      n *= 2;
      if (n > 9) n -= 9;
    }
    sum += n;
  }
  return sum % 10 === 0;
}

export const CODICE_FISCALE: Recognizer = {
  id: 'id-it:codice-fiscale',
  pattern: /\b[A-Z]{6}\d{2}[A-Z]\d{2}[A-Z]\d{3}[A-Z]\b/gi,
  label: 'account_number',
  confidence: 0.97,
  validate: validateCodiceFiscale,
};

export const PARTITA_IVA: Recognizer = {
  id: 'id-it:partita-iva',
  pattern: /\b\d{11}\b/g,
  label: 'account_number',
  confidence: 0.9,
  validate: validatePartitaIva,
};

export const ITALIAN_IDS: readonly Recognizer[] = [CODICE_FISCALE, PARTITA_IVA];
