// SPDX-License-Identifier: Apache-2.0

import {
  GLINER_EXTENDED_CATEGORIES,
  GLINER_MODEL_CATEGORIES,
  GLINER_ZERO_SHOT_EXTRA,
  type PiiSpan,
} from '../src/types/index.js';

/** Classes the model emits per span with the default config: one per
 * prompted label. Mock backends must return logits of this width. */
export const PROMPT_LABEL_COUNT =
  GLINER_MODEL_CATEGORIES.length +
  GLINER_ZERO_SHOT_EXTRA.length +
  GLINER_EXTENDED_CATEGORIES.length;

export function span(label: PiiSpan['label'], start: number, end: number, text: string): PiiSpan {
  return { label, start, end, text, score: 1.0 };
}
