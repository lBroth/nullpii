// SPDX-License-Identifier: Apache-2.0

/** Sliding-window chunker for inputs longer than the GLiNER model's
 * static capacity. Mirrors the bench-side 1400/200 char stride used by
 * `gliner_lora_predictor` in `packages/eval/src/nullpii_eval/adapters.py`,
 * so the npm runtime and the Python re-impl handle long inputs the
 * same way.
 *
 * Chunks overlap by `overlapChars` so spans straddling a chunk boundary
 * are detectable in at least one chunk. The caller is responsible for
 * deduping overlapping spans across chunks (see `dedupeOverlappingSpans`).
 */
export interface TextChunk {
  /** Chunk text passed to the model. */
  readonly text: string;
  /** Char offset of this chunk within the source string. */
  readonly offset: number;
}

// The merged-LoRA ONNX export carries a static `max_text_words ≈ 212`
// shape in the ScatterND op of the GLiNER head, so inputs that tokenise
// past that limit crash ORT (`indice = 212` error). Empirically 950
// chars is the largest safe single-pass length on `nullpii-bench`;
// 900 leaves headroom for variable subword density (Italian, German).
export const DEFAULT_CHUNK_CHARS = 900;
export const DEFAULT_OVERLAP_CHARS = 200;

export function chunkText(
  text: string,
  maxChars: number = DEFAULT_CHUNK_CHARS,
  overlapChars: number = DEFAULT_OVERLAP_CHARS,
): TextChunk[] {
  if (overlapChars >= maxChars) {
    throw new RangeError(`overlapChars (${overlapChars}) must be < maxChars (${maxChars})`);
  }
  if (text.length <= maxChars) return [{ text, offset: 0 }];
  const chunks: TextChunk[] = [];
  let start = 0;
  const stride = maxChars - overlapChars;
  while (start < text.length) {
    const end = Math.min(start + maxChars, text.length);
    chunks.push({ text: text.slice(start, end), offset: start });
    if (end >= text.length) break;
    start += stride;
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
