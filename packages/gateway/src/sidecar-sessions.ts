// SPDX-License-Identifier: Apache-2.0

import type { NullPii } from 'nullpii';
import { SanitizeCache } from './sanitize-cache.js';

/** Caller-chosen session keys: a Claude Code session id or similar. Not
 * secret (the bearer token is the gate) and never a vault id. */
const SESSION_KEY_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;

/** Whether `key` can name a sidecar session (`SESSION_KEY_PATTERN`). */
export function isValidSessionKey(key: string): boolean {
  return SESSION_KEY_PATTERN.test(key);
}

export interface SidecarSessionsOptions {
  /** Idle time after which a session and its vault entries are dropped. */
  readonly ttlMs: number;
  readonly maxSessions: number;
  /** Clock, injectable for tests. */
  readonly now?: () => number;
}

export type OpenResult = 'created' | 'exists' | 'full';

interface Entry {
  readonly vaultId: string;
  readonly cache: SanitizeCache;
  lastUsed: number;
}

/** What a caller gets for a live session. */
export interface LiveSession {
  readonly vaultId: string;
  readonly cache: SanitizeCache;
}

/**
 * Maps caller-chosen session keys to vault sessions that live across
 * requests, unlike the Messages proxy's one session per request.
 *
 * Every session is dropped, vault entries included, once it has been
 * idle for `ttlMs`, so real values do not outlive their use in memory.
 * When the table is full, opening a session fails rather than evicting
 * a live one, whose placeholders would then silently stop restoring.
 */
export class SidecarSessions {
  private readonly entries = new Map<string, Entry>();
  private readonly now: () => number;

  constructor(
    private readonly np: NullPii,
    private readonly opts: SidecarSessionsOptions,
  ) {
    this.now = opts.now ?? Date.now;
  }

  /** Create the session for `key`, or keep the existing one alive. */
  open(key: string): OpenResult {
    this.sweep();
    const existing = this.entries.get(key);
    if (existing !== undefined) {
      existing.lastUsed = this.now();
      return 'exists';
    }
    if (this.entries.size >= this.opts.maxSessions) return 'full';
    this.entries.set(key, {
      vaultId: this.np.createSession(),
      cache: new SanitizeCache(),
      lastUsed: this.now(),
    });
    return 'created';
  }

  /** The live session under `key`, refreshing its idle timer, or
   * `undefined` when there is none. */
  use(key: string): LiveSession | undefined {
    this.sweep();
    const entry = this.entries.get(key);
    if (entry === undefined) return undefined;
    entry.lastUsed = this.now();
    return entry;
  }

  /** Drop the session and its vault entries. Returns false if unknown. */
  close(key: string): boolean {
    const entry = this.entries.get(key);
    if (entry === undefined) return false;
    this.np.destroySession(entry.vaultId);
    this.entries.delete(key);
    return true;
  }

  /** Drop every session idle for longer than the TTL. */
  sweep(): void {
    const cutoff = this.now() - this.opts.ttlMs;
    for (const [key, entry] of this.entries) {
      if (entry.lastUsed <= cutoff) this.close(key);
    }
  }

  /** Drop every session. Called when the server closes. */
  closeAll(): void {
    for (const key of [...this.entries.keys()]) this.close(key);
  }

  get size(): number {
    return this.entries.size;
  }
}
