// SPDX-License-Identifier: Apache-2.0

/**
 * Per-chunk cap on tokens fed into the model in a single forward pass.
 * The upstream model supports 131072 tokens (banded attention,
 * `sliding_window: 128`), but per-chunk memory still scales with
 * sequence length so 512 is the production CPU sweet spot. Inputs longer
 * than this are split into overlapping chunks (see `CHUNK_OVERLAP_TOKENS`)
 * unless `strictLength` is set.
 */
export const MAX_SEQUENCE_LENGTH = 512;

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

/** Default on-disk model directory, relative to the consumer's `cwd`. */
export const DEFAULT_MODEL_DIR = './models/privacy-filter';

/** Maximum time spent downloading model artifacts before aborting. */
export const MODEL_DOWNLOAD_TIMEOUT_MS = 300_000;

/**
 * Regex used to find placeholders in sanitized text during restore.
 * Matches `[[NULLPII:<label>:<index>]]`. Capture groups: 1 = label, 2 = index.
 * Global flag so `String.prototype.replaceAll` and `matchAll` work.
 */
export const PLACEHOLDER_REGEX = /\[\[NULLPII:([a-z_]+):(\d+)\]\]/g;

/**
 * Build the canonical placeholder string for a vault entry.
 * @param label - the PII label of the original span
 * @param index - 0-based index within the session
 * @returns `[[NULLPII:<label>:<index>]]`
 */
export function PLACEHOLDER_TEMPLATE(label: string, index: number): string {
  return `[[NULLPII:${label}:${index}]]`;
}
