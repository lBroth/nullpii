// SPDX-License-Identifier: Apache-2.0

import type { PiiSpan } from './spans.js';

/**
 * Result of a `sanitize(text)` call.
 *
 * The vault is keyed by `sessionId` server-side; callers pass `sessionId`
 * back to `restore()` to map placeholders back to originals.
 */
export interface SanitizeResult {
  /** Opaque identifier of the in-memory vault session that owns the placeholders. */
  readonly sessionId: string;
  /** Input text with every detected PII span replaced by a placeholder. */
  readonly sanitized: string;
  /** Spans found in the original input, in document order. */
  readonly spans: readonly PiiSpan[];
}

/** Result of a `restore(text, sessionId)` call. */
export interface RestoreResult {
  /** Text with placeholders mapped back to the original values. Foreign-
   * prefix and unknown-idx placeholders are left literal. */
  readonly restored: string;
  /** Number of placeholders that were successfully replaced. */
  readonly replacements: number;
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
}
