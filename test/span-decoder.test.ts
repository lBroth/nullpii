import { describe, expect, it } from 'vitest';
import { decodeSpans } from '../src/span-decoder.js';

describe('decodeSpans', () => {
  it('extracts a multi-token entity from B-I-E', () => {
    const labels = ['O', 'B-private_person', 'I-private_person', 'E-private_person', 'O'];
    const offsets: ReadonlyArray<readonly [number, number]> = [
      [0, 2],
      [3, 7],
      [8, 12],
      [13, 18],
      [19, 23],
    ];
    const scores = [0.9, 0.95, 0.92, 0.93, 0.99];
    const text = 'Hi John Lee Smith now.';
    const spans = decodeSpans(labels, offsets, scores, text);
    expect(spans).toHaveLength(1);
    const span = spans[0];
    expect(span?.label).toBe('private_person');
    expect(span?.start).toBe(3);
    expect(span?.end).toBe(18);
    expect(span?.text).toBe(text.slice(3, 18));
    expect(span?.score).toBeCloseTo((0.95 + 0.92 + 0.93) / 3, 4);
  });

  it('extracts an S-* as a single-token span', () => {
    const labels = ['O', 'S-secret', 'O'];
    const offsets: ReadonlyArray<readonly [number, number]> = [
      [0, 4],
      [5, 11],
      [12, 16],
    ];
    const text = 'said sk-abc next';
    const spans = decodeSpans(labels, offsets, [0.5, 0.97, 0.5], text);
    expect(spans).toHaveLength(1);
    expect(spans[0]?.label).toBe('secret');
    expect(spans[0]?.text).toBe('sk-abc');
  });

  it('emits no spans when all labels are O', () => {
    const spans = decodeSpans(
      ['O', 'O', 'O'],
      [
        [0, 1],
        [1, 2],
        [2, 3],
      ],
      [0.99, 0.99, 0.99],
      'abc',
    );
    expect(spans).toEqual([]);
  });

  it('throws on length mismatch', () => {
    expect(() => decodeSpans(['O'], [], [0.5], '')).toThrow();
  });
});
