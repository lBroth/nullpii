// SPDX-License-Identifier: Apache-2.0

import type { PiiCategory } from './labels.js';

/**
 * User-defined recognizer that runs as a regex post-pass after the ML
 * model. Useful for known formats with poor ML coverage (internal
 * employee IDs, AWS access keys, IBAN, ...).
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
  /** Optional: the part of `text` to mask for a match that passed
   * `validate`, or `null` to drop the match. For a value only its
   * context identifies (the password after a key name), or a format a
   * linear regex cannot bound (a PEM block cut off before its trailer).
   * Must run in time linear in the text it reads. */
  readonly span?: (match: RegExpExecArray, text: string) => RecognizerSpan | null;
}

/** Offsets into the scanned text, `start` inclusive, `end` exclusive. */
export interface RecognizerSpan {
  readonly start: number;
  readonly end: number;
}
