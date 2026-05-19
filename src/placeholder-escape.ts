// SPDX-License-Identifier: Apache-2.0

/**
 * Protect user-authored `{{...}}` from colliding with `{{PII_*}}`
 * placeholders during sanitize/restore. PUA sentinel is round-trip
 * safe and effectively never appears in natural text or LLM output.
 */

export const PLACEHOLDER_OPEN = '{{';
export const PLACEHOLDER_OPEN_ESCAPED = '';

export function escapePlaceholders(text: string): string {
  return text.split(PLACEHOLDER_OPEN).join(PLACEHOLDER_OPEN_ESCAPED);
}

export function unescapePlaceholders(text: string): string {
  return text.split(PLACEHOLDER_OPEN_ESCAPED).join(PLACEHOLDER_OPEN);
}
