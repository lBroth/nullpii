// SPDX-License-Identifier: Apache-2.0

import { splitWords } from './gliner-tokenizer.js';

/** Word-aware sliding-window chunker. Splits on GLiNER word boundaries
 * so each chunk has a bounded word count regardless of input density
 * (prose, code, env-var dumps, JSON — all chunk to the same word
 * budget). Char chunking is unsafe because punctuation each becomes
 * a word in the GLiNER tokenizer; a 900-char prose chunk has ~150
 * words, the same length of dense JSON has ~250.
 *
 * Chunks overlap by `overlapWords` words so spans straddling a chunk
 * boundary are detectable in at least one chunk. The caller is
 * responsible for deduping overlapping spans across chunks (see
 * `dedupeOverlappingSpans`).
 */
export interface TextChunk {
  /** Chunk text passed to the model. */
  readonly text: string;
  /** Char offset of this chunk within the source string. */
  readonly offset: number;
}

// The merged-LoRA ONNX export carries content-dependent caps in the
// GLiNER head (ScatterND_1 indice errors observed at 172–212 across
// inputs; dash-heavy or punctuation-dense content lowers the safe
// limit). 140 is the empirical floor that holds across the bench
// surface (nullpii-bench long-prompts + ai4privacy-300k-heldout German
// dash-banner inputs) — small enough to absorb worst-case input
// density, large enough to keep span-boundary recall reasonable.
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
export interface SpanLike {
  readonly label: string;
  readonly start: number;
  readonly end: number;
  readonly score: number;
}

export function dedupeOverlappingSpans<T extends SpanLike>(
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
  const sorted = [...survivors].sort((a, b) => b.score - a.score);
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

function removeContainedSpans<T extends SpanLike>(spans: T[]): T[] {
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

function iou(a: SpanLike, b: SpanLike): number {
  const interStart = Math.max(a.start, b.start);
  const interEnd = Math.min(a.end, b.end);
  const inter = Math.max(0, interEnd - interStart);
  if (inter === 0) return 0;
  const union = a.end - a.start + (b.end - b.start) - inter;
  return inter / union;
}
