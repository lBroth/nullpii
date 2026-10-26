// SPDX-License-Identifier: Apache-2.0
//
// The span passes were made linear for long texts (a text over
// MAX_INPUT_CHARS can carry 100k spans). Their output must not change:
// each is compared with the quadratic version it replaced, on random spans.

import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { dedupeOverlappingSpans } from '../src/chunking.js';
import { iou } from '../src/iou.js';
import type { PiiSpan } from '../src/types/index.js';
import { otherPiiIndex } from '../src/url-filter.js';

type Span = { start: number; end: number; label: string; score: number };

/** `dedupeOverlappingSpans` as it was before the linear passes. */
function dedupeReference<T extends Span>(
  spans: T[],
  iouThreshold = 0.5,
  acrossLabels = false,
): T[] {
  if (spans.length <= 1) return [...spans];
  const survivors: T[] = [];
  for (let i = 0; i < spans.length; i++) {
    const a = spans[i] as T;
    let contained = false;
    for (let j = 0; j < spans.length; j++) {
      if (i === j) continue;
      const b = spans[j] as T;
      if (b.start <= a.start && b.end >= a.end && b.end - b.start > a.end - a.start) {
        contained = true;
        break;
      }
    }
    if (!contained) survivors.push(a);
  }
  const sorted = [...survivors].sort(
    (a, b) =>
      b.score - a.score || a.start - b.start || a.end - b.end || a.label.localeCompare(b.label),
  );
  const kept: T[] = [];
  for (const s of sorted) {
    const i = kept.findIndex(
      (k) => (acrossLabels || k.label === s.label) && iou(s, k) >= iouThreshold,
    );
    const keeper = kept[i];
    if (keeper === undefined) {
      kept.push(s);
      continue;
    }
    if (s.start < keeper.start || s.end > keeper.end) {
      kept[i] = {
        ...keeper,
        start: Math.min(keeper.start, s.start),
        end: Math.max(keeper.end, s.end),
      };
    }
  }
  return kept.sort((a, b) => a.start - b.start);
}

/** Spans in a small space, so overlaps, containments and ties are common;
 * some spans are long enough to cross several 1,024-character buckets. */
const spanArb = fc
  .record({
    start: fc.integer({ min: 0, max: 5_000 }),
    length: fc.oneof(fc.integer({ min: 0, max: 40 }), fc.integer({ min: 0, max: 3_000 })),
    label: fc.constantFrom('private_email', 'private_person', 'secret'),
    score: fc.constantFrom(0.3, 0.5, 0.7, 0.99),
  })
  .map(({ start, length, label, score }) => ({ start, end: start + length, label, score }));

describe('linear span passes give the same output as the quadratic ones', () => {
  it('dedupeOverlappingSpans', () => {
    fc.assert(
      fc.property(
        fc.array(spanArb, { maxLength: 120 }),
        fc.constantFrom(0.5, 0.3, 1, 0),
        fc.boolean(),
        (spans, threshold, acrossLabels) => {
          expect(dedupeOverlappingSpans(spans, threshold, { acrossLabels })).toEqual(
            dedupeReference(spans, threshold, acrossLabels),
          );
        },
      ),
      { numRuns: 500 },
    );
  });

  it('the URL filter test for other PII touching a URL', () => {
    const urlArb = spanArb.map((s) => ({ ...s, label: 'private_url' }));
    fc.assert(
      fc.property(
        fc.array(fc.oneof(spanArb, urlArb), { maxLength: 80 }),
        fc.integer({ min: 0, max: 6_000 }),
        fc.integer({ min: 0, max: 400 }),
        (spans, start, length) => {
          const all = spans.map((s) => ({ ...s, text: '' })) as PiiSpan[];
          const naive = all.some(
            (t) => t.label !== 'private_url' && t.start < start + length && t.end > start,
          );
          expect(otherPiiIndex(all)(start, start + length)).toBe(naive);
        },
      ),
      { numRuns: 500 },
    );
  });
});
