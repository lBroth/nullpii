// SPDX-License-Identifier: Apache-2.0

/**
 * The padlock the band shows beside its line: the logo's padlock, as small as
 * a terminal draws it, 3 cells wide and 2 rows tall (two half-block pixels
 * per row, so 3 by 4 pixels). Closed and teal while nullpii is on, open and
 * amber while it starts, open and red while masking is paused, closed and
 * grey when it is broken. Open is the closed padlock with the shackle's
 * right leg one pixel short, so a gap shows between the arch and the body.
 * Pure functions, no I/O.
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
 * broken (the sidecar cannot be reached). */
export type PadlockTone = 'teal' | 'amber' | 'red' | 'grey';
/** The red of a broken padlock's keyhole. */
const CROSS = 0x00ef4444;
interface Palette {
  readonly shackle: number;
  /** The body's colour by column, left to right, as the logo's goes. */
  readonly body: readonly [number, number, number];
  readonly highlight: number;
  readonly keyhole: number;
}
const TONES: Record<PadlockTone, Palette> = {
  teal: {
    shackle: 0x0000cbd7,
    body: [0x0000c5d3, 0x0000a3b8, 0x00007594],
    highlight: 0x007ffcff,
    keyhole: 0x00102a33,
  },
  amber: {
    shackle: 0x00fde047,
    body: [0x00fbbf24, 0x00f59e0b, 0x00d97706],
    highlight: 0x00fde68a,
    keyhole: 0x003c1e00,
  },
  red: {
    shackle: 0x00ff9a9a,
    body: [0x00ff4d4d, 0x00ff2b2b, 0x00dc1f1f],
    highlight: 0x00ffb3b3,
    keyhole: 0x00460000,
  },
  grey: {
    shackle: 0x006b7280,
    body: [0x009ca3af, 0x006b7280, 0x004b5563],
    highlight: 0x00d1d5db,
    keyhole: CROSS,
  },
};

/** The padlock's pixels as roles, top pixel row first: `S` shackle, `H` the
 * body's highlight, `B` body, `K` keyhole. Closed, the shackle's two legs
 * reach the body; open, the right leg is one pixel short. */
const CLOSED = ['SSS', 'S.S', 'HBB', 'BKB'] as const;
const OPEN = ['SSS', 'S..', 'HBB', 'BKB'] as const;

/** The colour of the pixel at column `x` for `role`, or undefined for empty. */
function colourOf(role: string, x: number, palette: Palette): number | undefined {
  if (role === 'S') return palette.shackle;
  if (role === 'H') return palette.highlight;
  if (role === 'K') return palette.keyhole;
  if (role === 'B') return palette.body[x];
  return undefined;
}

/** The padlock as `Raster` cells: standard padded base64 of the cells'
 * triplets (`columns * rows` of code point, foreground, background, each
 * a little-endian u32). */
export function padlockCells(open: boolean, tone: PadlockTone): string {
  const palette = TONES[tone];
  const rows = open ? OPEN : CLOSED;
  const words = new Uint32Array(PADLOCK_COLUMNS * PADLOCK_ROWS * 3);
  let at = 0;
  for (let y = 0; y < PADLOCK_ROWS; y++) {
    for (let x = 0; x < PADLOCK_COLUMNS; x++) {
      const upper = colourOf(rows[y * 2][x], x, palette);
      const lower = colourOf(rows[y * 2 + 1][x], x, palette);
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
