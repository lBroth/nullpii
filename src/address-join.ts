// SPDX-License-Identifier: Apache-2.0

import type { PiiSpan } from './types/index.js';

const ADDRESS_LABEL = 'private_address';

/** What may sit between two parts of one address on one line: spaces,
 * commas, dashes and slashes, at most 3 characters. The model often emits
 * `Via Roma 1, 20121 Milano` as two spans around `, `. A semicolon or a
 * line break usually separates two addresses, so neither qualifies. */
const ADDRESS_GAP = /^[ \t,/\-–—]{1,3}$/;

/**
 * Join `private_address` spans that only separator characters keep apart
 * (`ADDRESS_GAP`), so one address is masked as one value and the
 * separators inside it are masked with it. Any other span between two
 * address parts prevents the join. The result is ordered by start.
 *
 * @param text - the text the spans index into
 * @param spans - final, non-overlapping spans
 */
export function joinAddressParts(text: string, spans: readonly PiiSpan[]): PiiSpan[] {
  const sorted = [...spans].sort((a, b) => a.start - b.start || a.end - b.end);
  const out: PiiSpan[] = [];
  for (const s of sorted) {
    const prev = out[out.length - 1];
    if (prev !== undefined && joins(text, prev, s)) {
      out[out.length - 1] = {
        ...prev,
        end: s.end,
        score: Math.max(prev.score, s.score),
        text: text.slice(prev.start, s.end),
      };
      continue;
    }
    out.push(s);
  }
  return out;
}

function joins(text: string, a: PiiSpan, b: PiiSpan): boolean {
  if (a.label !== ADDRESS_LABEL || b.label !== ADDRESS_LABEL || a.end > b.start) return false;
  return ADDRESS_GAP.test(text.slice(a.end, b.start));
}
