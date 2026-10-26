// SPDX-License-Identifier: Apache-2.0

/** One window of a long text: `text.slice(start, end)`. */
export interface Segment {
  readonly start: number;
  readonly end: number;
}

const LINE_BREAK = '\n';
const WHITESPACE = /\s/;
/** A window's end moves back at most this fraction of the window to reach
 * a line break or whitespace. */
const CUT_SEARCH_FRACTION = 4;

/**
 * Overlapping windows that cover `text`, for a text longer than one
 * detection pass reads (`MAX_INPUT_CHARS`). Each window holds at most
 * `maxChars` characters and overlaps the next by at least `overlap`, so a
 * value shorter than `overlap` that crosses a window's end lies whole
 * inside the next window. A window ends after a line break where one lies
 * in its last quarter, else after whitespace, so a cut rarely splits a
 * value at all; the next window starts the same way, at least `overlap`
 * characters before that end. No cut splits a surrogate pair.
 *
 * Only a run with no whitespace in the window's last quarter (a base64
 * blob, minified code, a long URL) is cut in the middle. The next window
 * then starts where that run starts, so a run of up to half a window
 * lies whole in it (with `overlap` at most an eighth of `maxChars`):
 * values longer than `overlap`, such as an encoded secret, are not split.
 *
 * A text of at most `maxChars` characters is one window.
 */
export function segmentWindows(text: string, maxChars: number, overlap: number): Segment[] {
  if (!(overlap > 0 && overlap * CUT_SEARCH_FRACTION <= maxChars)) {
    throw new RangeError(
      `overlap ${overlap} must be positive and at most a quarter of ${maxChars}`,
    );
  }
  const out: Segment[] = [];
  let start = 0;
  for (;;) {
    const limit = start + maxChars;
    if (limit >= text.length) {
      out.push({ start, end: text.length });
      return out;
    }
    const end = cutBefore(text, limit, limit - Math.floor(maxChars / CUT_SEARCH_FRACTION));
    out.push({ start, end });
    const next = cutBefore(text, end - overlap, end - 2 * overlap);
    // A cut inside a run: restart at the run, if that still moves on.
    const run = runStartAt(text, end);
    const moved = start + Math.floor(maxChars / CUT_SEARCH_FRACTION);
    start = run !== null && run >= moved ? Math.min(run, next) : next;
  }
}

/** Where the run of non-whitespace characters around `offset` starts,
 * when `offset` falls inside one; else `null`. */
function runStartAt(text: string, offset: number): number | null {
  const inRun = (i: number) => i >= 0 && i < text.length && !WHITESPACE.test(text.charAt(i));
  if (!inRun(offset - 1) || !inRun(offset)) return null;
  let i = offset - 1;
  while (inRun(i - 1)) i--;
  return i;
}

/** The last offset in `[floor, limit]` right after a line break, else
 * right after whitespace, else `limit` itself; never inside a surrogate
 * pair. */
function cutBefore(text: string, limit: number, floor: number): number {
  const lineBreak = text.lastIndexOf(LINE_BREAK, limit - 1);
  if (lineBreak >= floor) return lineBreak + 1;
  for (let i = limit - 1; i >= floor; i--) {
    if (WHITESPACE.test(text.charAt(i))) return i + 1;
  }
  return outsideSurrogatePair(text, limit);
}

/** `offset`, moved back one unit if it falls between the two halves of a
 * surrogate pair. */
function outsideSurrogatePair(text: string, offset: number): number {
  const before = text.charCodeAt(offset - 1);
  const after = text.charCodeAt(offset);
  const splitsPair = before >= 0xd800 && before <= 0xdbff && after >= 0xdc00 && after <= 0xdfff;
  return splitsPair ? offset - 1 : offset;
}
