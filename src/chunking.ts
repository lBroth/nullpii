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

// Empirically the merged-LoRA ONNX ScatterND_1 op crashes on inputs
// where words_mask values exceed `text_lengths`, which happens when
// our tokenizer's subword-level truncation (max_len=384) drops the
// trailing word mid-token: numWords still counts the partial word but
// words_mask kept the higher index. 180 sits comfortably under the
// observed crash thresholds (199–212 across runs) and absorbs noise.
export const DEFAULT_MAX_WORDS_PER_CHUNK = 180;
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

export function dedupeOverlappingSpans<T extends SpanLike>(spans: T[], iouThreshold = 0.5): T[] {
  if (spans.length <= 1) return [...spans];
  const sorted = [...spans].sort((a, b) => b.score - a.score);
  const kept: T[] = [];
  for (const s of sorted) {
    let isDup = false;
    for (const k of kept) {
      if (k.label !== s.label) continue;
      if (iou(s, k) >= iouThreshold) {
        isDup = true;
        break;
      }
    }
    if (!isDup) kept.push(s);
  }
  return kept.sort((a, b) => a.start - b.start);
}

function iou(a: SpanLike, b: SpanLike): number {
  const interStart = Math.max(a.start, b.start);
  const interEnd = Math.min(a.end, b.end);
  const inter = Math.max(0, interEnd - interStart);
  if (inter === 0) return 0;
  const union = a.end - a.start + (b.end - b.start) - inter;
  return inter / union;
}
