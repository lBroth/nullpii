// SPDX-License-Identifier: Apache-2.0

/**
 * Subword tokens fed to the model in one forward pass, prompt included:
 * `gliner_config.json:max_len` of the shipped ONNX model. A longer text is
 * read window by window, each window starting at the first word the
 * previous one did not keep (`forEachWindow`), unless `strictLength` is
 * set, which throws `TextTooLongError` instead.
 */
export const MAX_SEQUENCE_LENGTH = 384;

/** Maximum time spent downloading model artifacts before aborting. */
export const MODEL_DOWNLOAD_TIMEOUT_MS = 300_000;

/**
 * Number of hex chars from the session UUID encoded into each
 * placeholder. Used by `restore()` to detect cross-session mismatches
 * before substituting the wrong PII value back into text.
 *
 * 16 hex chars = 64 bits of session entropy. Birthday-collision
 * probability for N concurrent sessions ≈ N² / 2^65 — so
 *   - p < 1 ppm at N ≈ 6 × 10^6 concurrent sessions
 *   - p < 1 / 10^9 at N ≈ 1.9 × 10^5
 * The previous 8-char / 32-bit prefix hit the same probabilities at
 * N ≈ 90 / N ≈ 3, which is the only cross-tenant barrier inside a
 * single Node process — see F-15 in the audit plan.
 */
export const SESSION_PREFIX_LEN = 16;

/**
 * Regex used to find placeholders in sanitized text during restore.
 * Matches `{{PII_<LABEL>_<index>_<sessionPrefix>}}`. Capture groups:
 * 1 = label (uppercase), 2 = index, 3 = 16-hex-char session prefix.
 * Global flag so `String.prototype.replaceAll` and `matchAll` work.
 *
 * The Mustache `{{var}}` syntax is universal in prompt-engineering tooling
 * (Anthropic prompts, LangChain `PromptTemplate`, Jinja2, Handlebars, Vue,
 * Django) — LLMs are deeply trained to leave such tokens untouched, which
 * gives the highest round-trip preservation rate of the formats tested
 * (see `packages/eval/private/PLACEHOLDER_FORMAT_ANALYSIS.md`). Token cost
 * is also lower than the previous `[[NULLPII:type:i]]` format (-20% under
 * the cl100k_base tokenizer).
 */
export const PLACEHOLDER_REGEX = /\{\{PII_([A-Z_]+)_(\d+)_([0-9a-f]{16})\}\}/g;

/**
 * Build the canonical placeholder string for a vault entry.
 * @param label - the PII label of the original span (lowercase, e.g. `private_email`)
 * @param index - 0-based index within the session
 * @param sessionPrefix - first {@link SESSION_PREFIX_LEN} hex chars of the session UUID
 * @returns `{{PII_<LABEL>_<index>_<sessionPrefix>}}` with label uppercased
 */
export function PLACEHOLDER_TEMPLATE(label: string, index: number, sessionPrefix: string): string {
  return `{{PII_${label.toUpperCase()}_${index}_${sessionPrefix}}}`;
}
