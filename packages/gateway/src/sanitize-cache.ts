// SPDX-License-Identifier: Apache-2.0

import { createHash } from 'node:crypto';

/** Per-session bounds of the cache. */
export const SANITIZE_CACHE_MAX_ENTRIES = 512;
export const SANITIZE_CACHE_MAX_CHARS = 8 * 1024 * 1024;

/**
 * Remembers the sanitize responses of one sidecar session, keyed by a
 * SHA-256 of the request value, so a value sent again is not run through
 * the model again. Coding agents re-read the same files often, and a
 * 30k-character file costs seconds of CPU per read.
 *
 * Exact by construction: the vault mints one placeholder per value in a
 * session, so recomputing gives back the same response. Only masked
 * output is kept, never an original value, and the cache goes with its
 * session. Least recently used entries are dropped past either bound.
 */
export class SanitizeCache {
  private readonly entries = new Map<string, string>();
  private chars = 0;

  static keyOf(serializedValue: string): string {
    return createHash('sha256').update(serializedValue).digest('hex');
  }

  get(key: string): string | undefined {
    const hit = this.entries.get(key);
    if (hit === undefined) return undefined;
    // Re-insert to mark it most recently used.
    this.entries.delete(key);
    this.entries.set(key, hit);
    return hit;
  }

  set(key: string, response: string): void {
    if (response.length > SANITIZE_CACHE_MAX_CHARS) return;
    const previous = this.entries.get(key);
    if (previous !== undefined) {
      this.chars -= previous.length;
      this.entries.delete(key);
    }
    this.entries.set(key, response);
    this.chars += response.length;
    this.evict();
  }

  get size(): number {
    return this.entries.size;
  }

  /** Forget every response: they were masked under a policy that changed. */
  clear(): void {
    this.entries.clear();
    this.chars = 0;
  }

  private evict(): void {
    for (const [key, response] of this.entries) {
      if (this.entries.size <= SANITIZE_CACHE_MAX_ENTRIES && this.chars <= SANITIZE_CACHE_MAX_CHARS)
        return;
      this.entries.delete(key);
      this.chars -= response.length;
    }
  }
}
