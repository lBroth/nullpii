// SPDX-License-Identifier: Apache-2.0

/** Small text helpers for how the mod looks: a progress bar and the short
 * name of what blocks it. Every word here is the mod's own. */

const FILLED = '▰';
const EMPTY = '▱';

/** A bar of `width` cells, `percent` (0 to 100) of them filled: `▰▰▰▱▱▱`. */
export function progressBar(percent: number, width: number): string {
  const part = Math.max(0, Math.min(100, percent));
  const filled = Math.round((part / 100) * width);
  return FILLED.repeat(filled) + EMPTY.repeat(width - filled);
}

/** One entry of the table that names a block in a few words: the texts that
 * block (or a test of them) and the words that stand for them. */
export interface CauseWords {
  readonly matches: (reason: string) => boolean;
  readonly words: string;
}

/** What blocks the mod, in a few words, for the line under the prompt and
 * the band: the first entry of `table` that matches `reason`, or `fallback`. */
export function causeIn(table: readonly CauseWords[], reason: string, fallback: string): string {
  return table.find((entry) => entry.matches(reason))?.words ?? fallback;
}
