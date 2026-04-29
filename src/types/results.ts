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

/** Result of a `restore(sessionId, text)` call. */
export interface RestoreResult {
  /** Text with placeholders mapped back to the original values. */
  readonly restored: string;
  /** Number of placeholders that were successfully replaced. */
  readonly replacements: number;
}
