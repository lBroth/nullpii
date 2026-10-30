// SPDX-License-Identifier: Apache-2.0

import { type Word, splitWords } from './gliner-tokenizer.js';
import { type Interval, iou } from './iou.js';
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

/** One model window: a slice of the text and the number of words it spans. */
export interface WordWindow extends TextChunk {
  readonly wordCount: number;
}

/** Outcome of {@link forEachWindow}. */
export interface WindowWalk {
  readonly windows: number;
  /** Words no window could consume: each alone exceeds the encoder budget. */
  readonly unscannedWords: number;
  /** Those words' char ranges in the text, in order. */
  readonly unscanned: readonly Interval[];
}

function assertOverlap(maxWords: number, overlapWords: number): void {
  if (overlapWords >= maxWords) {
    throw new RangeError(`overlapWords (${overlapWords}) must be < maxWords (${maxWords})`);
  }
}

function windowAt(
  text: string,
  words: readonly Word[],
  cursor: number,
  maxWords: number,
): WordWindow {
  if (cursor === 0 && words.length <= maxWords) {
    return { text, offset: 0, wordCount: words.length };
  }
  const end = Math.min(cursor + maxWords, words.length);
  const start = words[cursor]?.charStart ?? text.length;
  const stop = end < words.length ? (words[end]?.charStart ?? text.length) : text.length;
  return { text: text.slice(start, stop), offset: start, wordCount: end - cursor };
}

/** The char range of `words[index]`, which must exist. */
function wordRange(words: readonly Word[], index: number): Interval {
  const word = words[index];
  if (word === undefined) {
    throw new RangeError(`word ${index} out of range (${words.length} words)`);
  }
  return { start: word.charStart, end: word.charEnd };
}

/** Where the next window starts after the encoder kept only `seen` of a window's words. */
function nextAfterCut(cursor: number, seen: number, overlapWords: number): number {
  if (seen > overlapWords) return cursor + seen - overlapWords;
  return cursor + Math.max(1, seen);
}

/**
 * Walk `text` in overlapping word windows, advancing by what the encoder
 * actually consumed. `visit` returns how many leading words of the window
 * the encoder kept; the rest were cut by its subword budget.
 *
 * A fixed stride (as in {@link chunkText}) silently skips the tail of a
 * cut window whenever more than `overlapWords` words were dropped, which
 * happens on dense text such as logs full of long tokens. Here the next
 * window restarts `overlapWords` before the last kept word, so every word
 * reaches the model unless it alone exceeds the budget (counted in
 * `unscannedWords`). When no window is cut, the windows are exactly
 * `chunkText`'s.
 */
export async function forEachWindow(
  text: string,
  visit: (window: WordWindow) => Promise<number>,
  maxWords: number = DEFAULT_MAX_WORDS_PER_CHUNK,
  overlapWords: number = DEFAULT_WORD_OVERLAP,
): Promise<WindowWalk> {
  assertOverlap(maxWords, overlapWords);
  const words = splitWords(text);
  let cursor = 0;
  let windows = 0;
  const unscanned: Interval[] = [];
  for (;;) {
    const window = windowAt(text, words, cursor, maxWords);
    const seen = await visit(window);
    windows += 1;
    if (seen >= window.wordCount) {
      if (cursor + window.wordCount >= words.length) break;
      cursor += maxWords - overlapWords;
      continue;
    }
    if (seen === 0) unscanned.push(wordRange(words, cursor));
    cursor = nextAfterCut(cursor, seen, overlapWords);
    if (cursor >= words.length) break;
  }
  return { windows, unscannedWords: unscanned.length, unscanned };
}

export function chunkText(
  text: string,
  maxWords: number = DEFAULT_MAX_WORDS_PER_CHUNK,
  overlapWords: number = DEFAULT_WORD_OVERLAP,
): TextChunk[] {
  assertOverlap(maxWords, overlapWords);
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
 * different labels at the same offset are kept (rare with chunking).
 *
 * A duplicate gives up its label and score, never its characters: the
 * kept span grows to the union of both, so text that only the duplicate
 * covered is not left unmasked. Fields derived from offsets (a span's
 * `text`) are not updated here; callers re-derive them. */
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
  const near = new SpanBuckets();
  const matches = (s: T) => (k: T) =>
    (acrossLabels || k.label === s.label) && iou(s, k) >= iouThreshold;
  for (const s of sorted) {
    // A positive threshold needs an overlap, so only kept spans near `s`
    // can match; the first match in `kept` order wins, as a scan would.
    const i = iouThreshold > 0 ? near.firstIndex(s, kept, matches(s)) : kept.findIndex(matches(s));
    const keeper = kept[i];
    if (keeper === undefined) {
      kept.push(s);
      near.add(kept.length - 1, s);
      continue;
    }
    if (s.start < keeper.start || s.end > keeper.end) {
      kept[i] = {
        ...keeper,
        start: Math.min(keeper.start, s.start),
        end: Math.max(keeper.end, s.end),
      };
      near.add(i, kept[i] as T);
    }
  }
  return kept.sort((a, b) => a.start - b.start);
}

/** Width, in characters, of one bucket of `SpanBuckets`. */
const BUCKET_CHARS = 1024;

/** Indices of spans by the fixed-width buckets their characters fall in,
 * so finding the spans that overlap one span does not scan them all. A
 * span that grows is added again; its old buckets stay inside its range. */
class SpanBuckets {
  private readonly buckets = new Map<number, number[]>();

  add(index: number, span: Interval): void {
    for (let b = bucketOf(span.start); b <= bucketOf(span.end); b++) {
      const list = this.buckets.get(b);
      if (list === undefined) this.buckets.set(b, [index]);
      else list.push(index);
    }
  }

  /** The lowest index in `spans` that shares a bucket with `span` and
   * passes `test`, else -1. */
  firstIndex<T>(span: Interval, spans: readonly T[], test: (k: T) => boolean): number {
    let best = -1;
    for (let b = bucketOf(span.start); b <= bucketOf(span.end); b++) {
      for (const i of this.buckets.get(b) ?? []) {
        if ((best === -1 || i < best) && test(spans[i] as T)) best = i;
      }
    }
    return best;
  }
}

function bucketOf(offset: number): number {
  return Math.floor(offset / BUCKET_CHARS);
}

function removeContainedSpans<T extends ScoredSpan>(spans: T[]): T[] {
  // A span is dropped when another one is strictly larger and covers it:
  // one that starts earlier and ends no earlier, or starts at the same
  // offset and ends later. Equal bounds fall through to the IoU pass, so
  // the highest score wins on ties. One sweep in (start, -end) order.
  const order = spans.map((_, i) => i);
  order.sort((x, y) => startOf(spans, x) - startOf(spans, y) || endOf(spans, y) - endOf(spans, x));
  const contained = new Uint8Array(spans.length);
  let maxEndBefore = Number.NEGATIVE_INFINITY;
  let groupStart = Number.NaN;
  let groupEnd = Number.NEGATIVE_INFINITY;
  for (const i of order) {
    const a = spans[i];
    if (!a) continue;
    if (a.start !== groupStart) {
      maxEndBefore = Math.max(maxEndBefore, groupEnd);
      groupStart = a.start;
      groupEnd = a.end;
    }
    if (maxEndBefore >= a.end || groupEnd > a.end) contained[i] = 1;
  }
  return spans.filter((a, i) => a !== undefined && contained[i] === 0);
}

function startOf(spans: readonly ScoredSpan[], i: number): number {
  return spans[i]?.start ?? 0;
}

function endOf(spans: readonly ScoredSpan[], i: number): number {
  return spans[i]?.end ?? 0;
}
