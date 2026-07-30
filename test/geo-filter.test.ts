// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { dropNonCoordinateGeolocation, isCoordinateShaped } from '../src/geo-filter.js';

describe('isCoordinateShaped', () => {
  it('accepts the decimal lat/lon pairs the model actually emits', () => {
    // Verbatim span surfaces from `isotonic-en-heldout` predictions.
    for (const s of ['-17.2941,-98.1523', '30.4115,-55.8172', '13.018,162.6403']) {
      expect(isCoordinateShaped(s), s).toBe(true);
    }
  });

  it('tolerates the bracket / stray-punctuation boundaries the head produces', () => {
    expect(isCoordinateShaped('[62.4693,169.5474]')).toBe(true);
    expect(isCoordinateShaped('- [-64.6681,-23.7374')).toBe(true);
  });

  it('accepts DMS with a hemisphere letter', () => {
    expect(isCoordinateShaped('48° 51\' 29" N')).toBe(true);
  });

  it('rejects the place names and postcodes the zero-shot head mislabels', () => {
    // Each of these was emitted as `private_geolocation` while the gold
    // said `private_address`.
    for (const s of ['Nidwalden', 'Emilia-Romagna', 'Rohnert Park', '98025', 'Southeast']) {
      expect(isCoordinateShaped(s), s).toBe(false);
    }
  });

  it('rejects IPv4 — dotted quads have no separator and must not read as a pair', () => {
    expect(isCoordinateShaped('210.193.85.111')).toBe(false);
    expect(isCoordinateShaped('197.54.143.140')).toBe(false);
  });

  it('rejects bare integer pairs — a range or score is not a coordinate', () => {
    expect(isCoordinateShaped('12, 34')).toBe(false);
    expect(isCoordinateShaped('95935500')).toBe(false);
  });

  it('defers to latLonPairInRange for range and null-island rejection', () => {
    expect(isCoordinateShaped('200.5,-300.2')).toBe(false); // lat out of range
    expect(isCoordinateShaped('0.0,0.0')).toBe(false); // null island / sensor default
  });
});

describe('dropNonCoordinateGeolocation', () => {
  const text = 'Seen at 45.4642,9.1900 near Rohnert Park, IP 210.193.85.111';
  const at = (needle: string) => {
    const start = text.indexOf(needle);
    return { start, end: start + needle.length };
  };

  it('keeps coordinate spans and drops the rest', () => {
    const spans = [
      { label: 'private_geolocation', ...at('45.4642,9.1900') },
      { label: 'private_geolocation', ...at('Rohnert Park') },
      { label: 'private_geolocation', ...at('210.193.85.111') },
    ];
    const kept = dropNonCoordinateGeolocation(spans, text);
    expect(kept.map((s) => text.slice(s.start, s.end))).toEqual(['45.4642,9.1900']);
  });

  it('never touches spans of another label', () => {
    const spans = [
      { label: 'private_address', ...at('Rohnert Park') },
      { label: 'private_ip', ...at('210.193.85.111') },
      { label: 'private_geolocation', ...at('Rohnert Park') },
    ];
    const kept = dropNonCoordinateGeolocation(spans, text);
    expect(kept.map((s) => s.label)).toEqual(['private_address', 'private_ip']);
  });

  it('is a no-op when no geolocation span is present', () => {
    const spans = [{ label: 'private_ip', ...at('210.193.85.111') }];
    expect(dropNonCoordinateGeolocation(spans, text)).toEqual(spans);
  });
});
