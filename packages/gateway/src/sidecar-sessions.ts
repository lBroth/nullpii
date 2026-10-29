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
/** How many keys of sessions that ended by their idle TTL are remembered,
 * until their caller opens or closes them again. Past it, the table counts
 * as never released (`unclosed`), so nothing is forgotten silently. */
const UNCLOSED_KEYS_MAX = 1024;

/** Separates a session base from the suffix a caller adds to it when it
 * moves to a new key under the same base (`<base>.<suffix>`). */
const BASE_SEPARATOR = '.';

/** Whether `key` can name a sidecar session (`SESSION_KEY_PATTERN`). */
export function isValidSessionKey(key: string): boolean {
  return SESSION_KEY_PATTERN.test(key);
}

/** The base of `key`: the part before its first `.`, or the key itself. */
function baseOf(key: string): string {
  const cut = key.indexOf(BASE_SEPARATOR);
  return cut === -1 ? key : key.slice(0, cut);
}

/** Whether `left` can be superseded by a session opened under `key`: another
 * key under the same base (`<base>` or `<base>.<suffix>`). */
export function canSupersede(key: string, left: string): boolean {
  return left !== key && baseOf(left) === baseOf(key);
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
  /** A session opened later under the same base named this key as one its
   * caller left (`open`'s `supersedes`), and no call has proved its owner is
   * still here since: when its idle TTL ends it, its key is not remembered. */
  left: boolean;
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
  // Keys whose session ended by the idle TTL and whose caller has not come
  // back since (to open it again, or to close it): a window left open and
  // idle looks just like this, so these keys tell the shutdown route that
  // someone may still count on this sidecar.
  private readonly expiredKeys = new Set<string>();
  private expiredOverflow = false;
  private openedAny = false;
  private readonly now: () => number;

  constructor(
    private readonly np: NullPii,
    private readonly opts: SidecarSessionsOptions,
  ) {
    this.now = opts.now ?? Date.now;
  }

  /**
   * Create the session for `key` and hand out its secret, or keep the
   * existing one alive when `secret` is its own.
   *
   * `supersedes` is one other key under the same base as `key`, which the
   * caller says it held and left (it lost its secret, as after a reload of
   * the mod). It counts only when the session is created. Remembered as
   * expired, that key is forgotten; live, it stays open, its vault and
   * secret untouched, and only its expiry is not remembered later, unless
   * its owner proves itself on a call before then. A `supersedes` that
   * `canSupersede` refuses is a caller's bug (the route answers 400 first),
   * and throws.
   */
  open(key: string, secret: string | undefined, supersedes?: string): OpenResult {
    if (supersedes !== undefined && !canSupersede(key, supersedes)) {
      throw new Error('supersedes names no other key under the session key base');
    }
    this.sweep();
    const existing = this.entries.get(key);
    if (existing !== undefined) {
      if (!ownsEntry(existing, secret)) return { kind: 'conflict' };
      existing.lastUsed = this.now();
      existing.left = false;
      return { kind: 'exists' };
    }
    if (this.entries.size >= this.opts.maxSessions) return { kind: 'full' };
    const created = randomBytes(SESSION_SECRET_BYTES).toString('base64url');
    // The caller of an expired session is back: it no longer counts as gone
    // without a word.
    this.expiredKeys.delete(key);
    this.openedAny = true;
    this.entries.set(key, {
      vaultId: this.np.createSession(),
      cache: new SanitizeCache(),
      secretDigest: sha256(created),
      lastUsed: this.now(),
      left: false,
    });
    if (supersedes !== undefined) this.leave(supersedes);
    return { kind: 'created', secret: created };
  }

  /** The key `left` was left by its caller. */
  private leave(left: string): void {
    this.expiredKeys.delete(left);
    const entry = this.entries.get(left);
    if (entry !== undefined) entry.left = true;
  }

  /** The live session under `key` when `secret` is its own, refreshing
   * its idle timer; otherwise why not. */
  use(key: string, secret: string | undefined): LiveSession | SessionRefusal {
    this.sweep();
    const entry = this.entries.get(key);
    if (entry === undefined) return 'not_found';
    if (!ownsEntry(entry, secret)) return 'forbidden';
    entry.lastUsed = this.now();
    // Its owner is still here: a supersede from another key no longer holds.
    entry.left = false;
    return entry;
  }

  /** Drop the session and its vault entries when `secret` is its own. */
  close(key: string, secret: string | undefined): 'closed' | SessionRefusal {
    const entry = this.entries.get(key);
    if (entry === undefined) {
      // A caller closing a session its idle TTL already ended has said it is
      // done with it, all the same.
      this.expiredKeys.delete(key);
      return 'not_found';
    }
    if (!ownsEntry(entry, secret)) return 'forbidden';
    this.drop(key, entry);
    return 'closed';
  }

  /** Drop every session idle for longer than the TTL. */
  sweep(): void {
    const cutoff = this.now() - this.opts.ttlMs;
    for (const [key, entry] of this.entries) {
      if (entry.lastUsed > cutoff) continue;
      this.drop(key, entry);
      // A key its caller said it left is no window that may come back.
      if (!entry.left) this.rememberExpired(key);
    }
  }

  private rememberExpired(key: string): void {
    if (this.expiredKeys.size >= UNCLOSED_KEYS_MAX) {
      this.expiredOverflow = true;
      return;
    }
    this.expiredKeys.add(key);
  }

  /** Forget every session's cached sanitize responses, as after a policy
   * change; the sessions and their vaults stay. */
  clearCaches(): void {
    for (const entry of this.entries.values()) entry.cache.clear();
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

  /** Whether any session was ever opened here. */
  get everOpened(): boolean {
    return this.openedAny;
  }

  /** Whether a session ended by its idle TTL and its caller has neither
   * opened nor closed it since: that caller (a window left idle) may still
   * be counting on this process. */
  get unclosed(): boolean {
    return this.expiredOverflow || this.expiredKeys.size > 0;
  }
}

/** Constant-time check of a presented secret against the session's. */
function ownsEntry(entry: Entry, secret: string | undefined): boolean {
  return secret !== undefined && timingSafeEqual(sha256(secret), entry.secretDigest);
}
