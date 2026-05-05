import { describe, expect, it } from 'vitest';
import { normalizeForDetection, remapSpan } from '../src/normalize.js';

describe('normalizeForDetection', () => {
  it('passes through ASCII unchanged', () => {
    const text = 'Plain ASCII text with john@example.com and SSN 123-45-6789.';
    const r = normalizeForDetection(text);
    expect(r.normalized).toBe(text);
    expect(r.normToOrig).toHaveLength(text.length + 1);
    // Identity offset map for ASCII fast-path.
    for (let i = 0; i <= text.length; i++) {
      expect(r.normToOrig[i]).toBe(i);
    }
  });

  it('strips zero-width characters', () => {
    // ZWSP between `john` and `@`. Original length 18, normalised 17.
    const text = 'john​@example.com';
    const r = normalizeForDetection(text);
    expect(r.normalized).toBe('john@example.com');
    // Span over the entire normalised email maps back to the full
    // original including the ZWSP.
    const [origStart, origEnd] = remapSpan(0, r.normalized.length, r.normToOrig);
    expect(origStart).toBe(0);
    expect(origEnd).toBe(text.length);
  });

  it('decodes Cyrillic homoglyphs to ASCII', () => {
    // Cyrillic а / о / е look like Latin a / o / e but are different
    // codepoints. AnyAscii transliterates them to their ASCII look-alikes.
    const text = 'аdmin@еxample.com'; // Cyrillic а + е
    const r = normalizeForDetection(text);
    expect(r.normalized).toBe('admin@example.com');
    // Email regex now matches; vault span remaps back to original.
    const [origStart, origEnd] = remapSpan(0, r.normalized.length, r.normToOrig);
    expect(origStart).toBe(0);
    expect(origEnd).toBe(text.length);
  });

  it('decodes URL %XX escapes (non-anchor chars)', () => {
    // %53 = 'S', %53%53%4E = 'SSN'
    const text = 'My %53%53%4E is 123-45-6789';
    const r = normalizeForDetection(text);
    expect(r.normalized).toBe('My SSN is 123-45-6789');
  });

  it('preserves email-anchor chars (%40 → kept as %40)', () => {
    // %40 = '@'. F03 mirror — keep encoded so email regex can still
    // anchor on the literal `@` later when the percent form is in
    // the original; currently we drop the decoded `@` rather than
    // emit it.
    const text = 'john%40example.com';
    const r = normalizeForDetection(text);
    // %40 is kept as `%40` literal (we don't decode anchor chars).
    expect(r.normalized).toContain('%40');
  });

  it('decodes HTML numeric entities', () => {
    // &#115; = 's', &#x73; = 's'
    const text = '&#115;ecret &#x73;tring';
    const r = normalizeForDetection(text);
    expect(r.normalized).toBe('secret string');
  });

  it('despaces whitespace-obfuscated phone (≥4 digits gate)', () => {
    const text = 'Call me at + 4 9 1 7 6 5 4 3 today';
    const r = normalizeForDetection(text);
    expect(r.normalized).toContain('+4917654');
  });

  it('does NOT despace prose with sparse digits', () => {
    // Mary J. Doe age 47 with sparse digits — must not despace into
    // a phone-shape run. F02 mirror.
    const text = 'Mary J. Doe age 4 7';
    const r = normalizeForDetection(text);
    // Nothing collapsed — original spaces preserved.
    expect(r.normalized).toBe('Mary J. Doe age 4 7');
  });

  it('1 MB cap returns identity passthrough', () => {
    const big = 'a'.repeat(1_500_000);
    const r = normalizeForDetection(big);
    expect(r.normalized).toBe(big);
    expect(r.normToOrig).toHaveLength(big.length + 1);
  });
});

describe('remapSpan', () => {
  it('maps identity for ASCII passthrough', () => {
    const text = 'hello world';
    const r = normalizeForDetection(text);
    expect(remapSpan(6, 11, r.normToOrig)).toEqual([6, 11]);
  });

  it('clamps to max sentinel rather than truncating', () => {
    // F10 mirror: end == normToOrig.length should NOT lose a char.
    const text = 'abc';
    const r = normalizeForDetection(text);
    // normToOrig = [0, 1, 2, 3]; max idx = 3
    expect(remapSpan(0, r.normalized.length, r.normToOrig)).toEqual([0, 3]);
  });

  it('handles negative inputs by clamping to 0', () => {
    const text = 'abc';
    const r = normalizeForDetection(text);
    expect(remapSpan(-5, 1, r.normToOrig)).toEqual([0, 1]);
  });
});
