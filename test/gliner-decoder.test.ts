import { describe, expect, it } from 'vitest';
import { decodeGlinerLogits } from '../src/gliner-decoder.js';
import type { Word } from '../src/gliner-tokenizer.js';

const LABELS = ['private_person', 'private_email', 'private_phone'] as const;

const WORDS: Word[] = [
  { text: 'Hi', charStart: 0, charEnd: 2 },
  { text: 'John', charStart: 3, charEnd: 7 },
  { text: 'Smith', charStart: 8, charEnd: 13 },
  { text: 'at', charStart: 14, charEnd: 16 },
  { text: 'a@b.com', charStart: 17, charEnd: 24 },
];

const MAX_WIDTH = 3;
const NUM_CLASSES = 3;
const TEXT_LEN = WORDS.length;

/** Build a logits array of shape [textLength, maxWidth, numClasses] —
 * row-major flatten — with all entries below threshold, then bump
 * specific (start, width, class) positions to high logits. */
function buildLogits(
  highs: ReadonlyArray<{ start: number; width: number; cls: number; logit: number }>,
): Float32Array {
  const flat = new Float32Array(TEXT_LEN * MAX_WIDTH * NUM_CLASSES);
  flat.fill(-10); // sigmoid(-10) ≈ 0
  for (const h of highs) {
    const idx = (h.start * MAX_WIDTH + h.width) * NUM_CLASSES + h.cls;
    flat[idx] = h.logit;
  }
  return flat;
}

describe('decodeGlinerLogits', () => {
  it('returns no spans when all logits are below threshold', () => {
    const logits = new Float32Array(TEXT_LEN * MAX_WIDTH * NUM_CLASSES).fill(-10);
    const spans = decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5);
    expect(spans).toEqual([]);
  });

  it('decodes a single-word span with correct char offsets', () => {
    // High logit at start=1 (John), width=0 → span "John" at [3:7], class 0 (private_person).
    const logits = buildLogits([{ start: 1, width: 0, cls: 0, logit: 10 }]);
    const spans = decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5);
    expect(spans).toHaveLength(1);
    expect(spans[0]).toMatchObject({
      label: 'private_person',
      start: 3,
      end: 7,
    });
    expect(spans[0]?.score).toBeGreaterThan(0.99);
  });

  it('decodes a multi-word span: width=1 covers two words', () => {
    // High logit at start=1 (John), width=1 → span "John Smith" at [3:13].
    const logits = buildLogits([{ start: 1, width: 1, cls: 0, logit: 10 }]);
    const spans = decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5);
    expect(spans).toHaveLength(1);
    expect(spans[0]).toMatchObject({
      label: 'private_person',
      start: 3,
      end: 13,
    });
  });

  it('NMS keeps the higher-score span on overlap', () => {
    // Both span "John Smith" (start=1 w=1) and "Smith" (start=2 w=0)
    // light up. Greedy NMS keeps the higher-score span.
    const logits = buildLogits([
      { start: 1, width: 1, cls: 0, logit: 5 }, // sigmoid ≈ 0.993
      { start: 2, width: 0, cls: 0, logit: 2 }, // sigmoid ≈ 0.881
    ]);
    const spans = decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5);
    expect(spans).toHaveLength(1);
    expect(spans[0]).toMatchObject({ start: 3, end: 13 });
  });

  it('keeps non-overlapping spans of different classes', () => {
    // "John" person + "a@b.com" email — disjoint character ranges.
    const logits = buildLogits([
      { start: 1, width: 0, cls: 0, logit: 5 }, // John
      { start: 4, width: 0, cls: 1, logit: 5 }, // a@b.com
    ]);
    const spans = decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5);
    expect(spans).toHaveLength(2);
    expect(spans.map((s) => s.label).sort()).toEqual(['private_email', 'private_person']);
  });

  it('respects the threshold parameter', () => {
    // logit = 0 → sigmoid = 0.5. Upstream GLiNER convention keeps spans
    // with `score >= threshold`, so a span exactly at the boundary
    // survives.
    const logits = buildLogits([{ start: 1, width: 0, cls: 0, logit: 0 }]);
    expect(
      decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5),
    ).toHaveLength(1);
    // logit = 1 → sigmoid ≈ 0.731 ≥ 0.7 threshold.
    const logits2 = buildLogits([{ start: 1, width: 0, cls: 0, logit: 1 }]);
    expect(
      decodeGlinerLogits(logits2, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.7),
    ).toHaveLength(1);
    // Score strictly below the threshold is dropped.
    const logits3 = buildLogits([{ start: 1, width: 0, cls: 0, logit: -1 }]);
    expect(
      decodeGlinerLogits(logits3, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5),
    ).toEqual([]);
  });

  it('skips spans whose end_word runs past textLength', () => {
    // start=4 (last word), width=2 → end = 6 ≥ textLength (5) → skip.
    const logits = buildLogits([{ start: 4, width: 2, cls: 0, logit: 10 }]);
    const spans = decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5);
    expect(spans).toEqual([]);
  });

  it('throws when labels.length != numClasses', () => {
    const logits = new Float32Array(TEXT_LEN * MAX_WIDTH * NUM_CLASSES);
    expect(() =>
      decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, ['only-one'], 0.5),
    ).toThrow(/labels\.length=1 != numClasses=3/);
  });

  it('output spans are sorted by (start, end)', () => {
    const logits = buildLogits([
      { start: 4, width: 0, cls: 1, logit: 5 },
      { start: 0, width: 0, cls: 0, logit: 5 },
      { start: 2, width: 0, cls: 0, logit: 5 },
    ]);
    const spans = decodeGlinerLogits(logits, TEXT_LEN, MAX_WIDTH, NUM_CLASSES, WORDS, LABELS, 0.5);
    expect(spans.map((s) => s.start)).toEqual([0, 8, 17]);
  });
});
