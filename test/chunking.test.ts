// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { dedupeSpans, partitionTokens } from '../src/chunking.js';
import type { EncodeResult } from '../src/tokenizer.js';
import type { PiiSpan } from '../src/types/index.js';

function fakeEnc(n: number): EncodeResult {
  const ids = new BigInt64Array(n);
  const mask = new BigInt64Array(n);
  const offsets: Array<readonly [number, number]> = [];
  for (let i = 0; i < n; i++) {
    ids[i] = BigInt(1000 + i);
    mask[i] = 1n;
    offsets.push([i * 4, i * 4 + 4] as const);
  }
  return { inputIds: ids, attentionMask: mask, offsetMapping: offsets };
}

describe('partitionTokens', () => {
  it('returns the full encoding as one chunk when fits', () => {
    const enc = fakeEnc(200);
    const chunks = partitionTokens(enc, 512, 64);
    expect(chunks).toHaveLength(1);
    expect(chunks[0]?.inputIds.length).toBe(200);
  });

  it('splits oversized inputs with the requested overlap', () => {
    const enc = fakeEnc(1100);
    const chunks = partitionTokens(enc, 500, 100);
    // stride=400 → starts at 0, 400, 800. Last chunk hits end at 1100.
    expect(chunks).toHaveLength(3);
    expect(chunks[0]?.inputIds.length).toBe(500);
    expect(chunks[1]?.inputIds.length).toBe(500);
    expect(chunks[2]?.inputIds.length).toBe(300);
  });

  it('preserves original char offsets in each chunk', () => {
    const enc = fakeEnc(800);
    const chunks = partitionTokens(enc, 400, 50);
    expect(chunks[0]?.offsetMapping[0]).toEqual([0, 4]);
    // chunk 1 starts at token index 350 (400-50)
    expect(chunks[1]?.offsetMapping[0]).toEqual([350 * 4, 350 * 4 + 4]);
  });

  it('rejects invalid overlap values', () => {
    const enc = fakeEnc(100);
    expect(() => partitionTokens(enc, 50, 50)).toThrow();
    expect(() => partitionTokens(enc, 50, -1)).toThrow();
    expect(() => partitionTokens(enc, 0, 0)).toThrow();
  });
});

describe('dedupeSpans', () => {
  const span = (label: string, start: number, end: number, score = 0.9): PiiSpan => ({
    label: label as PiiSpan['label'],
    start,
    end,
    score,
    text: 'x',
  });

  it('drops exact duplicates from overlapping chunks', () => {
    const spans = [span('private_email', 10, 25), span('private_email', 10, 25)];
    expect(dedupeSpans(spans)).toHaveLength(1);
  });

  it('keeps the longest of overlapping same-label spans', () => {
    const spans = [span('private_person', 0, 5, 0.7), span('private_person', 0, 12, 0.6)];
    const out = dedupeSpans(spans);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ start: 0, end: 12 });
  });

  it('breaks ties on score when lengths match', () => {
    const spans = [span('private_email', 0, 10, 0.4), span('private_email', 0, 10, 0.95)];
    const out = dedupeSpans(spans);
    expect(out).toHaveLength(1);
    expect(out[0]?.score).toBeCloseTo(0.95);
  });

  it('preserves overlapping spans with different labels', () => {
    const spans = [span('private_person', 0, 10), span('private_email', 5, 15)];
    expect(dedupeSpans(spans)).toHaveLength(2);
  });

  it('returns spans sorted by start', () => {
    const spans = [span('private_email', 80, 95), span('private_person', 0, 5)];
    const out = dedupeSpans(spans);
    expect(out[0]?.start).toBe(0);
    expect(out[1]?.start).toBe(80);
  });
});
