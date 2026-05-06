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

/** GLiNER span logits → char-offset spans (sigmoid + threshold + greedy NMS).
 *
 * Logits flat layout: `[textLength, maxWidth, numClasses]` row-major,
 * index `i * maxWidth * numClasses + j * numClasses + k`. `labels.length`
 * MUST equal `numClasses`. Returns spans sorted by (start, -end), highest
 * score wins on overlap (NMS at IoU > 0).
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
