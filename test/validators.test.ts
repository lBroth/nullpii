import { describe, expect, it } from 'vitest';
import { base58CheckValid } from '../src/validators.js';

describe('base58CheckValid', () => {
  it('accepts the Bitcoin Genesis Block address (Satoshi)', () => {
    expect(base58CheckValid('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa')).toBe(true);
  });

  it('accepts a real P2SH address', () => {
    expect(base58CheckValid('3J98t1WpEZ73CNmQviecrnyiWrnqRhWNLy')).toBe(true);
  });

  it('rejects a tampered address (last char swapped)', () => {
    expect(base58CheckValid('1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNb')).toBe(false);
  });

  it('rejects a base58-shape prose token', () => {
    // Audit F07 example: `Order ID: 1A2B3C4D5E6F7G8H9J1K2L3M4N` was wrongly tagged.
    expect(base58CheckValid('1A2B3C4D5E6F7G8H9J1K2L3M4N')).toBe(false);
  });

  it('rejects a too-short string', () => {
    expect(base58CheckValid('1A1z')).toBe(false);
  });

  it('rejects characters outside the base58 alphabet', () => {
    // `O`, `0`, `I`, `l` are not in base58. `Oolong` is not base58.
    expect(base58CheckValid('1Oolong0NotBase58Address123Token')).toBe(false);
  });

  it('rejects an empty string', () => {
    expect(base58CheckValid('')).toBe(false);
  });
});

import { codiceFiscaleValid, cpfValid, iban97Valid, luhnValid } from '../src/validators.js';

describe('luhnValid', () => {
  it('accepts a valid Visa test card', () => {
    expect(luhnValid('4111 1111 1111 1111')).toBe(true);
  });

  it('accepts a valid Mastercard test card with hyphen separators', () => {
    expect(luhnValid('5500-0000-0000-0004')).toBe(true);
  });

  it('rejects a tampered last digit', () => {
    expect(luhnValid('4111 1111 1111 1112')).toBe(false);
  });

  it('rejects a 16-digit non-CC number', () => {
    expect(luhnValid('1234567890123456')).toBe(false);
  });

  it('rejects too-short input', () => {
    expect(luhnValid('41111111')).toBe(false);
  });

  it('rejects non-numeric content', () => {
    expect(luhnValid('4111 1111 ABCD 1111')).toBe(false);
  });
});

describe('iban97Valid', () => {
  it('accepts a valid Italian IBAN', () => {
    expect(iban97Valid('IT60X0542811101000000123456')).toBe(true);
  });

  it('accepts a valid German IBAN with spaces', () => {
    expect(iban97Valid('DE89 3704 0044 0532 0130 00')).toBe(true);
  });

  it('rejects a tampered IBAN', () => {
    expect(iban97Valid('IT61X0542811101000000123456')).toBe(false);
  });

  it('rejects a country-prefix-shaped non-IBAN', () => {
    expect(iban97Valid('US12 3456 7890 1234 5678')).toBe(false);
  });

  it('rejects too-short input', () => {
    expect(iban97Valid('IT60X')).toBe(false);
  });
});

describe('cpfValid', () => {
  it('accepts a valid CPF', () => {
    // Public test CPF (Receita Federal example).
    expect(cpfValid('390.533.447-05')).toBe(true);
  });

  it('rejects a tampered CPF', () => {
    expect(cpfValid('390.533.447-04')).toBe(false);
  });

  it('rejects all-same-digit CPF (`000.000.000-00`)', () => {
    expect(cpfValid('000.000.000-00')).toBe(false);
    expect(cpfValid('111.111.111-11')).toBe(false);
  });

  it('rejects too-short or non-digit input', () => {
    expect(cpfValid('390.533.447')).toBe(false);
    expect(cpfValid('abc.def.ghi-jk')).toBe(false);
  });
});

describe('codiceFiscaleValid', () => {
  it('accepts a valid CF', () => {
    // Mario Rossi born 1980-04-15 in Roma — public format example.
    expect(codiceFiscaleValid('RSSMRA80D15H501O')).toBe(true);
  });

  it('rejects a tampered final check letter', () => {
    expect(codiceFiscaleValid('RSSMRA80D15H501Z')).toBe(false);
    expect(codiceFiscaleValid('RSSMRA80D15H501U')).toBe(false);
  });

  it('rejects wrong length', () => {
    expect(codiceFiscaleValid('RSSMRA80D15H501')).toBe(false);
    expect(codiceFiscaleValid('RSSMRA80D15H501OA')).toBe(false);
  });

  it('rejects invalid month-letter (e.g. `K`)', () => {
    expect(codiceFiscaleValid('RSSMRA80K15H501U')).toBe(false);
  });

  it('accepts lowercase input (case-insensitive)', () => {
    expect(codiceFiscaleValid('rssmra80d15h501o')).toBe(true);
  });
});
