// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import {
  CODICE_FISCALE,
  PARTITA_IVA,
  validateCodiceFiscale,
  validatePartitaIva,
} from '../../packages/recognizers-id-it/src/index.js';
import { runRecognizers } from '../../src/recognizers.js';

describe('validateCodiceFiscale', () => {
  it('accepts a known-valid codice fiscale', () => {
    // Mario Rossi, born 1 Jan 1980 in Roma — synthetic CF used in
    // public examples (does not identify a real person).
    expect(validateCodiceFiscale('RSSMRA80A01H501U')).toBe(true);
  });
  it('rejects a wrong checksum', () => {
    expect(validateCodiceFiscale('RSSMRA80A01H501A')).toBe(false);
  });
  it('rejects malformed input', () => {
    expect(validateCodiceFiscale('not-a-cf-string')).toBe(false);
  });
});

describe('validatePartitaIva', () => {
  it('accepts a known-valid PIVA', () => {
    expect(validatePartitaIva('00743110157')).toBe(true);
  });
  it('rejects wrong checksum', () => {
    expect(validatePartitaIva('00743110158')).toBe(false);
  });
  it('rejects non-11-digit input', () => {
    expect(validatePartitaIva('1234567890')).toBe(false);
  });
});

describe('CODICE_FISCALE recognizer', () => {
  it('finds CFs in text and validates them', () => {
    const text = 'CF: RSSMRA80A01H501U; bogus: AAAAAA00A00A000A';
    const spans = runRecognizers(text, [CODICE_FISCALE], []);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.text).toBe('RSSMRA80A01H501U');
  });
});

describe('PARTITA_IVA recognizer', () => {
  it('emits span only for valid 11-digit checksum', () => {
    const text = 'piva 00743110157 ok; piva 00743110158 ko';
    const spans = runRecognizers(text, [PARTITA_IVA], []);
    expect(spans).toHaveLength(1);
  });
});
