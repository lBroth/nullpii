// SPDX-License-Identifier: Apache-2.0

/**
 * The padlock the band shows beside its line: the logo's padlock, as small as
 * a terminal draws it — 3 cells wide and one row tall, two half-block pixels
 * high. Closed and teal while nullpii is on,
 * open and amber while it starts, open and red while masking is paused,
 * closed and grey when it is broken. Pure functions, no I/O.
 */

/** The padlock's size in cells: one cell is two pixels, one above the other. */
export const PADLOCK_COLUMNS = 3;
export const PADLOCK_ROWS = 1;

/** The terminal's default colour, as `RasterProps` packs a cell's triplet. */
const DEFAULT = 0x01000000;
/** The upper half block: a cell's top pixel as the glyph, its bottom as the
 * background, so one cell holds two colours. */
const BOTH = 0x2580;
/** The lower half block, for a cell whose bottom pixel alone is set. */
const LOWER = 0x2584;
const BLANK = 0x20;

/** The padlock's looks: teal when nullpii is on, amber while it starts and
 * does not protect yet, red while masking is paused, grey when it is
 * broken (the sidecar cannot be reached). The body's colour goes by column,
 * left to right, as the logo's does. */
export type PadlockTone = 'teal' | 'amber' | 'red' | 'grey';
/** The red of a broken padlock's cross. */
const CROSS = 0x00ef4444;
const TONES: Record<PadlockTone, { body: readonly number[]; shackle: number }> = {
  teal: { body: [0x0000fdfd, 0x0000c5d3, 0x00007594], shackle: 0x0000cbd7 },
  amber: { body: [0x00fbbf24, 0x00f59e0b, 0x00fbbf24], shackle: 0x00fde047 },
  red: { body: [0x00ff4d4d, 0x00ff2b2b, 0x00ff4d4d], shackle: 0x00ff9a9a },
  grey: { body: [0x009ca3af, 0x006b7280, 0x004b5563], shackle: 0x006b7280 },
};

/** The padlock's pixels, top pixel row first: a shackle over a full body.
 * Closed, the shackle is in the middle; open, it is swung to the left. */
function padlockPixels(open: boolean, shackle: number, body: readonly number[]) {
  const top = open ? [shackle, undefined, undefined] : [undefined, shackle, undefined];
  return [top, [...body]];
}

/** The padlock as `Raster` cells: standard padded base64 of the cells'
 * triplets (`columns * rows` of code point, foreground, background, each
 * a little-endian u32). */
export function padlockCells(open: boolean, tone: PadlockTone): string {
  const { body, shackle } = TONES[tone];
  const pixels = padlockPixels(open, shackle, body);
  // A broken padlock has a red mark in the middle of its body.
  if (tone === 'grey') pixels[1] = [body[0], CROSS, body[2]];
  const words = new Uint32Array(PADLOCK_COLUMNS * PADLOCK_ROWS * 3);
  let at = 0;
  for (let y = 0; y < PADLOCK_ROWS; y++) {
    for (let x = 0; x < PADLOCK_COLUMNS; x++) {
      const upper = pixels[y * 2][x];
      const lower = pixels[y * 2 + 1][x];
      const [codePoint, foreground, background] =
        upper !== undefined && lower !== undefined
          ? [BOTH, upper, lower]
          : upper !== undefined
            ? [BOTH, upper, DEFAULT]
            : lower !== undefined
              ? [LOWER, lower, DEFAULT]
              : [BLANK, DEFAULT, DEFAULT];
      words[at++] = codePoint;
      words[at++] = foreground;
      words[at++] = background;
    }
  }
  return new Uint8Array(words.buffer).toBase64();
}
