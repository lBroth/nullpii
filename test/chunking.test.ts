import { describe, expect, it } from 'vitest';
import {
  DEFAULT_MAX_WORDS_PER_CHUNK,
  DEFAULT_WORD_OVERLAP,
  chunkText,
  dedupeOverlappingSpans,
} from '../src/chunking.js';

describe('chunking', () => {
  it('returns single chunk when word count fits', () => {
    const out = chunkText('short text');
    expect(out).toEqual([{ text: 'short text', offset: 0 }]);
  });

  it('splits long text on word boundaries with overlap', () => {
    const words = Array.from({ length: 500 }, (_, i) => `word${i}`).join(' ');
    const out = chunkText(words, 100, 20);
    expect(out.length).toBeGreaterThan(2);
    // First chunk starts at offset 0
    expect(out[0]?.offset).toBe(0);
    // Each chunk should preserve word boundaries (start at a word, not mid-word)
    for (const chunk of out) {
      expect(chunk.text.charAt(0)).toMatch(/\S/);
    }
  });

  it('default constants leave headroom for the merged-LoRA ONNX cap', () => {
    expect(DEFAULT_MAX_WORDS_PER_CHUNK).toBe(180);
    expect(DEFAULT_WORD_OVERLAP).toBe(30);
  });

  it('rejects overlap >= max words', () => {
    expect(() => chunkText('a '.repeat(300), 100, 100)).toThrow(RangeError);
  });

  it('preserves global offsets across chunks', () => {
    const words = Array.from({ length: 500 }, (_, i) => `tok${i}`).join(' ');
    const out = chunkText(words, 100, 20);
    for (const chunk of out) {
      expect(words.slice(chunk.offset, chunk.offset + chunk.text.length)).toBe(chunk.text);
    }
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
