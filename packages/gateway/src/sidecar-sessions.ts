// SPDX-License-Identifier: Apache-2.0

import { createHash, randomBytes, timingSafeEqual } from 'node:crypto';
import type { NullPii } from 'nullpii';
import { SanitizeCache } from './sanitize-cache.js';

/** Caller-chosen session keys: a Claude Code session id or similar. Not
 * secret and never a vault id: the bearer token and the session's own
 * secret are the gates. */
const SESSION_KEY_PATTERN = /^[A-Za-z0-9._-]{1,128}$/;
/** Random bytes in a session secret, sent base64url-encoded. */
const SESSION_SECRET_BYTES = 32;

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

/** What opening a session gave: a new session and its secret (the only
 * time the secret is handed out), the caller's own live session, a live
 * session the caller did not prove it owns, or a full table. */
export type OpenResult =
  | { readonly kind: 'created'; readonly secret: string }
  | { readonly kind: 'exists' }
  | { readonly kind: 'conflict' }
  | { readonly kind: 'full' };

/** Why a session could not be used: none under that key, or a secret
 * that is missing or wrong. */
export type SessionRefusal = 'not_found' | 'forbidden';

interface Entry {
  readonly vaultId: string;
  readonly cache: SanitizeCache;
  /** SHA-256 of the session secret; the secret itself is not kept. */
  readonly secretDigest: Buffer;
  lastUsed: number;
}

/** What a caller gets for a live session. */
export interface LiveSession {
  readonly vaultId: string;
  readonly cache: SanitizeCache;
}

function sha256(value: string): Buffer {
  return createHash('sha256').update(value).digest();
}

/**
 * Maps caller-chosen session keys to vault sessions that live across
 * requests, unlike the Messages proxy's one session per request.
 *
 * Each session has a random secret, handed out once when it is created.
 * Every later call on it must present the secret, so a process that only
 * holds the bearer token (any command started from a shell that exported
 * it) cannot read the real values of a session it did not open.
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

  /** Create the session for `key` and hand out its secret, or keep the
   * existing one alive when `secret` is its own. */
  open(key: string, secret: string | undefined): OpenResult {
    this.sweep();
    const existing = this.entries.get(key);
    if (existing !== undefined) {
      if (!ownsEntry(existing, secret)) return { kind: 'conflict' };
      existing.lastUsed = this.now();
      return { kind: 'exists' };
    }
    if (this.entries.size >= this.opts.maxSessions) return { kind: 'full' };
    const created = randomBytes(SESSION_SECRET_BYTES).toString('base64url');
    this.entries.set(key, {
      vaultId: this.np.createSession(),
      cache: new SanitizeCache(),
      secretDigest: sha256(created),
      lastUsed: this.now(),
    });
    return { kind: 'created', secret: created };
  }

  /** The live session under `key` when `secret` is its own, refreshing
   * its idle timer; otherwise why not. */
  use(key: string, secret: string | undefined): LiveSession | SessionRefusal {
    this.sweep();
    const entry = this.entries.get(key);
    if (entry === undefined) return 'not_found';
    if (!ownsEntry(entry, secret)) return 'forbidden';
    entry.lastUsed = this.now();
    return entry;
  }

  /** Drop the session and its vault entries when `secret` is its own. */
  close(key: string, secret: string | undefined): 'closed' | SessionRefusal {
    const entry = this.entries.get(key);
    if (entry === undefined) return 'not_found';
    if (!ownsEntry(entry, secret)) return 'forbidden';
    this.drop(key, entry);
    return 'closed';
  }

  /** Drop every session idle for longer than the TTL. */
  sweep(): void {
    const cutoff = this.now() - this.opts.ttlMs;
    for (const [key, entry] of this.entries) {
      if (entry.lastUsed <= cutoff) this.drop(key, entry);
    }
  }

  /** Drop every session. Called when the server closes. */
  closeAll(): void {
    for (const [key, entry] of [...this.entries]) this.drop(key, entry);
  }

  private drop(key: string, entry: Entry): void {
    this.np.destroySession(entry.vaultId);
    this.entries.delete(key);
  }

  get size(): number {
    return this.entries.size;
  }
}

/** Constant-time check of a presented secret against the session's. */
function ownsEntry(entry: Entry, secret: string | undefined): boolean {
  return secret !== undefined && timingSafeEqual(sha256(secret), entry.secretDigest);
}
