// SPDX-License-Identifier: Apache-2.0

/**
 * Hard upper bound on tokens fed into the model in a single inference.
 * The upstream tokenizer config says `model_max_length: 128000`, but the
 * ONNX runtime surface and memory footprint make 512 the practical ceiling
 * for the production CPU path. Backends MAY raise this internally; the
 * public API is capped here so user inputs cannot OOM the process.
 */
export const MAX_SEQUENCE_LENGTH = 512;

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
