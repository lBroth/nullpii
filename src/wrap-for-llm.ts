// SPDX-License-Identifier: Apache-2.0

import type { SanitizeResult } from './types/index.js';

/**
 * Built-in preservation hint emitted by `wrapForLLM`. Saturates round-trip
 * preservation to 100% across all task scenarios tested in
 * `packages/eval/private/scripts/placeholder_llm_with_hint.py` (translate /
 * summarise / rewrite-formal / json-extract / markdown-format / adversarial
 * "ignore-syntax"), even on smaller open-weight models.
 *
 * Cost: ~80 prompt tokens once. Break-even is ~5 placeholders per request.
 */
export const LLM_PRESERVATION_HINT =
  'IMPORTANT: Any text matching the pattern `{{PII_<TYPE>_<N>}}` is a privacy ' +
  'placeholder. Preserve every such placeholder LITERALLY in your output — do ' +
  'not paraphrase, reformat, expand, escape, or substitute them with ' +
  'realistic-looking values. They will be programmatically replaced after ' +
  'your response.';

/**
 * Prefix `sanitized` text with the standard PII-preservation hint, optionally
 * followed by a task instruction. Pass the returned string straight to the
 * downstream LLM as the user message.
 *
 * @example
 * ```ts
 * const safe = await sanitize('Email John at john@x.com');
 * const prompt = wrapForLLM(safe, 'Translate to Italian');
 * // prompt = "IMPORTANT: Any text matching {{PII_<TYPE>_<N>}} is a privacy
 * //          placeholder. Preserve … literally …
 * //
 * //          Translate to Italian
 * //
 * //          Email {{PII_PRIVATE_PERSON_0}} at {{PII_PRIVATE_EMAIL_0}}"
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
