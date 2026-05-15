// SPDX-License-Identifier: Apache-2.0

/**
 * Per-chunk cap on tokens fed into the model in a single forward pass.
 * Set to 384 to match `gliner_config.json:max_len` on the shipped
 * ONNX model — the runtime rejects sequences longer than this, so the
 * public constant matches what `sanitize()` actually accepts. Inputs
 * longer than this are split into overlapping chunks (see
 * `CHUNK_OVERLAP_TOKENS`) unless `strictLength` is set.
 */
export const MAX_SEQUENCE_LENGTH = 384;

/**
 * Token overlap between consecutive chunks. Spans straddling a chunk
 * boundary appear in both chunks (full coverage if shorter than overlap)
 * and are deduped post-decode.
 */
export const CHUNK_OVERLAP_TOKENS = 64;

/**
 * Hard upper bound on total input tokens after tokenization. Inputs above
 * this are truncated with a debug warning to prevent pathological memory
 * use. ~32k tokens ≈ 128k chars of plain text — far beyond any normal
 * Claude prompt.
 */
export const MAX_INPUT_TOKENS = 32_768;

/** Maximum time spent downloading model artifacts before aborting. */
export const MODEL_DOWNLOAD_TIMEOUT_MS = 300_000;

/**
 * Number of hex chars from the session UUID encoded into each
 * placeholder. Used by `restore()` to detect cross-session mismatches
 * before substituting the wrong PII value back into text.
 *
 * 16 hex chars = 64 bits of session entropy → birthday-safe up to
 * ~2^32 concurrent sessions per process. The previous 8-char / 32-bit
 * value collided at ~2^16 sessions, which is the only cross-tenant
 * barrier inside a single Node process — see F-15 in the audit plan.
 */
export const SESSION_PREFIX_LEN = 16;

/**
 * Regex used to find placeholders in sanitized text during restore.
 * Matches `{{PII_<LABEL>_<index>_<sessionPrefix>}}`. Capture groups:
 * 1 = label (uppercase), 2 = index, 3 = 8-hex-char session prefix.
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
