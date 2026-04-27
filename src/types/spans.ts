// SPDX-License-Identifier: Apache-2.0
import type { PiiLabel } from './labels.js';

/**
 * One detected span in the input text.
 *
 * Offsets are character-level (UTF-16 code units, the same units
 * `String.prototype.slice` uses), half-open: `text.slice(start, end)`.
 */
export interface PiiSpan {
  /** Inclusive start char offset into the original input. */
  readonly start: number;
  /** Exclusive end char offset into the original input. */
  readonly end: number;
  /** Predicted label for the span (never `'O'` — `'O'` spans are not emitted). */
  readonly label: Exclude<PiiLabel, 'O'>;
  /** Mean softmax score across the span's BIOES tokens, in `[0, 1]`. */
  readonly score: number;
  /** Verbatim slice of the original input — `text.slice(start, end)`. */
  readonly text: string;
}
