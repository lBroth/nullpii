// SPDX-License-Identifier: Apache-2.0
//
// `segmentWindows`: the overlapping windows `sanitize()` reads a text
// longer than `MAX_INPUT_CHARS` in.

import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { type Segment, segmentWindows } from '../src/segments.js';

const MAX = 100;
const OVERLAP = 20;

/** The invariants every result must hold. */
function expectCovering(text: string, windows: Segment[], max: number, overlap: number): void {
  expect(windows[0]?.start).toBe(0);
  expect(windows.at(-1)?.end).toBe(text.length);
  for (const [i, w] of windows.entries()) {
    expect(w.end - w.start).toBeLessThanOrEqual(max);
    if (text.length > 0) expect(w.end).toBeGreaterThan(w.start);
    const next = windows[i + 1];
    if (next === undefined) continue;
    expect(next.start).toBeGreaterThan(w.start);
    expect(w.end - next.start).toBeGreaterThanOrEqual(overlap);
  }
}

describe('segmentWindows', () => {
  it('returns one window for a text that fits', () => {
    expect(segmentWindows('x'.repeat(MAX), MAX, OVERLAP)).toEqual([{ start: 0, end: MAX }]);
    expect(segmentWindows('', MAX, OVERLAP)).toEqual([{ start: 0, end: 0 }]);
  });

  it('ends a window after a line break in its last quarter', () => {
    const text = `${'a'.repeat(89)}\n${'b'.repeat(200)}`;
    const [first] = segmentWindows(text, MAX, OVERLAP);
    expect(first).toEqual({ start: 0, end: 90 });
  });

  it('falls back to whitespace, then to a hard cut', () => {
    const spaced = `${'a'.repeat(84)} ${'b'.repeat(200)}`;
    expect(segmentWindows(spaced, MAX, OVERLAP)[0]).toEqual({ start: 0, end: 85 });
    const solid = 'c'.repeat(300);
    expect(segmentWindows(solid, MAX, OVERLAP)[0]).toEqual({ start: 0, end: MAX });
    expectCovering(solid, segmentWindows(solid, MAX, OVERLAP), MAX, OVERLAP);
  });

  it('ignores a line break before the last quarter', () => {
    const text = `${'a'.repeat(50)}\n${'b'.repeat(300)}`;
    expect(segmentWindows(text, MAX, OVERLAP)[0]).toEqual({ start: 0, end: MAX });
  });

  it('never cuts a surrogate pair', () => {
    const text = '😀'.repeat(400);
    for (const w of segmentWindows(text, 101, OVERLAP)) {
      expect(w.start % 2).toBe(0);
      expect(w.end % 2).toBe(0);
    }
  });

  it('refuses an overlap that leaves no progress', () => {
    expect(() => segmentWindows('x', MAX, 0)).toThrow(RangeError);
    expect(() => segmentWindows('x', MAX, 26)).toThrow(RangeError);
  });

  it('covers any text with windows that overlap enough', () => {
    const chars = fc.constantFrom('a', 'b', ' ', '\n', '😀', '\t');
    fc.assert(
      fc.property(fc.array(chars, { maxLength: 2_000 }), (parts) => {
        const text = parts.join('');
        expectCovering(text, segmentWindows(text, MAX, OVERLAP), MAX, OVERLAP);
      }),
    );
  });

  it('starts the next window where a run cut by a hard end starts', () => {
    // 140 characters of words, then a 90-character run over the first
    // window's last quarter (150 to 200), so the first window ends inside it.
    const text = `${'a '.repeat(70)}${'x'.repeat(90)} ${'b '.repeat(100)}`;
    const [first, second] = segmentWindows(text, 200, OVERLAP);
    expect(first).toEqual({ start: 0, end: 200 });
    expect(second?.start).toBe(140);
    expect(second?.end).toBeGreaterThanOrEqual(230);
  });

  it('puts a run with no whitespace of up to half a window whole inside one window', () => {
    const max = 200;
    const overlap = 20;
    fc.assert(
      fc.property(
        fc.string({ unit: fc.constantFrom('a', ' ', '\n'), maxLength: 1_500 }),
        fc.nat(),
        fc.integer({ min: 1, max: max / 2 }),
        (around, at, length) => {
          const cut = at % (around.length + 1);
          const text = `${around.slice(0, cut)} ${'x'.repeat(length)} ${around.slice(cut)}`;
          const windows = segmentWindows(text, max, overlap);
          expectCovering(text, windows, max, overlap);
          const start = cut + 1;
          expect(windows.some((w) => w.start <= start && start + length <= w.end)).toBe(true);
        },
      ),
    );
  });

  it('puts every value shorter than the overlap whole inside one window', () => {
    fc.assert(
      fc.property(
        fc.string({ unit: fc.constantFrom('a', ' ', '\n'), maxLength: 1_500 }),
        fc.nat(),
        fc.integer({ min: 1, max: OVERLAP - 1 }),
        (text, at, length) => {
          const start = text.length === 0 ? 0 : at % text.length;
          const end = Math.min(text.length, start + length);
          const windows = segmentWindows(text, MAX, OVERLAP);
          expect(windows.some((w) => w.start <= start && end <= w.end)).toBe(true);
        },
      ),
    );
  });
});
