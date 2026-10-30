// SPDX-License-Identifier: Apache-2.0

import type { PiiLabel } from './labels.js';
import type { PiiSpan } from './spans.js';

/**
 * Text with given spans replaced by placeholders: what the vault returns
 * for `PiiVault.sanitize(text, spans, sessionId)`.
 *
 * The vault is keyed by `sessionId` server-side; callers pass `sessionId`
 * back to `restore()` to map placeholders back to originals.
 */
export interface MaskResult {
  /** Opaque identifier of the in-memory vault session that owns the placeholders. */
  readonly sessionId: string;
  /** Input text with every given PII span replaced by a placeholder. */
  readonly sanitized: string;
  /** The masked spans, in document order. */
  readonly spans: readonly PiiSpan[];
}

/** Result of a `sanitize(text)` call: the masked text and the spans found,
 * plus what the model could not read. */
export interface SanitizeResult extends MaskResult {
  /** Words the model could not read: each is longer, alone, than the
   * model's subword budget (minified code, data blobs). The recognizer
   * pack and the base64 detector still scanned them; only the model did
   * not. Under a policy that runs a secret pass (`secret-pass.ts`), a
   * word counted here may still be read for secrets by that pass, whose
   * prompt is shorter. Usually 0. For a text over `MAX_INPUT_CHARS`, read
   * in overlapping windows, a word in an overlap is counted once per
   * window. */
  readonly modelUnscannedWords: number;
}

/** Result of a `restore(text, sessionId)` call. */
export interface RestoreResult {
  /** Text with placeholders mapped back to the original values. Foreign-
   * prefix and unknown-idx placeholders are left literal. */
  readonly restored: string;
  /** Number of placeholders that were successfully replaced. */
  readonly replacements: number;
  /** Per-label substitution counts. Empty object when `replacements === 0`.
   * Useful for "did the LLM preserve placeholders?" / "which categories
   * actually round-tripped?" telemetry without spelunking through the
   * sanitize spans. Anomalous placeholders (unknown / foreign) are not
   * counted here — they appear in their own arrays. */
  readonly replacementsByLabel: Readonly<Partial<Record<PiiLabel, number>>>;
  /** Placeholders carrying the current session's prefix but with no entry
   * in the vault — typically LLM hallucinations. Left literal in `restored`.
   * Empty if everything matched. */
  readonly unknownPlaceholders: readonly string[];
  /** Placeholders carrying a foreign session prefix. Left literal in
   * `restored`. Empty when input is clean. */
  readonly foreignPlaceholders: readonly string[];
}

/** Options for `restore()` calls. */
export interface RestoreOptions {
  /** When `true`, throws `SessionMismatchError` on the first foreign-prefix
   * placeholder, or `UnknownPlaceholderError` on the first unknown placeholder.
   * Default `false` — anomalies surface in the returned arrays instead. */
  readonly strict?: boolean;
  /** Caller-supplied trace identifier propagated to structured log lines
   * emitted during this call. Never logged with PII attached. */
  readonly traceId?: string;
}

/** Options for `sanitize()` calls. */
export interface SanitizeOptions {
  /** Caller-supplied trace identifier propagated to structured log lines
   * emitted during this call. Never logged with PII attached. */
  readonly traceId?: string;
}
