// SPDX-License-Identifier: Apache-2.0

/** Structural shape shared by every label-scored char-offset span used
 * inside the pipeline (GLiNER decoder output, recognizer hits, chunking
 * intermediates). Field semantics — inclusive `start`, exclusive `end`,
 * sigmoid `score` in `[0, 1]` — live on the consumer types that
 * extend this base (e.g. `DecodedSpan`). */
export interface ScoredSpan {
  readonly label: string;
  readonly start: number;
  readonly end: number;
  readonly score: number;
}
