import { describe, expect, it } from 'vitest';
import { buildSpanCandidates } from '../src/gliner-spans.js';

describe('gliner-spans / buildSpanCandidates', () => {
  it('emits numWords × maxWidth (start, end) pairs with correct flat layout', () => {
    const cand = buildSpanCandidates(3, 2);
    expect(cand.numSpans).toBe(6);
    expect(cand.maxWidth).toBe(2);
    // Flat shape: [start0, end0, start1, end1, …]. Width 0 = single-token span;
    // width 1 = two-token span (start, start+1).
    expect(Array.from(cand.spanIdx, (n) => Number(n))).toEqual([
      0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3,
    ]);
  });

  it('span_mask zeroes spans that overrun numWords', () => {
    const cand = buildSpanCandidates(3, 2);
    // Width-1 from start 2 lands at end=3 → out-of-range (numWords = 3).
    expect(Array.from(cand.spanMask, (n) => Number(n))).toEqual([1, 1, 1, 1, 1, 0]);
  });

  it('uses default max span width 12 when omitted', () => {
    const cand = buildSpanCandidates(5);
    expect(cand.maxWidth).toBe(12);
    expect(cand.numSpans).toBe(60);
  });

  it('handles numWords = 0 gracefully', () => {
    const cand = buildSpanCandidates(0, 4);
    expect(cand.numSpans).toBe(0);
    expect(cand.spanIdx.length).toBe(0);
    expect(cand.spanMask.length).toBe(0);
  });
});
