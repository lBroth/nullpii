// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it } from 'vitest';
import { DEFAULT_RECOGNIZERS } from '../src/defaults.js';
import { runRecognizers } from '../src/recognizers.js';
import type { PiiSpan } from '../src/types/index.js';

// `core:ipv6-full` has confidence 0.85 (< 0.9), so it defers to model
// spans. It must only defer when the model already covers the match.
const IPV6 = '2a02:0c7f:85a3:0000:0000:8a2e:0370:7334'; // not 2001:db8::/32 (documentation range, never PII)
const text = `peer ${IPV6} closed`;
const start = text.indexOf(IPV6);
const mlSpan = (s: number, e: number): PiiSpan => ({
  label: 'account_number',
  start: s,
  end: e,
  score: 0.07,
  text: text.slice(s, e),
});
const ipSpans = (existing: PiiSpan[]) =>
  runRecognizers(text, DEFAULT_RECOGNIZERS, existing).filter((s) => s.label === 'private_ip');

describe('low-confidence recognizer deferral', () => {
  it('still emits when a model span covers only part of the match', () => {
    const out = ipSpans([mlSpan(start, start + 4)]);
    expect(out.map((s) => s.text)).toEqual([IPV6]);
  });

  it('defers when a model span already covers the whole match', () => {
    expect(ipSpans([mlSpan(start - 1, start + IPV6.length + 1)])).toEqual([]);
  });

  it('emits when nothing overlaps', () => {
    expect(ipSpans([]).map((s) => s.text)).toEqual([IPV6]);
  });
});
