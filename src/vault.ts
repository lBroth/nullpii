// SPDX-License-Identifier: Apache-2.0

import { randomUUID } from 'node:crypto';
import { SessionMismatchError, SessionNotFoundError, UnknownPlaceholderError } from './errors.js';
import { logf } from './log.js';
import { sessionPrefixOf } from './session-prefix.js';
import {
  type MaskResult,
  PLACEHOLDER_REGEX,
  PLACEHOLDER_TEMPLATE,
  type PiiSpan,
  type RestoreOptions,
  type RestoreResult,
} from './types/index.js';

const LOG_SCOPE = 'nullpii:vault';

interface Session {
  /** placeholder string → original value. */
  readonly entries: Map<string, string>;
  /** label → next index for that label. */
  readonly counters: Map<string, number>;
  /** `label + NUL + exact value` → the placeholder minted for it, so a
   * value that recurs in the session reaches the model as the same token
   * (issue #50). Keyed on the exact value: folding case or whitespace
   * would restore every occurrence with the first one's spelling. */
  readonly byValue: Map<string, string>;
}

const VALUE_KEY_SEPARATOR = '\u0000';

/**
 * In-memory reversible vault for PII placeholders.
 *
 * Security invariants (enforced by construction):
 * - Vault contents never leave memory — `sanitize`/`restore` are the only
 *   ways to read placeholder→original mappings, and both require the
 *   correct sessionId.
 * - Placeholders carry a 16-hex-char prefix of the minting session id.
 *   `restore()` validates the prefix and throws `SessionMismatchError`
 *   on mismatch, so a placeholder minted by session A cannot be
 *   silently substituted with session B's PII.
 * - `destroySession` deletes the underlying `Map` so GC can reclaim it
 *   and subsequent `sanitize`/`restore` calls fail loud.
 * - `clear()` wipes every session (call from `NullPii.dispose()`).
 * - Debug logs never carry PII — only counts and short ids.
 */
export class PiiVault {
  private readonly sessions = new Map<string, Session>();

  /** Create a fresh vault session. Returns a UUID v4. */
  createSession(): string {
    const id = randomUUID();
    this.sessions.set(id, { entries: new Map(), counters: new Map(), byValue: new Map() });
    logf(LOG_SCOPE, 'session.created', { sessions: this.sessions.size });
    return id;
  }

  /**
   * Replace each PII span with a typed indexed placeholder.
   *
   * Spans are processed back-to-front so each replacement preserves the
   * char offsets of earlier spans. The session's vault is updated in place.
   *
   * @throws {SessionNotFoundError} if `sessionId` is unknown.
   */
  sanitize(text: string, spans: readonly PiiSpan[], sessionId: string): MaskResult {
    const session = this.requireSession(sessionId);
    if (spans.length === 0) {
      return { sessionId, sanitized: text, spans: [] };
    }
    const sessionPrefix = sessionPrefixOf(sessionId);
    // Placeholders are allocated in document order so indices reflect
    // reading order. Overlapping spans are merged first: replacing two
    // spans that share characters corrupts the round-trip.
    const ordered = mergeOverlappingSpans(text, spans);
    if (ordered.length < spans.length) {
      logf(LOG_SCOPE, 'sanitize.merged', {
        spans: ordered.length,
        dropped: spans.length - ordered.length,
      });
    }
    const placeholders = ordered.map((span) => this.allocPlaceholder(session, span, sessionPrefix));
    // Replace back-to-front so each replacement preserves earlier offsets.
    let out = text;
    for (let i = ordered.length - 1; i >= 0; i--) {
      const span = ordered[i];
      const placeholder = placeholders[i];
      if (span === undefined || placeholder === undefined) continue;
      out = `${out.slice(0, span.start)}${placeholder}${out.slice(span.end)}`;
    }
    logf(LOG_SCOPE, 'sanitize', { spans: ordered.length, session: sessionPrefix });
    return { sessionId, sanitized: out, spans: ordered };
  }

  /**
   * Replace every placeholder in `text` with its original value from the
   * session vault.
   *
   * Anomaly classes:
   *   - "unknown" — placeholder matches the current session prefix but has
   *     no vault entry (typically an LLM hallucination).
   *   - "foreign" — placeholder carries a different session's prefix.
   *
   * Default mode surfaces both via `RestoreResult.unknownPlaceholders` and
   * `.foreignPlaceholders` and leaves them literal in `restored`. Legitimate
   * placeholders are still substituted on the same pass.
   *
   * `{ strict: true }` throws on the first anomaly seen
   * (`UnknownPlaceholderError` or `SessionMismatchError`) — useful when the
   * caller treats any anomaly as a hard failure.
   *
   * @throws {SessionNotFoundError} if `sessionId` is unknown.
   * @throws {SessionMismatchError} when `strict` and a foreign-prefix placeholder is found.
   * @throws {UnknownPlaceholderError} when `strict` and a same-prefix placeholder is unknown.
   */
  restore(text: string, sessionId: string, options: RestoreOptions = {}): RestoreResult {
    const session = this.requireSession(sessionId);
    const expectedPrefix = sessionPrefixOf(sessionId);
    const strict = options.strict === true;
    let replacements = 0;
    const replacementsByLabel: Partial<Record<string, number>> = {};
    const unknownPlaceholders: string[] = [];
    const foreignPlaceholders: string[] = [];
    let strictError: SessionMismatchError | UnknownPlaceholderError | null = null;
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    const restored = text.replace(re, (match, label: string, _idx, foundPrefix: string) => {
      if (foundPrefix !== expectedPrefix) {
        if (strict && strictError === null) {
          strictError = new SessionMismatchError(expectedPrefix, foundPrefix);
        }
        foreignPlaceholders.push(match);
        return match;
      }
      const original = session.entries.get(match);
      if (original === undefined) {
        if (strict && strictError === null) {
          strictError = new UnknownPlaceholderError(match);
        }
        unknownPlaceholders.push(match);
        return match;
      }
      replacements += 1;
      // Placeholder label segment is uppercased (`PRIVATE_EMAIL`); the
      // public `PiiLabel` union is lowercased (`private_email`). Map back.
      const lc = label.toLowerCase();
      replacementsByLabel[lc] = (replacementsByLabel[lc] ?? 0) + 1;
      return original;
    });
    if (strictError !== null) {
      throw strictError;
    }
    logf(LOG_SCOPE, 'restore', {
      replacements,
      unknown: unknownPlaceholders.length,
      foreign: foreignPlaceholders.length,
      session: expectedPrefix,
      ...(options.traceId !== undefined && { traceId: options.traceId }),
    });
    return {
      restored,
      replacements,
      replacementsByLabel: replacementsByLabel as Readonly<
        Partial<Record<import('./types/index.js').PiiLabel, number>>
      >,
      unknownPlaceholders,
      foreignPlaceholders,
    };
  }

  /**
   * Wipe the vault for `sessionId`. Safe to call on unknown sessions.
   * Subsequent `sanitize`/`restore` for this id throw `SessionNotFoundError`.
   */
  destroySession(sessionId: string): void {
    const existed = this.sessions.delete(sessionId);
    if (existed) logf(LOG_SCOPE, 'session.destroyed', { session: sessionPrefixOf(sessionId) });
  }

  /** Drop every session. Called from `NullPii.dispose()` so vault state
   * does not outlive the engine that minted it. */
  clear(): void {
    const n = this.sessions.size;
    this.sessions.clear();
    if (n > 0) logf(LOG_SCOPE, 'vault.cleared', { dropped: n });
  }

  /** Number of active sessions. Diagnostic only — does not expose contents. */
  get sessionCount(): number {
    return this.sessions.size;
  }

  private requireSession(sessionId: string): Session {
    const s = this.sessions.get(sessionId);
    if (s === undefined) throw new SessionNotFoundError(sessionId);
    return s;
  }

  private allocPlaceholder(session: Session, span: PiiSpan, sessionPrefix: string): string {
    const key = `${span.label}${VALUE_KEY_SEPARATOR}${span.text}`;
    const existing = session.byValue.get(key);
    if (existing !== undefined) return existing;
    const idx = session.counters.get(span.label) ?? 0;
    session.counters.set(span.label, idx + 1);
    const placeholder = PLACEHOLDER_TEMPLATE(span.label, idx, sessionPrefix);
    session.entries.set(placeholder, span.text);
    session.byValue.set(key, placeholder);
    return placeholder;
  }
}

/**
 * Clamp spans to `text`, drop empty ones, and merge any that share a
 * character into their union, sorted by start.
 *
 * Masking the union never exposes a character that any input span
 * covered, so merging is the fail-safe resolution. The merged span keeps
 * the label of its highest-scoring member and that member's score; its
 * `text` is re-sliced from `text` because the vault stores it verbatim.
 */
export function mergeOverlappingSpans(text: string, spans: readonly PiiSpan[]): PiiSpan[] {
  const clamped = spans
    .map((s) => ({ ...s, start: Math.max(0, s.start), end: Math.min(text.length, s.end) }))
    .filter((s) => s.end > s.start)
    .sort((a, b) => a.start - b.start || b.end - a.end);
  const merged: PiiSpan[] = [];
  for (const span of clamped) {
    const last = merged[merged.length - 1];
    if (last === undefined || span.start >= last.end) {
      merged.push({ ...span, text: text.slice(span.start, span.end) });
      continue;
    }
    const end = Math.max(last.end, span.end);
    const winner = span.score > last.score ? span : last;
    merged[merged.length - 1] = {
      ...winner,
      start: last.start,
      end,
      text: text.slice(last.start, end),
    };
  }
  return merged;
}
