// SPDX-License-Identifier: Apache-2.0

/**
 * Protect user-authored `{{...}}` from colliding with `{{PII_*}}`
 * placeholders during sanitize/restore. PUA sentinel is round-trip
 * safe and effectively never appears in natural text or LLM output.
 */

export const PLACEHOLDER_OPEN = '{{';
/** First char of the 2-char PUA sentinel pair (U+E000). */
export const PLACEHOLDER_SENTINEL_LEFT = '';
/** Second char of the 2-char PUA sentinel pair (U+E001). */
export const PLACEHOLDER_SENTINEL_RIGHT = '';
export const PLACEHOLDER_OPEN_ESCAPED = PLACEHOLDER_SENTINEL_LEFT + PLACEHOLDER_SENTINEL_RIGHT;

export function escapePlaceholders(text: string): string {
  return text.split(PLACEHOLDER_OPEN).join(PLACEHOLDER_OPEN_ESCAPED);
}

export function unescapePlaceholders(text: string): string {
  return text.split(PLACEHOLDER_OPEN_ESCAPED).join(PLACEHOLDER_OPEN);
}
