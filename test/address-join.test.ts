// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { joinAddressParts } from '../src/address-join.js';
import type { PiiSpan } from '../src/types/index.js';

const span = (text: string, value: string, label: string, from = 0): PiiSpan => {
  const start = text.indexOf(value, from);
  return { label, start, end: start + value.length, text: value, score: 0.9 } as PiiSpan;
};
const texts = (spans: readonly PiiSpan[]) => spans.map((s) => [s.label, s.text]);

describe('joinAddressParts', () => {
  it('joins the parts of one address around a comma', () => {
    const text = 'Ship to Via Roma 1, 20121 Milano today';
    const out = joinAddressParts(text, [
      span(text, 'Via Roma 1', 'private_address'),
      span(text, '20121 Milano', 'private_address'),
    ]);
    expect(texts(out)).toEqual([['private_address', 'Via Roma 1, 20121 Milano']]);
    expect(out[0]).toMatchObject({ start: 8, end: 32 });
  });

  it('joins across a dash or a slash', () => {
    const text = 'Rue Lepic 3 - 75018 Paris';
    const out = joinAddressParts(text, [
      span(text, 'Rue Lepic 3', 'private_address'),
      span(text, '75018 Paris', 'private_address'),
    ]);
    expect(texts(out)).toEqual([['private_address', 'Rue Lepic 3 - 75018 Paris']]);
  });

  it('keeps two addresses apart across a semicolon or a line break', () => {
    for (const sep of ['; ', '\n']) {
      const text = `Via Roma 1${sep}Corso Italia 5`;
      const out = joinAddressParts(text, [
        span(text, 'Via Roma 1', 'private_address'),
        span(text, 'Corso Italia 5', 'private_address'),
      ]);
      expect(out).toHaveLength(2);
    }
  });

  it('keeps parts apart when words sit between them', () => {
    const text = 'Via Roma 1 and then Milano';
    const out = joinAddressParts(text, [
      span(text, 'Via Roma 1', 'private_address'),
      span(text, 'Milano', 'private_address'),
    ]);
    expect(out).toHaveLength(2);
  });

  it('never joins across another label or into another label', () => {
    const text = 'Via Roma 1, Mario Rossi, Milano';
    const out = joinAddressParts(text, [
      span(text, 'Via Roma 1', 'private_address'),
      span(text, 'Mario Rossi', 'private_person'),
      span(text, 'Milano', 'private_address'),
    ]);
    expect(texts(out)).toEqual([
      ['private_address', 'Via Roma 1'],
      ['private_person', 'Mario Rossi'],
      ['private_address', 'Milano'],
    ]);
  });

  it('chains three parts and orders the result by start', () => {
    const text = 'Via Roma 1, 20121, Milano';
    const out = joinAddressParts(text, [
      span(text, 'Milano', 'private_address'),
      span(text, 'Via Roma 1', 'private_address'),
      span(text, '20121', 'private_address'),
    ]);
    expect(texts(out)).toEqual([['private_address', 'Via Roma 1, 20121, Milano']]);
  });
});
