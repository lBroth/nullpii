// SPDX-License-Identifier: Apache-2.0

import { DEFAULT_MAX_SPAN_WIDTH } from './gliner-tokenizer.js';

/** All candidate spans for a sequence of `numWords` tokens, enumerated
 * left-to-right with width 0..maxWidth-1 from each start. Mirrors
 * `gliner.data_processing.utils.prepare_span_idx`.
 *
 * Shape returned: flat `[start0, end0, start1, end1, ...]` with
 * `numWords * maxWidth` (start, end) pairs. Caller wraps as
 * `[1, numWords * maxWidth, 2]` tensor for ONNX feed.
 *
 * `end` is the start + offset (1-indexed end exclusive in span lookups).
 * Pairs where `end >= numWords` are out-of-range and the corresponding
 * `spanMask` slot is `false` so the model ignores them.
 */
export interface SpanCandidates {
  /** Flat [start0, end0, start1, end1, ...] — length 2 * numWords * maxWidth. */
  readonly spanIdx: BigInt64Array;
  /** Bool per span (1 = valid, 0 = padding). length = numWords * maxWidth. */
  readonly spanMask: BigInt64Array;
  /** Number of (start, end) candidate pairs. */
  readonly numSpans: number;
  readonly maxWidth: number;
}

/** Generate `span_idx` + `span_mask` for an input of `numWords` words.
 *
 * @param numWords — number of TEXT words in the input (matches
 *   `text_lengths` in the ONNX feed and the GLiNER decoder's `L` dim).
 * @param maxWidth — max span width in words. Default 12 matches
 *   `gliner_config.json.max_width`. */
export function buildSpanCandidates(
  numWords: number,
  maxWidth: number = DEFAULT_MAX_SPAN_WIDTH,
): SpanCandidates {
  const numSpans = numWords * maxWidth;
  const spanIdx = new BigInt64Array(numSpans * 2);
  const spanMask = new BigInt64Array(numSpans);
  // ScatterND in the GLiNER head reads span end indices as gather indices
  // even for masked-out slots, so out-of-range values (`end >= numWords`)
  // crash ORT before the mask is applied. Clamp end to a safe in-range
  // value (0) for masked positions and store the real end only for valid
  // spans. Mirrors the upstream `prepare_span_idx` clamp behavior.
  let p = 0;
  for (let start = 0; start < numWords; start++) {
    for (let offset = 0; offset < maxWidth; offset++) {
      const end = start + offset;
      const valid = end < numWords;
      spanIdx[p * 2] = valid ? BigInt(start) : 0n;
      spanIdx[p * 2 + 1] = valid ? BigInt(end) : 0n;
      spanMask[p] = valid ? 1n : 0n;
      p++;
    }
  }
  return { spanIdx, spanMask, numSpans, maxWidth };
}
