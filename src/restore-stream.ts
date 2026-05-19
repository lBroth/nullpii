// SPDX-License-Identifier: Apache-2.0

import { SessionMismatchError } from './errors.js';
import { sessionPrefixOf } from './session-prefix.js';
import type { RestoreOptions, RestoreResult } from './types/index.js';
import { PLACEHOLDER_REGEX } from './types/index.js';

/** Structural shape of the dependency `RestoreStream` needs from its
 * backing engine: a single `restore()` method matching `PiiVault.restore`.
 * Both `PiiVault` and the public `NullPii` engine satisfy this — letting
 * callers pick whichever is more convenient (the gateway passes the
 * engine directly so it can pool one engine across many sessions). */
export interface RestoreCapable {
  restore(text: string, sessionId: string, options?: RestoreOptions): RestoreResult;
}

/** Hard cap on how many chars can sit in the open-brace buffer before
 * we give up and flush them as literal text. Sized as ~4× the typical
 * placeholder length so a real placeholder never exceeds it — but a
 * stray `{{` with no `}}` following can't grow the buffer without
 * bound. */
const MAX_OPEN_BUFFER = 256;

/**
 * Streaming-safe restore. Wraps a vault + session and exposes a
 * `push(chunk) → restoredHead` / `end() → RestoreResult` pair that
 * tolerates SSE-style chunk boundaries splitting a placeholder
 * mid-token (`{{PII_PRIVATE_PERSON_0_a1b2` | `c3d4e5f6a7b8}}`).
 *
 * Invariants:
 *   - `push()` returns text that is SAFE TO EMIT — no placeholder
 *     prefix that might extend into the next chunk is ever returned.
 *   - The buffer is bounded by `MAX_OPEN_BUFFER` chars. Past that,
 *     an unclosed `{{` is given up on and emitted as literal so the
 *     stream cannot stall on malformed input.
 *   - `end()` drains whatever is still buffered and returns the full
 *     `RestoreResult` (replacements + replacementsByLabel +
 *     unknown / foreign arrays for the whole session run).
 *   - Strict mode throws on the first anomaly seen, just like
 *     `PiiVault.restore({ strict: true })`.
 */
export class RestoreStream {
  private buffer = '';
  /** Aggregated counters across every `push()` call. `end()` returns a
   * single `RestoreResult` that summarises the whole stream. */
  private totalReplacements = 0;
  private readonly totalByLabel: Partial<Record<string, number>> = {};
  private readonly unknownPlaceholders: string[] = [];
  private readonly foreignPlaceholders: string[] = [];

  constructor(
    private readonly vault: RestoreCapable,
    private readonly sessionId: string,
    private readonly options: RestoreOptions = {},
  ) {}

  /** Feed a chunk; return text safe to emit downstream (with completed
   * placeholders restored). Incomplete placeholders are kept in the
   * buffer for the next call. */
  push(chunk: string): string {
    if (chunk.length === 0) return '';
    this.buffer += chunk;
    return this.drainSafe();
  }

  /** Drain the buffer at end-of-stream and return the aggregated
   * RestoreResult. Resets internal state so the instance can be
   * reused for a new stream (rare — typically construct fresh). */
  end(): RestoreResult {
    const remaining = this.buffer;
    this.buffer = '';
    const result = this.restoreSafe(remaining);
    return {
      restored: result,
      replacements: this.totalReplacements,
      replacementsByLabel: { ...this.totalByLabel } as RestoreResult['replacementsByLabel'],
      unknownPlaceholders: [...this.unknownPlaceholders],
      foreignPlaceholders: [...this.foreignPlaceholders],
    };
  }

  private drainSafe(): string {
    // The "safe boundary" is the index up to which no placeholder
    // could possibly be opening. Strategy: find the LAST `{{` that
    // does NOT yet have a closing `}}` after it. Everything before
    // that `{{` is safe to restore + emit; everything from that
    // `{{` onward stays buffered.
    const safePos = this.findSafeBoundary();
    if (safePos === 0) return '';
    const safeSlice = this.buffer.slice(0, safePos);
    this.buffer = this.buffer.slice(safePos);
    return this.restoreSafe(safeSlice);
  }

  private findSafeBoundary(): number {
    const lastOpen = this.buffer.lastIndexOf('{{');
    let pos = this.buffer.length;
    if (lastOpen !== -1) {
      const closeAfterOpen = this.buffer.indexOf('}}', lastOpen);
      if (closeAfterOpen === -1) {
        // Trailing `{{` is unclosed → hold from the `{{` onward,
        // unless the unclosed run exceeded the safety cap.
        if (this.buffer.length - lastOpen > MAX_OPEN_BUFFER) {
          return this.buffer.length;
        }
        return lastOpen;
      }
      // Trailing `{{` is closed; fall through.
    }
    // Hold a trailing solo `{` — the next chunk's first char might
    // complete `{{`. Without this, byte-at-a-time feeds split every
    // placeholder before it can be recognised.
    if (pos > 0 && this.buffer.charAt(pos - 1) === '{') {
      pos -= 1;
    }
    return pos;
  }

  private restoreSafe(slice: string): string {
    if (slice.length === 0) return '';
    const expectedPrefix = sessionPrefixOf(this.sessionId);
    const strict = this.options.strict === true;
    const re = new RegExp(PLACEHOLDER_REGEX.source, 'g');
    return slice.replace(re, (match, label: string, _idx, foundPrefix: string) => {
      if (foundPrefix !== expectedPrefix) {
        if (strict) {
          throw new SessionMismatchError(expectedPrefix, foundPrefix);
        }
        this.foreignPlaceholders.push(match);
        return match;
      }
      // Delegate to the vault for the single-placeholder lookup. We
      // know the prefix matches; pass the snippet as-is.
      const r = this.vault.restore(match, this.sessionId, this.options);
      if (r.unknownPlaceholders.length > 0) {
        this.unknownPlaceholders.push(...r.unknownPlaceholders);
        return match;
      }
      this.totalReplacements += r.replacements;
      const lc = label.toLowerCase();
      this.totalByLabel[lc] = (this.totalByLabel[lc] ?? 0) + r.replacements;
      return r.restored;
    });
  }
}
