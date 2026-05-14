// SPDX-License-Identifier: Apache-2.0

import type { PiiCategory } from './labels.js';

/**
 * User-defined recognizer that runs as a regex post-pass after the ML
 * model. Useful for known formats with poor ML coverage (internal
 * employee IDs, AWS access keys, IBAN, SWIFT BIC, ...).
 *
 * Recognizer matches are merged into the ML span list, dropping any that
 * overlap an existing higher-confidence span.
 */
export interface Recognizer {
  /** Stable id (used for debugging / opt-out). */
  readonly id: string;
  /** Global regex with `g` flag. Match groups not used; full match is the span. */
  readonly pattern: RegExp;
  /** PII category to assign to matches. Must be one of the 8 standard categories. */
  readonly label: PiiCategory;
  /** Confidence in `[0, 1]`. ML matches with higher score win on overlap. */
  readonly confidence: number;
  /** Optional: skip matches whose verbatim text fails this validator
   * (e.g. Luhn for credit cards, IBAN checksum). */
  readonly validate?: (match: string) => boolean;
}
