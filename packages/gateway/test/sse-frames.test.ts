// SPDX-License-Identifier: Apache-2.0
//
// SSE framing as the HTML specification defines it, which both stream
// relays read upstream events through.

import { describe, expect, it } from 'vitest';
import { SseFrameSplitter, parseSseFields } from '../src/sse-frames.js';

function splitAll(chunks: readonly string[]): string[] {
  const splitter = new SseFrameSplitter();
  const frames = chunks.flatMap((c) => splitter.push(c));
  const rest = splitter.end();
  return rest === '' ? frames : [...frames, rest];
}

describe('SseFrameSplitter', () => {
  it.each([
    ['LF', ['data: a\n\ndata: b\n\n']],
    ['CRLF', ['data: a\r\n\r\ndata: b\r\n\r\n']],
    ['CR', ['data: a\r\rdata: b\r\r']],
    ['CRLF split between chunks', ['data: a\r', '\n\r', '\ndata: b\r\n\r\n']],
  ])('splits frames on blank lines with %s line ends', (_ends, chunks) => {
    expect(splitAll(chunks)).toEqual(['data: a', 'data: b']);
  });

  it('keeps a last frame with no blank line after it for the caller to judge', () => {
    expect(splitAll(['data: a\n\ndata: b\n'])).toEqual(['data: a', 'data: b']);
    expect(splitAll(['data: a\n\ndata: b\r'])).toEqual(['data: a', 'data: b']);
  });
});

describe('parseSseFields', () => {
  it('joins data lines with a newline and drops one space after the colon only', () => {
    expect(parseSseFields('event: e\ndata:  two spaces\ndata:none')).toEqual({
      event: 'e',
      data: ' two spaces\nnone',
    });
  });

  it('ignores comments and unknown fields, and reads a bare field name as empty', () => {
    expect(parseSseFields(': keep-alive\nid: 7\ndata')).toEqual({ event: null, data: '' });
    expect(parseSseFields(': only a comment')).toEqual({ event: null, data: null });
  });
});
