// SPDX-License-Identifier: Apache-2.0

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

import {
  codiceFiscaleValid,
  cpfValid,
  iban97Valid,
  luhnValid,
  macAddressNonReserved,
} from '../src/validators.js';

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

  it('rejects 12-digit Luhn-passing string (below minimum card length)', () => {
    // Real credit cards start at 13 digits — anything shorter is FP-prone
    // (Italian phone numbers, long IDs). Confirm a 12-digit input is
    // rejected even when its mod-10 checksum would otherwise pass.
    expect(luhnValid('123456789012')).toBe(false);
  });

  it('rejects non-numeric content', () => {
    expect(luhnValid('4111 1111 ABCD 1111')).toBe(false);
  });
});

describe('macAddressNonReserved', () => {
  it('accepts a regular unicast MAC', () => {
    expect(macAddressNonReserved('01:23:45:67:89:ab')).toBe(true);
    expect(macAddressNonReserved('aa-bb-cc-dd-ee-ff')).toBe(true);
  });

  it('rejects the broadcast MAC', () => {
    expect(macAddressNonReserved('ff:ff:ff:ff:ff:ff')).toBe(false);
    expect(macAddressNonReserved('FF:FF:FF:FF:FF:FF')).toBe(false);
  });

  it('rejects the null / uninitialised MAC', () => {
    expect(macAddressNonReserved('00:00:00:00:00:00')).toBe(false);
  });

  it('rejects multicast prefixes (IPv4, IPv6, STP)', () => {
    expect(macAddressNonReserved('01:00:5e:00:00:01')).toBe(false); // IPv4 multicast
    expect(macAddressNonReserved('33:33:00:00:00:01')).toBe(false); // IPv6 multicast
    expect(macAddressNonReserved('01:80:c2:00:00:00')).toBe(false); // STP
  });

  it('rejects malformed input', () => {
    expect(macAddressNonReserved('not-a-mac')).toBe(false);
    expect(macAddressNonReserved('01:23:45:67:89')).toBe(false);
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

  // Check letters below come from an independent implementation of the
  // official tables (DM 12/03/1974), not from this validator.
  it('accepts omocodic codes, one to seven digits replaced from the right', () => {
    for (const cf of [
      'RSSMRA85T10A56NH',
      'RSSMRA85T10A5SNT',
      'RSSMRA85T10ARSNO',
      'RSSMRA85T1LARSNR',
      'RSSMRA85TMLARSNC',
      'RSSMRA8RTMLARSNO',
      'RSSMRAURTMLARSNL',
    ]) {
      expect(codiceFiscaleValid(cf)).toBe(true);
    }
  });

  it('rejects a substitution that is not a suffix of the digits', () => {
    // Year digit replaced while the later digits are still digits.
    expect(codiceFiscaleValid('RSSMRAU5T10A562P')).toBe(false);
  });

  it("checks the day: 41–71 marks a woman's code, 32–40 is impossible", () => {
    expect(codiceFiscaleValid('VRDLCU90A41H501M')).toBe(true);
    expect(codiceFiscaleValid('RSSMRA85T32A562Y')).toBe(false);
  });

  it('rejects mixed case, which is a code identifier, not a written code', () => {
    expect(codiceFiscaleValid('RSSMRA85T10A562S')).toBe(true);
    expect(codiceFiscaleValid('rssmra85t10a562s')).toBe(true);
    expect(codiceFiscaleValid('RssMra85T10a562S')).toBe(false);
  });
});

import { partitaIvaValid } from '../src/validators.js';

// Check digits below come from an independent implementation of the
// DPR 633/1972 algorithm, not from this validator.
describe('partitaIvaValid', () => {
  it('accepts valid numbers, with or without the IT prefix', () => {
    for (const v of [
      '12345670017',
      '07654320881',
      '00000011007',
      '98765431204',
      'IT12345670017',
      'it 07654320881',
    ]) {
      expect(partitaIvaValid(v)).toBe(true);
    }
  });

  it('rejects a wrong check digit', () => {
    expect(partitaIvaValid('12345670018')).toBe(false);
  });

  it('rejects an office code the tax office does not assign', () => {
    // Office 150: valid check digit, impossible office.
    expect(partitaIvaValid('12345671502')).toBe(false);
  });

  it('rejects other lengths and non-digits', () => {
    expect(partitaIvaValid('1234567001')).toBe(false);
    expect(partitaIvaValid('123456700177')).toBe(false);
    expect(partitaIvaValid('1234567001X')).toBe(false);
  });
});

import { latLonPairInRange, vinValid } from '../src/validators.js';

describe('vinValid', () => {
  it('accepts a known-valid Toyota VIN', () => {
    // Public sample VIN from NHTSA vPIC documentation.
    expect(vinValid('1HGCM82633A123456')).toBe(false); // pre-tampered for failure baseline
    expect(vinValid('1HGCM82633A004352')).toBe(true);
  });

  it('rejects a VIN with bad check digit', () => {
    expect(vinValid('1HGCM82633A004353')).toBe(false);
  });

  it('rejects forbidden chars (I, O, Q)', () => {
    expect(vinValid('1HGCM8I633A004352')).toBe(false);
    expect(vinValid('1HGCM8O633A004352')).toBe(false);
    expect(vinValid('1HGCM8Q633A004352')).toBe(false);
  });

  it('rejects wrong length', () => {
    expect(vinValid('1HGCM82633A00435')).toBe(false);
    expect(vinValid('1HGCM82633A0043522')).toBe(false);
  });

  it('accepts lowercase (case-insensitive)', () => {
    expect(vinValid('1hgcm82633a004352')).toBe(true);
  });
});

describe('latLonPairInRange', () => {
  it('accepts coords inside [-90, 90] × [-180, 180]', () => {
    expect(latLonPairInRange('41.9028, 12.4964')).toBe(true); // Rome
    expect(latLonPairInRange('-33.8688, 151.2093')).toBe(true); // Sydney
    expect(latLonPairInRange('90, 180')).toBe(true);
    expect(latLonPairInRange('-90, -180')).toBe(true);
  });

  it('rejects out-of-range coords', () => {
    expect(latLonPairInRange('91.0, 0.0')).toBe(false);
    expect(latLonPairInRange('0.0, 181.0')).toBe(false);
    expect(latLonPairInRange('-90.1, 0.0')).toBe(false);
  });

  it('rejects null-island origin (0, 0)', () => {
    expect(latLonPairInRange('0, 0')).toBe(false);
    expect(latLonPairInRange('0.0, 0.0')).toBe(false);
  });

  it('rejects non-numeric or wrong-arity input', () => {
    expect(latLonPairInRange('41.9028')).toBe(false);
    expect(latLonPairInRange('41.9028, 12.4964, 100')).toBe(false);
    expect(latLonPairInRange('lat, lon')).toBe(false);
  });
});
