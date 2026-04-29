import { randomUUID } from 'node:crypto';
import debug from 'debug';
import { SessionNotFoundError } from './errors.js';
import {
  PLACEHOLDER_REGEX,
  PLACEHOLDER_TEMPLATE,
  type PiiSpan,
  type RestoreResult,
  type SanitizeResult,
} from './types/index.js';

const log = debug('nullpii:vault');

interface Session {
  /** placeholder string → original value. */
  readonly entries: Map<string, string>;
  /** label → next index for that label. */
  readonly counters: Map<string, number>;
}

/**
 * In-memory reversible vault for PII placeholders.
 *
 * Security invariants (enforced by construction):
 * - Vault contents never leave memory — `sanitize`/`restore` are the only
 *   ways to read placeholder→original mappings, and both require the
 *   correct sessionId.
 * - `destroySession` deletes the underlying `Map` so GC can reclaim it
 *   and subsequent `sanitize`/`restore` calls fail loud.
 * - Debug logs never carry PII — only counts and labels.
 */
export class PiiVault {
  private readonly sessions = new Map<string, Session>();

  /** Create a fresh vault session. Returns a UUID v4. */
  createSession(): string {
    const id = randomUUID();
    this.sessions.set(id, { entries: new Map(), counters: new Map() });
    log('session created (count=%d)', this.sessions.size);
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
  sanitize(text: string, spans: readonly PiiSpan[], sessionId: string): SanitizeResult {
    const session = this.requireSession(sessionId);
    if (spans.length === 0) {
      return { sessionId, sanitized: text, spans: [] };
    }
    // Allocate placeholders in document order so indices reflect reading order.
    const ordered = [...spans].sort((a, b) => a.start - b.start);
    const placeholders = ordered.map((span) => this.allocPlaceholder(session, span));
    // Replace back-to-front so each replacement preserves earlier offsets.
    let out = text;
    for (let i = ordered.length - 1; i >= 0; i--) {
      const span = ordered[i];
      const placeholder = placeholders[i];
      if (span === undefined || placeholder === undefined) continue;
      out = `${out.slice(0, span.start)}${placeholder}${out.slice(span.end)}`;
    }
    log('sanitized: spans=%d session=%s', spans.length, shortId(sessionId));
    return { sessionId, sanitized: out, spans };
  }

  /**
   * Replace every placeholder in `text` with its original value from the
   * session vault. Placeholders not found in the vault are left as-is.
   *
   * @throws {SessionNotFoundError} if `sessionId` is unknown.
   */
  restore(text: string, sessionId: string): RestoreResult {
    const session = this.requireSession(sessionId);
    let replacements = 0;
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    const restored = text.replace(re, (match) => {
      const original = session.entries.get(match);
      if (original === undefined) return match;
      replacements += 1;
      return original;
    });
    log('restored: replacements=%d session=%s', replacements, shortId(sessionId));
    return { restored, replacements };
  }

  /**
   * Wipe the vault for `sessionId`. Safe to call on unknown sessions.
   * Subsequent `sanitize`/`restore` for this id throw `SessionNotFoundError`.
   */
  destroySession(sessionId: string): void {
    const existed = this.sessions.delete(sessionId);
    if (existed) log('session destroyed: %s', shortId(sessionId));
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

  private allocPlaceholder(session: Session, span: PiiSpan): string {
    const idx = session.counters.get(span.label) ?? 0;
    session.counters.set(span.label, idx + 1);
    const placeholder = PLACEHOLDER_TEMPLATE(span.label, idx);
    session.entries.set(placeholder, span.text);
    return placeholder;
  }
}

function shortId(id: string): string {
  return id.slice(0, 8);
}
