// SPDX-License-Identifier: Apache-2.0
// Span decoding ported from the GLiNER library (Apache-2.0); see NOTICE.

import type { Word } from './gliner-tokenizer.js';
import { iou } from './iou.js';
import type { ScoredSpan } from './types/scored-span.js';

/** A decoded GLiNER span — fields mirror the existing `PiiSpan`
 * representation used downstream by the recognizer / vault pipeline. */
export interface DecodedSpan extends ScoredSpan {
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

/** GLiNER span logits → char-offset spans (sigmoid + per-label score cut +
 * greedy NMS).
 *
 * Logits flat layout: `[textLength, maxWidth, numClasses]` row-major,
 * index `i * maxWidth * numClasses + j * numClasses + k`. `labels.length`
 * MUST equal `numClasses`. A candidate is kept iff its score reaches
 * `minScore(label)`; the cut runs before NMS, so a span the caller's
 * thresholds would drop never suppresses another. On overlap
 * (`IoU >= NMS_IOU_THRESHOLD`) the highest score wins and grows to cover
 * the suppressed candidate too. Returns spans sorted by (start, end).
 */
export function decodeGlinerLogits(
  logits: Float32Array,
  textLength: number,
  maxWidth: number,
  numClasses: number,
  words: readonly Word[],
  labels: readonly string[],
  minScore: (label: string) => number,
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
        const lab = labels[classIdx];
        if (lab === undefined) continue;
        const logit = logits[base + classIdx] ?? Number.NEGATIVE_INFINITY;
        const score = sigmoid(logit);
        // Match upstream GLiNER: keep iff `score >= cut`. A span scoring
        // exactly AT the cut survives — matters when callers tune a
        // threshold to a precise value at the high-precision end.
        if (score < minScore(lab)) continue;
        const startWordObj = words[startWord];
        const endWordObj = words[endWord];
        if (startWordObj === undefined || endWordObj === undefined) continue;
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

/** Greedy non-max suppression with IoU threshold. Sort by score desc;
 * a candidate that overlaps a higher-score retained span at
 * `IoU >= NMS_IOU_THRESHOLD` is merged into it: the retained span keeps
 * its label and score and grows to the union of the two ranges, so no
 * character a surviving candidate covered is left unmasked (the same
 * rule as `dedupeOverlappingSpans`). Output sorted by (start, end) for
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
    const i = kept.findIndex((k) => iou(cand, k) >= NMS_IOU_THRESHOLD);
    const keeper = kept[i];
    if (keeper === undefined) {
      kept.push(cand);
      continue;
    }
    if (cand.start < keeper.start || cand.end > keeper.end) {
      kept[i] = {
        ...keeper,
        start: Math.min(keeper.start, cand.start),
        end: Math.max(keeper.end, cand.end),
      };
    }
  }
  return kept.sort((a, b) => a.start - b.start || a.end - b.end);
}
