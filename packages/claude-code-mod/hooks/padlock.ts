// SPDX-License-Identifier: Apache-2.0

/**
 * The padlock the band shows beside its line: the logo's padlock, small —
 * 3 x 2 cells of half-block pixels. Closed and teal while nullpii is on,
 * open and amber while it starts, open and red while masking is paused,
 * closed and grey when it is broken. Pure functions, no I/O.
 */

/** The padlock's size in cells: one cell is two pixels, one above the other. */
export const PADLOCK_COLUMNS = 3;
export const PADLOCK_ROWS = 2;

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
  amber: { body: [0x00fde68a, 0x00fbbf24, 0x00d97706], shackle: 0x00fcd34d },
  red: { body: [0x00fd6b6b, 0x00fd4d4d, 0x00d32f2f], shackle: 0x00fd8c8c },
  grey: { body: [0x009ca3af, 0x006b7280, 0x004b5563], shackle: 0x006b7280 },
};

/** The padlock's pixels, top pixel row first: the shackle's arc over a
 * full body. Closed, the arc is a U over the body; open, it is swung up
 * beside it, as the logo's paused variant. */
function padlockPixels(open: boolean, shackle: number, body: readonly number[]) {
  const arcTop = open ? [shackle, shackle, undefined] : [undefined, shackle, undefined];
  const arcSide = open ? [shackle, undefined, undefined] : [shackle, undefined, shackle];
  return [arcTop, arcSide, [...body], [...body]];
}

/** The padlock as `Raster` cells: standard padded base64 of the cells'
 * triplets (`columns * rows` of code point, foreground, background, each
 * a little-endian u32). */
export function padlockCells(open: boolean, tone: PadlockTone): string {
  const { body, shackle } = TONES[tone];
  const pixels = padlockPixels(open, shackle, body);
  // A broken padlock carries a red cross over its body.
  if (tone === 'grey') {
    pixels[2] = [CROSS, body[1], CROSS];
    pixels[3] = [body[0], CROSS, body[2]];
  }
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
