// SPDX-License-Identifier: Apache-2.0
import { NullPii } from '../nullpii.js';
import type { NullPiiConfig } from '../types/index.js';

/**
 * Tracks one vault session across multiple sanitize calls in a single
 * middleware invocation. `destroy()` is safe to call when no session was
 * ever opened (no-op).
 */
export class MiddlewareSession {
  private sessionId: string | undefined;
  private sharedEngine = false;

  constructor(
    private readonly engine: NullPii,
    initialSessionId?: string,
  ) {
    this.sessionId = initialSessionId;
  }

  /** Mark this session's engine as shared (multi-turn) so destroy is no-op
   * on the engine but session id is dropped from the local handle. */
  markShared(): this {
    this.sharedEngine = true;
    return this;
  }

  /** Returns the current session id if one has been opened. */
  getSessionId(): string | undefined {
    return this.sessionId;
  }

  async sanitize(text: string): Promise<string> {
    const r = await this.engine.sanitize(text, this.sessionId);
    this.sessionId = r.sessionId;
    return r.sanitized;
  }

  /** Restore placeholders if a session was opened. Otherwise pass through. */
  restore(text: string): string {
    if (this.sessionId === undefined) return text;
    return this.engine.restore(text, this.sessionId).restored;
  }

  destroy(): void {
    if (this.sharedEngine) {
      // Multi-turn: keep the vault entry alive for follow-up calls.
      this.sessionId = undefined;
      return;
    }
    if (this.sessionId !== undefined) {
      this.engine.destroySession(this.sessionId);
      this.sessionId = undefined;
    }
  }
}

/** Build a fresh engine and session bound to it. */
export function newSession(config: NullPiiConfig): MiddlewareSession {
  return new MiddlewareSession(new NullPii(config));
}

/**
 * Per-conversation session pool. Shared by middleware to keep one vault
 * across multiple `messages.create` calls under the same `conversationKey`.
 */
export class ConversationPool {
  private readonly engine: NullPii;
  private readonly sessions = new Map<string, string>();

  constructor(config: NullPiiConfig) {
    this.engine = new NullPii(config);
  }

  /** Get or create a session id for `key`. */
  getOrCreateSessionId(key: string): string | undefined {
    return this.sessions.get(key);
  }

  setSessionId(key: string, sessionId: string): void {
    this.sessions.set(key, sessionId);
  }

  /** Build a `MiddlewareSession` that reuses the conversation's vault. */
  open(key: string): MiddlewareSession {
    const session = new MiddlewareSession(this.engine, this.sessions.get(key)).markShared();
    return session;
  }

  /** Persist the session id back from a finished `MiddlewareSession`. */
  commit(key: string, session: MiddlewareSession): void {
    const id = session.getSessionId();
    if (id !== undefined) this.sessions.set(key, id);
  }

  /** Destroy a conversation's vault. Safe on unknown keys. */
  destroyConversation(key: string): void {
    const id = this.sessions.get(key);
    if (id === undefined) return;
    this.engine.destroySession(id);
    this.sessions.delete(key);
  }

  async dispose(): Promise<void> {
    for (const id of this.sessions.values()) this.engine.destroySession(id);
    this.sessions.clear();
    await this.engine.dispose();
  }
}
