// SPDX-License-Identifier: Apache-2.0

/**
 * Server-sent event framing, as the HTML specification defines it: lines
 * end with CRLF, LF or CR; a blank line ends an event; a line starting
 * with `:` is a comment; `field: value` loses one space after the colon;
 * several `data:` lines join with `\n`. Both stream relays read upstream
 * events through this module, so what they judge is what a conforming
 * client would read. Frames are re-emitted with LF line ends.
 */

/** The blank line that ends a frame once line ends are normalised. */
export const FRAME_SEPARATOR = '\n\n';

const LF = '\n';
const CR = '\r';
const CRLF_OR_CR = /\r\n?/g;
const TRAILING_LFS = /\n+$/;
const COMMENT_PREFIX = ':';
const FIELD_SEPARATOR = ':';
const EVENT_FIELD = 'event';
const DATA_FIELD = 'data';

/** The fields of one frame that the relays read. */
export interface SseFields {
  readonly event: string | null;
  /** The `data:` lines joined with `\n`; `null` when the frame has none. */
  readonly data: string | null;
}

/**
 * Splits decoded upstream text into frames. Line ends are normalised to
 * LF; a CR at the end of a chunk is held until the next one shows whether
 * an LF follows, so CRLF split across chunks counts once.
 */
export class SseFrameSplitter {
  private buffer = '';
  private pendingCr = false;

  /** The frames that `text` completes, without their blank line. */
  push(text: string): string[] {
    let chunk = this.pendingCr ? CR + text : text;
    this.pendingCr = chunk.endsWith(CR);
    if (this.pendingCr) chunk = chunk.slice(0, -1);
    this.buffer += chunk.replace(CRLF_OR_CR, LF);
    const frames: string[] = [];
    let sep = this.buffer.indexOf(FRAME_SEPARATOR);
    while (sep !== -1) {
      frames.push(this.buffer.slice(0, sep));
      this.buffer = this.buffer.slice(sep + FRAME_SEPARATOR.length);
      sep = this.buffer.indexOf(FRAME_SEPARATOR);
    }
    return frames;
  }

  /** What is left once the upstream ended: a last frame with no blank
   * line after it, possibly incomplete. */
  end(): string {
    const rest = this.pendingCr ? `${this.buffer}${LF}` : this.buffer;
    this.buffer = '';
    this.pendingCr = false;
    return rest.replace(TRAILING_LFS, '');
  }
}

/** The `event` and `data` fields of one frame. */
export function parseSseFields(frame: string): SseFields {
  let event: string | null = null;
  const data: string[] = [];
  for (const line of frame.split(LF)) {
    if (line === '' || line.startsWith(COMMENT_PREFIX)) continue;
    const colon = line.indexOf(FIELD_SEPARATOR);
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? '' : line.slice(colon + 1);
    if (value.startsWith(' ')) value = value.slice(1);
    if (field === EVENT_FIELD) event = value;
    else if (field === DATA_FIELD) data.push(value);
  }
  return { event, data: data.length > 0 ? data.join(LF) : null };
}

/** One frame as the relays write it. */
export function serialiseFrame(event: string | null, data: Record<string, unknown>): string {
  const prefix = event !== null ? `event: ${event}${LF}` : '';
  return `${prefix}data: ${JSON.stringify(data)}${FRAME_SEPARATOR}`;
}
