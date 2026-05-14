// SPDX-License-Identifier: Apache-2.0

import type { SanitizeResult } from './types/index.js';

/**
 * Built-in preservation hint emitted by `wrapForLLM`. Tuned to saturate
 * round-trip preservation across translate / summarise / rewrite-formal /
 * json-extract / markdown-format / adversarial "ignore-syntax" scenarios
 * (see `packages/eval/private/scripts/placeholder_llm_with_hint.py`).
 *
 * The runtime placeholder shape is 4 segments: `{{PII_<TYPE>_<N>_<HEX>}}`
 * (see `src/types/constants.ts:PLACEHOLDER_TEMPLATE`). The trailing hex
 * segment binds each placeholder to its minting session and is verified
 * by `restore()` — dropping it breaks the session-prefix check and turns
 * a benign rewrite into a `SessionMismatchError` / silent
 * `unknownPlaceholders` surfacing. The hint calls this out explicitly so
 * the LLM doesn't "tidy up" the placeholder by trimming what looks like
 * a noisy suffix.
 *
 * Cost: 103 prompt tokens (cl100k_base) / 102 (o200k_base), measured
 * 2026-05-14 — emitted once per request, not per placeholder. Break-even
 * ~7 placeholders per request relative to letting the LLM rewrite them.
 */
export const LLM_PRESERVATION_HINT =
  'IMPORTANT: Any text matching the pattern `{{PII_<TYPE>_<N>_<HEX>}}` is a ' +
  'privacy placeholder (e.g. `{{PII_PRIVATE_EMAIL_0_a1b2c3d4}}`). Preserve ' +
  'every such placeholder LITERALLY and IN FULL in your output — do not ' +
  'paraphrase, reformat, expand, escape, or substitute them with realistic-' +
  'looking values, and do not drop the trailing hex session segment. They ' +
  'will be programmatically replaced after your response.';

/**
 * Prefix `sanitized` text with the standard PII-preservation hint, optionally
 * followed by a task instruction. Pass the returned string straight to the
 * downstream LLM as the user message.
 *
 * @example
 * ```ts
 * const safe = await sanitize('Email John at john@x.com');
 * const prompt = wrapForLLM(safe, 'Translate to Italian');
 * // prompt = "IMPORTANT: Any text matching {{PII_<TYPE>_<N>_<HEX>}} is a
 * //          privacy placeholder. Preserve … literally …
 * //
 * //          Translate to Italian
 * //
 * //          Email {{PII_PRIVATE_PERSON_0_a1b2c3d4}} at {{PII_PRIVATE_EMAIL_0_a1b2c3d4}}"
 * const reply = await llm(prompt);  // any model
 * const out = restore(reply, safe.sessionId);
 * ```
 *
 * @param sanitized - either a `SanitizeResult` (preferred) or the raw
 *   `sanitized` string from a previous `sanitize()` call.
 * @param task - optional task instruction inserted between the hint and the
 *   sanitized body. If omitted, the hint is followed by the body alone.
 * @returns the wrapped prompt string ready to send to the LLM.
 */
export function wrapForLLM(sanitized: SanitizeResult | string, task?: string): string {
  const body = typeof sanitized === 'string' ? sanitized : sanitized.sanitized;
  const trimmedTask = task?.trim();
  if (trimmedTask !== undefined && trimmedTask.length > 0) {
    return `${LLM_PRESERVATION_HINT}\n\n${trimmedTask}\n\n${body}`;
  }
  return `${LLM_PRESERVATION_HINT}\n\n${body}`;
}
