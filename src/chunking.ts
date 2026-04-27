// SPDX-License-Identifier: Apache-2.0
import type { EncodeResult } from './tokenizer.js';
import type { PiiSpan } from './types/index.js';

/** A single window emitted by `partitionTokens`. Slices of the underlying
 * tokenizer output, with `offsetMapping` already aligned to the original
 * (escaped) text — so spans decoded inside the chunk land in original char
 * coordinates without remapping. */
export interface TokenChunk {
  readonly inputIds: BigInt64Array;
  readonly attentionMask: BigInt64Array;
  readonly offsetMapping: ReadonlyArray<readonly [number, number]>;
}

/**
 * Split a tokenized input into overlapping windows.
 *
 * Each window has at most `chunkSize` tokens; consecutive windows share
 * `overlap` tokens at the boundary so that any span shorter than the
 * overlap is fully visible in at least one chunk.
 *
 * No-op (single-element array) when the input fits in one chunk.
 */
export function partitionTokens(
  enc: EncodeResult,
  chunkSize: number,
  overlap: number,
): TokenChunk[] {
  if (chunkSize <= 0) throw new Error(`partitionTokens: chunkSize must be > 0, got ${chunkSize}`);
  if (overlap < 0 || overlap >= chunkSize) {
    throw new Error(`partitionTokens: overlap must be in [0, ${chunkSize}), got ${overlap}`);
  }
  const total = enc.inputIds.length;
  if (total <= chunkSize) {
    return [
      {
        inputIds: enc.inputIds,
        attentionMask: enc.attentionMask,
        offsetMapping: enc.offsetMapping,
      },
    ];
  }
  const stride = chunkSize - overlap;
  const out: TokenChunk[] = [];
  for (let start = 0; start < total; start += stride) {
    const end = Math.min(start + chunkSize, total);
    out.push({
      inputIds: enc.inputIds.slice(start, end),
      attentionMask: enc.attentionMask.slice(start, end),
      offsetMapping: enc.offsetMapping.slice(start, end),
    });
    if (end === total) break;
  }
  return out;
}

/**
 * Deduplicate spans collected from overlapping chunks.
 *
 * Strategy:
 * 1. Drop exact duplicates (same `start`, `end`, `label`).
 * 2. For overlapping spans of the same label, keep the longest; ties go
 *    to the higher-confidence span. Spans with different labels survive
 *    overlap (caller can resolve).
 *
 * Result is sorted by `start` ascending.
 */
export function dedupeSpans(spans: readonly PiiSpan[]): PiiSpan[] {
  if (spans.length <= 1) return [...spans];
  const sorted = [...spans].sort((a, b) => a.start - b.start || b.end - a.end || b.score - a.score);
  const out: PiiSpan[] = [];
  for (const s of sorted) {
    let merged = false;
    for (let i = out.length - 1; i >= 0; i--) {
      const prev = out[i];
      if (prev === undefined) continue;
      if (prev.end <= s.start) break;
      if (prev.label !== s.label) continue;
      const prevLen = prev.end - prev.start;
      const sLen = s.end - s.start;
      if (sLen > prevLen || (sLen === prevLen && s.score > prev.score)) {
        out[i] = s;
      }
      merged = true;
      break;
    }
    if (!merged) out.push(s);
  }
  return out.sort((a, b) => a.start - b.start);
}
