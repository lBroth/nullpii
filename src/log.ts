// SPDX-License-Identifier: Apache-2.0

//
// Structured logging shim for nullpii. Wraps the `debug` package with a
// typed-field API so log lines are machine-parseable AND so the type
// system enforces the PII / prompt-body exclusion contract.
//
// Hard rule, enforced by the `LogFields` shape below: **no log field
// ever holds user PII or prompt content.** That includes:
//
//   - the raw input text passed to `sanitize()`;
//   - any value from `RestoreResult.spans[].text` (the PII verbatim);
//   - any vault entry (placeholder → original mapping);
//   - reconstructed text fragments from `restore()`;
//   - LLM replies routed through `wrapForLLM`.
//
// What IS permitted: event name, traceId (caller-supplied), already-
// truncated session prefix, counts, sizes, timings, file paths the
// caller passed in, HF download URLs, recognizer ids, label names
// (the categories themselves — `private_email`, not the matched email).
//
// Adding a new field? Add it to `LogFields` and ask the question:
//   "Could this value ever carry a fragment of the caller's input?"
// If yes, reject — find a count / hash / bucket / boolean signal
// instead.

import debug from 'debug';

/**
 * Permitted log fields. Explicit allowlist — keys are spelled out so a
 * reviewer can scan this interface and verify the contract. Values are
 * restricted to scalar primitives that round-trip cleanly through
 * NDJSON / OTel attribute exports.
 */
export interface LogFields {
  /** Caller-supplied trace identifier. Threaded through `sanitize()` /
   * `restore()` so log lines from a single request can be correlated. */
  readonly traceId?: string;
  /** Already-truncated session prefix. Never the full session id. */
  readonly session?: string;
  /** Recognizer / module / event short id (e.g. `core:iban`). */
  readonly recognizer?: string;
  /** PII label name from the schema (e.g. `private_email`) — the
   * category, never the matched value. */
  readonly label?: string;

  // Counts
  readonly spans?: number;
  readonly replacements?: number;
  readonly unknown?: number;
  readonly foreign?: number;
  readonly chunks?: number;
  readonly words?: number;
  readonly tokens?: number;
  readonly count?: number;
  readonly sessions?: number;
  readonly dropped?: number;

  // Sizes
  readonly bytes?: number;
  readonly maxLen?: number;
  readonly cap?: number;

  // HTTP / network
  readonly attempt?: number;
  readonly maxAttempts?: number;
  readonly httpStatus?: number;
  readonly delayMs?: number;

  // Timings
  readonly ms?: number;

  // Filesystem / artifact metadata (paths come from the caller — never
  // synthesised from input text).
  readonly path?: string;
  readonly modelDir?: string;
  readonly url?: string;
  readonly repo?: string;
  readonly revision?: string;

  // State flags
  readonly truncated?: boolean;
  readonly cacheHit?: boolean;
}

const loggerCache = new Map<string, debug.Debugger>();
function getLogger(scope: string): debug.Debugger {
  let logger = loggerCache.get(scope);
  if (logger === undefined) {
    logger = debug(scope);
    loggerCache.set(scope, logger);
  }
  return logger;
}

/**
 * Emit a structured log line under `scope`. Fields are formatted as
 * `key=value` pairs after the event name. When the scope is disabled
 * (per the `DEBUG` env var) the call is a no-op.
 */
export function logf(scope: string, event: string, fields: LogFields = {}): void {
  const logger = getLogger(scope);
  if (!logger.enabled) return;
  const parts: string[] = [event];
  for (const key of Object.keys(fields) as Array<keyof LogFields>) {
    const v = fields[key];
    if (v === undefined) continue;
    parts.push(`${key}=${v}`);
  }
  logger('%s', parts.join(' '));
}
