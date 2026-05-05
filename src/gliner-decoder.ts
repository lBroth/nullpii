// SPDX-License-Identifier: Apache-2.0

import type { Word } from './gliner-tokenizer.js';

/** A decoded GLiNER span — fields mirror the existing `PiiSpan`
 * representation used downstream by the recognizer / vault pipeline. */
export interface DecodedSpan {
  readonly label: string;
  /** Inclusive char offset in the original text. */
  readonly start: number;
  /** Exclusive char offset. */
  readonly end: number;
  /** sigmoid(logit) — unnormalised confidence in `[0, 1]`. */
  readonly score: number;
}

const sigmoid = (x: number): number => {
  if (x >= 0) {
    const e = Math.exp(-x);
    return 1 / (1 + e);
  }
  const e = Math.exp(x);
  return e / (1 + e);
};

/**
 * Decode GLiNER span logits into character-offset spans.
 *
 * Mirrors the logits → spans path from
 * `gliner.decoding.decoder.SpanDecoder.decode` (sigmoid + threshold +
 * `torch.where(probs > threshold)` + greedy NMS).
 *
 * Logits layout (from `OrtBackend.infer()` output): row-major flatten
 * of `[textLength, maxWidth, numClasses]`. Each (i, j, k) entry is at
 * index `i * maxWidth * numClasses + j * numClasses + k`.
 *
 * @param logits — flat output of GLiNER ONNX
 * @param textLength — number of TEXT words in the input (matches the
 *   `text_lengths` ONNX feed and the words array passed in)
 * @param maxWidth — span width dimension (default 12)
 * @param numClasses — number of label classes
 * @param words — text words with original char offsets (from
 *   `GlinerTokenizer.encode().words`); used to map (start_word, end_word)
 *   pairs back to the source text
 * @param labels — label vocabulary in the same order as the prompt that
 *   produced these logits. `labels.length` MUST equal `numClasses`.
 * @param threshold — sigmoid score threshold (default 0.5 per
 *   `gliner_config.json`)
 *
 * @returns spans sorted by (start, -end), with overlaps resolved by
 *   keeping the highest-score span (greedy NMS at IoU > 0).
 */
export function decodeGlinerLogits(
  logits: Float32Array,
  textLength: number,
  maxWidth: number,
  numClasses: number,
  words: readonly Word[],
  labels: readonly string[],
  threshold = 0.5,
): DecodedSpan[] {
  if (labels.length !== numClasses) {
    throw new Error(
      `decodeGlinerLogits: labels.length=${labels.length} != numClasses=${numClasses}`,
    );
  }

  const candidates: DecodedSpan[] = [];

  for (let startWord = 0; startWord < textLength; startWord++) {
    for (let widthOffset = 0; widthOffset < maxWidth; widthOffset++) {
      const endWord = startWord + widthOffset;
      if (endWord >= textLength) break; // span runs off the end

      const base = (startWord * maxWidth + widthOffset) * numClasses;
      for (let classIdx = 0; classIdx < numClasses; classIdx++) {
        const logit = logits[base + classIdx] ?? Number.NEGATIVE_INFINITY;
        const score = sigmoid(logit);
        if (score <= threshold) continue;
        const startWordObj = words[startWord];
        const endWordObj = words[endWord];
        if (startWordObj === undefined || endWordObj === undefined) continue;
        const lab = labels[classIdx];
        if (lab === undefined) continue;
        candidates.push({
          label: lab,
          start: startWordObj.charStart,
          end: endWordObj.charEnd,
          score,
        });
      }
    }
  }

  return greedyNms(candidates);
}

/** Greedy non-max suppression: sort by score desc, keep span only if it
 * does not overlap a higher-score retained span (strict overlap > 0).
 * The output is then resorted by start char for deterministic ordering. */
function greedyNms(spans: readonly DecodedSpan[]): DecodedSpan[] {
  if (spans.length <= 1) return [...spans];
  const sortedByScore = [...spans].sort((a, b) => b.score - a.score);
  const kept: DecodedSpan[] = [];
  for (const cand of sortedByScore) {
    let overlap = false;
    for (const k of kept) {
      if (cand.start < k.end && k.start < cand.end) {
        overlap = true;
        break;
      }
    }
    if (!overlap) kept.push(cand);
  }
  return kept.sort((a, b) => a.start - b.start || a.end - b.end);
}
