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
 * score wins on overlap (NMS at `IoU >= NMS_IOU_THRESHOLD`).
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
        // Match upstream GLiNER: keep iff `score >= threshold`. A span
        // scoring exactly AT the threshold survives — matters when
        // callers tune `threshold` to a precise value at the high-
        // precision end of the curve.
        if (score < threshold) continue;
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

/** IoU threshold used by `greedyNms`. Matches upstream GLiNER's
 * convention (~0.4 — `John|Smith` adjacent persons survive, partial
 * overlaps at IoU >= 0.4 collapse). Strict `> 0` was too aggressive;
 * adjacent same-label spans with zero overlap (`John` + `Smith`) were
 * collapsing if char ranges abutted at exactly one boundary. */
const NMS_IOU_THRESHOLD = 0.4;

function spanIou(a: DecodedSpan, b: DecodedSpan): number {
  const interStart = Math.max(a.start, b.start);
  const interEnd = Math.min(a.end, b.end);
  const inter = Math.max(0, interEnd - interStart);
  if (inter === 0) return 0;
  const union = a.end - a.start + (b.end - b.start) - inter;
  return union > 0 ? inter / union : 0;
}

/** Greedy non-max suppression with IoU threshold. Sort by score desc,
 * keep span unless it overlaps a higher-score retained span at
 * `IoU >= NMS_IOU_THRESHOLD`. Output sorted by (start, end) for
 * deterministic ordering. */
function greedyNms(spans: readonly DecodedSpan[]): DecodedSpan[] {
  if (spans.length <= 1) return [...spans];
  // Stable tie-break on (start, end) keeps ordering deterministic when
  // two candidates share the same score.
  const sortedByScore = [...spans].sort(
    (a, b) => b.score - a.score || a.start - b.start || a.end - b.end,
  );
  const kept: DecodedSpan[] = [];
  for (const cand of sortedByScore) {
    let suppressed = false;
    for (const k of kept) {
      if (spanIou(cand, k) >= NMS_IOU_THRESHOLD) {
        suppressed = true;
        break;
      }
    }
    if (!suppressed) kept.push(cand);
  }
  return kept.sort((a, b) => a.start - b.start || a.end - b.end);
}
