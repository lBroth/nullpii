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
