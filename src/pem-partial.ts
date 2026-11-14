// SPDX-License-Identifier: Apache-2.0

import type { RecognizerSpan } from './types/index.js';

/**
 * PEM private keys with only part of the block in the text: the header
 * and the base64 lines after it with no trailer (a paste or a log cut
 * short), or base64 lines and the trailer with no header (a window that
 * starts inside the block). `core:pem-private-key` needs both markers;
 * this walks the lines from the one marker there is.
 *
 * A body line is a base64 run (RFC 7468 §3, RFC 4716 §3, RFC 4880 §6.2)
 * of at least {@link MIN_LINE_CHARS} characters. Only the line that ends
 * the body may be shorter: the one before the trailer, or one that ends
 * in `=` padding. Lines are separated by a newline, a literal `\n` (a key
 * in a JSON string or an env file), or a single space (a key flattened
 * onto one line), the same separator throughout the block. Every line
 * has the indentation of the first one (a key in a YAML block scalar).
 * After a header, `Proc-Type:` and `DEK-Info:` lines (RFC 1421, legacy
 * encrypted OpenSSL keys) and OpenPGP armor headers (RFC 4880 §6.2) may
 * come before the body, with a blank line after them.
 *
 * The walk stops at the first line that is none of these, so it reads
 * each line at most once from each side: linear in the text.
 */

/** Shortest base64 run that counts as a body line, padding excluded:
 * a PEM line is 64 characters (OpenSSH 70, OpenPGP up to 76), and a
 * piece of one cut by a window is still long. */
const MIN_LINE_CHARS = 16;

/** A body holds at least one of these: a base64 run made only of letters
 * is a word, not key material. */
const NON_LETTER_BASE64 = /[0-9+/]/;

/** Header lines allowed between the BEGIN line and the body, each
 * `<name>: <value>`: RFC 1421 encapsulated headers and RFC 4880 armor
 * headers. */
const HEADER_NAMES = [
  'Proc-Type',
  'DEK-Info',
  'Version',
  'Comment',
  'Hash',
  'Charset',
  'MessageID',
];
const HEADER_NAME_END = ': ';
const PADDING = '=';
/** Most `=` a base64 run ends in. */
const MAX_PADDING = 2;

const DASHES = '-----';
const LF = '\n';
const CRLF = '\r\n';
const ESCAPED_LF = '\\n';
const ESCAPED_CRLF = '\\r\\n';
const SPACE = ' ';

type Separator = 'newline' | 'escaped' | 'space';

/** What a forward or backward walk found: where the body starts and
 * ends, and whether it is a block the full-block recognizer matches. */
interface Walk {
  /** Offsets of the body runs walked, `start` of the first and `end` of the last. */
  readonly start: number;
  readonly end: number;
  /** At least one long run, with a digit, `+` or `/` somewhere. */
  readonly keyMaterial: boolean;
  /** The other marker, with the same label, closes the block. */
  readonly complete: boolean;
}

/**
 * `Recognizer.span` hook of `core:pem-private-key-partial`: the span of
 * a PEM private key block from the marker `m` matched, through the body
 * lines on its open side, or `null` when no body is there or the block
 * is whole (`core:pem-private-key` masks it).
 *
 * @param m - a match of `-----(BEGIN|END) (<label>)-----`
 * @param text - the text the match indexes into
 */
export function partialPemKeySpan(m: RegExpExecArray, text: string): RecognizerSpan | null {
  const [marker, side, label] = m;
  if (side === undefined || label === undefined) return null;
  const markerEnd = m.index + marker.length;
  if (side === 'BEGIN') {
    const walk = walkForward(text, markerEnd, `${DASHES}END ${label}${DASHES}`);
    if (walk === null || !walk.keyMaterial || walk.complete) return null;
    return { start: m.index, end: walk.end };
  }
  const walk = walkBackward(text, m.index, `${DASHES}BEGIN ${label}${DASHES}`);
  if (walk === null || !walk.keyMaterial || walk.complete) return null;
  return { start: walk.start, end: markerEnd };
}

/** The body lines after a BEGIN marker that ends at `from`. */
function walkForward(text: string, from: number, trailer: string): Walk | null {
  const kind = separatorKindAt(text, from);
  if (kind === null) return null;
  let pos = from;
  let end = from;
  let depth: string | null = null;
  let headers = kind !== 'space';
  let keyMaterial = false;
  let sawKeyChar = false;
  for (;;) {
    const sep = separatorAt(text, pos, kind);
    if (sep === 0) break;
    const lineStart = pos + sep;
    const indent = kind === 'space' ? '' : text.slice(lineStart, indentEnd(text, lineStart));
    const content = lineStart + indent.length;
    if (headers && separatorAt(text, content, kind) > 0) {
      // The blank line that closes the headers (OpenPGP armor has one
      // even with no headers).
      pos = content;
      headers = false;
      continue;
    }
    depth ??= indent;
    if (indent !== depth) break;
    if (headers && isHeaderLine(text, content)) {
      pos = lineEnd(text, content, kind);
      continue;
    }
    headers = false;
    const run = text.slice(content, base64RunEnd(text, content));
    const padded = run.endsWith('=');
    const long = run.replace(/=+$/, '').length >= MIN_LINE_CHARS;
    if (!long && !padded) break;
    if (long) keyMaterial = true;
    if (NON_LETTER_BASE64.test(run)) sawKeyChar = true;
    pos = content + run.length;
    end = pos;
    // Padding ends the body.
    if (padded) break;
  }
  return {
    start: from,
    end,
    keyMaterial: keyMaterial && sawKeyChar,
    complete: trailerAt(text, end, kind, trailer),
  };
}

/** The body lines before an END marker that starts at `to`. */
function walkBackward(text: string, to: number, header: string): Walk | null {
  const beforeSpace = text.charCodeAt(to - 2);
  const spaced =
    separatorBefore(text, to, 'space') > 0 &&
    (isBase64Char(beforeSpace) || text[to - 2] === PADDING);
  let kind: Separator | null = spaced ? 'space' : null;
  let pos = to;
  if (kind === null) {
    while (pos > 0 && (text[pos - 1] === ' ' || text[pos - 1] === '\t')) pos--;
    kind = separatorBefore(text, pos, 'newline') > 0 ? 'newline' : null;
    kind ??= separatorBefore(text, pos, 'escaped') > 0 ? 'escaped' : null;
  }
  if (kind === null) return null;
  const depth = text.slice(pos, to);
  let start = to;
  let first = true;
  let keyMaterial = false;
  let sawKeyChar = false;
  for (;;) {
    const sep = separatorBefore(text, pos, kind);
    if (sep === 0) break;
    const runEnd = pos - sep;
    const runStart = base64RunStartBefore(text, runEnd, kind);
    const run = text.slice(runStart, runEnd);
    const data = run.replace(/=+$/, '');
    const long = data.length >= MIN_LINE_CHARS;
    // Only the line right before the trailer may be short or padded.
    if (data.length === 0 || (!first && (!long || data.length !== run.length))) break;
    if (long) keyMaterial = true;
    if (NON_LETTER_BASE64.test(run)) sawKeyChar = true;
    start = runStart;
    first = false;
    if (runStart < depth.length || text.slice(runStart - depth.length, runStart) !== depth) break;
    pos = runStart - depth.length;
  }
  const complete = text.endsWith(header, pos - separatorBefore(text, pos, kind));
  return { start, end: to, keyMaterial: keyMaterial && sawKeyChar, complete };
}

/** Which separator follows a BEGIN marker at `i`, if any. */
function separatorKindAt(text: string, i: number): Separator | null {
  for (const kind of ['newline', 'escaped', 'space'] as const) {
    if (separatorAt(text, i, kind) > 0) return kind;
  }
  return null;
}

/** Length of a `kind` separator starting at `i`, 0 when there is none. */
function separatorAt(text: string, i: number, kind: Separator): number {
  if (kind === 'newline') {
    if (text.startsWith(LF, i)) return LF.length;
    return text.startsWith(CRLF, i) ? CRLF.length : 0;
  }
  if (kind === 'escaped') {
    if (text.startsWith(ESCAPED_LF, i)) return ESCAPED_LF.length;
    return text.startsWith(ESCAPED_CRLF, i) ? ESCAPED_CRLF.length : 0;
  }
  return text.startsWith(SPACE, i) ? SPACE.length : 0;
}

/** Length of a `kind` separator ending at `i`, 0 when there is none. */
function separatorBefore(text: string, i: number, kind: Separator): number {
  if (kind === 'newline') {
    if (text.endsWith(CRLF, i)) return CRLF.length;
    return text.endsWith(LF, i) ? LF.length : 0;
  }
  if (kind === 'escaped') {
    if (text.endsWith(ESCAPED_CRLF, i)) return ESCAPED_CRLF.length;
    return text.endsWith(ESCAPED_LF, i) ? ESCAPED_LF.length : 0;
  }
  return text.endsWith(SPACE, i) ? SPACE.length : 0;
}

/** Where the line that starts at `from` ends: at its `kind` separator, or the end of the text. */
function lineEnd(text: string, from: number, kind: Separator): number {
  const needle = kind === 'escaped' ? ESCAPED_LF : LF;
  const i = text.indexOf(needle, from);
  if (i === -1) return text.length;
  // A CRLF line ends before its CR, where `separatorAt` finds the separator.
  if (kind === 'newline' && text.endsWith('\r', i)) return i - 1;
  if (kind === 'escaped' && text.endsWith('\\r', i)) return i - 2;
  return i;
}

/** True when `trailer` closes the body that ends at `end`, on its own line or glued to it. */
function trailerAt(text: string, end: number, kind: Separator, trailer: string): boolean {
  let p = end + separatorAt(text, end, kind);
  if (kind !== 'space') p = indentEnd(text, p);
  return text.startsWith(trailer, p);
}

/** End of the base64 run, with its padding, that starts at `start`. */
function base64RunEnd(text: string, start: number): number {
  let i = start;
  while (i < text.length && isBase64Char(text.charCodeAt(i))) i++;
  if (i === start) return start;
  const runEnd = i;
  while (i < text.length && i - runEnd < MAX_PADDING && text[i] === PADDING) i++;
  return i;
}

/** Start of the base64 run, with its padding, that ends at `end`. A
 * literal `\n` before it is a separator, though its `n` is base64. */
function base64RunStartBefore(text: string, end: number, kind: Separator): number {
  let i = end;
  while (i > 0 && end - i < MAX_PADDING && text[i - 1] === PADDING) i--;
  while (i > 0 && isBase64Char(text.charCodeAt(i - 1))) {
    if (kind === 'escaped' && text.endsWith(ESCAPED_LF, i)) break;
    i--;
  }
  return i;
}

/** End of the spaces and tabs that start at `start`. */
function indentEnd(text: string, start: number): number {
  let i = start;
  while (text[i] === ' ' || text[i] === '\t') i++;
  return i;
}

/** True when a header line (`Proc-Type: …`) starts at `i`. */
function isHeaderLine(text: string, i: number): boolean {
  return HEADER_NAMES.some((name) => text.startsWith(`${name}${HEADER_NAME_END}`, i));
}

/** `[A-Za-z0-9+/]` */
function isBase64Char(c: number): boolean {
  return (
    (c >= 0x41 && c <= 0x5a) ||
    (c >= 0x61 && c <= 0x7a) ||
    (c >= 0x30 && c <= 0x39) ||
    c === 0x2b ||
    c === 0x2f
  );
}
