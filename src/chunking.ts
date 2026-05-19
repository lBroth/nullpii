// SPDX-License-Identifier: Apache-2.0

import { splitWords } from './gliner-tokenizer.js';
import { iou } from './iou.js';
import type { ScoredSpan } from './types/scored-span.js';

/** Word-aware sliding-window chunker. Splits on GLiNER word boundaries
 * so each chunk has a bounded word count regardless of input density.
 * Chunks overlap by `overlapWords`; caller dedupes via
 * `dedupeOverlappingSpans`. */
export interface TextChunk {
  readonly text: string;
  readonly offset: number;
}

// 140 holds across the bench surface — merged-LoRA ONNX ScatterND_1
// crashes at content-dependent thresholds (~172–212 words observed).
export const DEFAULT_MAX_WORDS_PER_CHUNK = 140;
export const DEFAULT_WORD_OVERLAP = 30;

export function chunkText(
  text: string,
  maxWords: number = DEFAULT_MAX_WORDS_PER_CHUNK,
  overlapWords: number = DEFAULT_WORD_OVERLAP,
): TextChunk[] {
  if (overlapWords >= maxWords) {
    throw new RangeError(`overlapWords (${overlapWords}) must be < maxWords (${maxWords})`);
  }
  const words = splitWords(text);
  if (words.length <= maxWords) return [{ text, offset: 0 }];

  const chunks: TextChunk[] = [];
  const stride = maxWords - overlapWords;
  for (let start = 0; start < words.length; start += stride) {
    const end = Math.min(start + maxWords, words.length);
    const startWord = words[start];
    if (!startWord) break;
    const chunkStart = startWord.charStart;
    const chunkEnd = end < words.length ? (words[end]?.charStart ?? text.length) : text.length;
    chunks.push({ text: text.slice(chunkStart, chunkEnd), offset: chunkStart });
    if (end === words.length) break;
  }
  return chunks;
}

/** Dedupe overlapping spans by IoU. Keeps the highest-score span in each
 * overlap cluster. Spans must share `label` to be considered duplicates;
 * different labels at the same offset are kept (rare with chunking). */
export function dedupeOverlappingSpans<T extends ScoredSpan>(
  spans: T[],
  iouThreshold = 0.5,
  options: { acrossLabels?: boolean } = {},
): T[] {
  if (spans.length <= 1) return [...spans];
  const acrossLabels = options.acrossLabels === true;
  // Two-pass strategy:
  //   1. Containment pass — drop any span fully inside another (any
  //      label combo). The outer span carries the structurally-richer
  //      pattern (e.g. recognizer email `<local>@<domain>` containing
  //      ML's partial-token guess). Containment-elimination is
  //      independent of score.
  //   2. IoU pass on the survivors — score-weighted dedupe of partial
  //      overlaps, with `acrossLabels` controlling whether different
  //      labels at the same offsets collapse.
  const survivors = removeContainedSpans(spans);
  // Sort by score desc, with stable tie-break on (start asc, end asc,
  // label asc) so two spans at identical (start, end, label, score)
  // resolve to a deterministic order regardless of insertion sequence.
  const sorted = [...survivors].sort(
    (a, b) =>
      b.score - a.score || a.start - b.start || a.end - b.end || a.label.localeCompare(b.label),
  );
  const kept: T[] = [];
  for (const s of sorted) {
    let isDup = false;
    for (const k of kept) {
      if (!acrossLabels && k.label !== s.label) continue;
      if (iou(s, k) >= iouThreshold) {
        isDup = true;
        break;
      }
    }
    if (!isDup) kept.push(s);
  }
  return kept.sort((a, b) => a.start - b.start);
}

function removeContainedSpans<T extends ScoredSpan>(spans: T[]): T[] {
  const out: T[] = [];
  for (let i = 0; i < spans.length; i++) {
    const a = spans[i];
    if (!a) continue;
    let contained = false;
    for (let j = 0; j < spans.length; j++) {
      if (i === j) continue;
      const b = spans[j];
      if (!b) continue;
      // a is strictly contained in b (proper subset). Equal-bounds spans
      // fall through to the IoU pass so highest score wins on ties.
      if (b.start <= a.start && b.end >= a.end && b.end - b.start > a.end - a.start) {
        contained = true;
        break;
      }
    }
    if (!contained) out.push(a);
  }
  return out;
}
