// SPDX-License-Identifier: Apache-2.0

import type { PiiSpan } from '../src/types/index.js';

export function span(label: PiiSpan['label'], start: number, end: number, text: string): PiiSpan {
  return { label, start, end, text, score: 1.0 };
}
