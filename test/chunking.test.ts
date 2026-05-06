import { describe, expect, it } from 'vitest';
import {
  DEFAULT_CHUNK_CHARS,
  DEFAULT_OVERLAP_CHARS,
  chunkText,
  dedupeOverlappingSpans,
} from '../src/chunking.js';

describe('chunking', () => {
  it('returns single chunk when text fits', () => {
    const out = chunkText('short text');
    expect(out).toEqual([{ text: 'short text', offset: 0 }]);
  });

  it('splits long text with overlap', () => {
    const text = 'x'.repeat(2500);
    const out = chunkText(text, 1000, 200);
    expect(out.length).toBeGreaterThan(2);
    expect(out[0]).toEqual({ text: 'x'.repeat(1000), offset: 0 });
    expect(out[1]?.offset).toBe(800);
    expect(out[2]?.offset).toBe(1600);
    expect(out.at(-1)?.offset).toBeLessThanOrEqual(text.length);
  });

  it('default chunk + overlap leave headroom for the merged-LoRA ONNX cap', () => {
    expect(DEFAULT_CHUNK_CHARS).toBe(600);
    expect(DEFAULT_OVERLAP_CHARS).toBe(100);
  });

  it('rejects overlap >= chunk size', () => {
    expect(() => chunkText('x'.repeat(2000), 100, 100)).toThrow(RangeError);
  });

  it('preserves global offsets across chunks', () => {
    const text = `${'a'.repeat(900)}EMAIL@x.com${'b'.repeat(800)}`;
    const out = chunkText(text, 900, 200);
    expect(out.length).toBe(3);
    const chunk1 = out[1];
    if (!chunk1) throw new Error('expected chunk index 1');
    expect(text.slice(chunk1.offset, chunk1.offset + chunk1.text.length)).toBe(chunk1.text);
  });
});

describe('dedupeOverlappingSpans', () => {
  it('keeps highest score across overlapping duplicates', () => {
    const spans = [
      { label: 'private_email', start: 0, end: 13, score: 0.8 },
      { label: 'private_email', start: 0, end: 13, score: 0.95 },
      { label: 'private_email', start: 0, end: 13, score: 0.7 },
    ];
    expect(dedupeOverlappingSpans(spans)).toEqual([
      { label: 'private_email', start: 0, end: 13, score: 0.95 },
    ]);
  });

  it('preserves non-overlapping spans', () => {
    const spans = [
      { label: 'private_email', start: 0, end: 13, score: 0.9 },
      { label: 'private_email', start: 100, end: 115, score: 0.8 },
    ];
    expect(dedupeOverlappingSpans(spans)).toHaveLength(2);
  });

  it('keeps spans with different labels at same offset', () => {
    const spans = [
      { label: 'private_person', start: 0, end: 10, score: 0.9 },
      { label: 'private_email', start: 0, end: 10, score: 0.8 },
    ];
    expect(dedupeOverlappingSpans(spans)).toHaveLength(2);
  });

  it('returns empty for empty input', () => {
    expect(dedupeOverlappingSpans([])).toEqual([]);
  });

  it('sorts output by start offset', () => {
    const spans = [
      { label: 'private_email', start: 100, end: 115, score: 0.7 },
      { label: 'private_email', start: 0, end: 13, score: 0.9 },
    ];
    const out = dedupeOverlappingSpans(spans);
    expect(out.map((s) => s.start)).toEqual([0, 100]);
  });
});
