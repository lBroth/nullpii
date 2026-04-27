// SPDX-License-Identifier: Apache-2.0
import { PII_LABELS, type PiiCategory } from './types/index.js';

/** BIOES tag of a label. `O` = outside any span. */
export type BioesTag = 'O' | 'B' | 'I' | 'E' | 'S';

/** Parsed label: just the tag for `'O'`, otherwise tag + entity category. */
export type ParsedLabel =
  | { readonly tag: 'O' }
  | { readonly tag: 'B' | 'I' | 'E' | 'S'; readonly entity: PiiCategory };

/**
 * Full label set for `openai/privacy-filter` at the pinned revision.
 * 33 labels: `'O'` + 8 categories × {B, I, E, S}, in the order used by
 * the model's `config.json` `id2label` mapping.
 */
export const LABEL_MAP: readonly string[] = (() => {
  const out: string[] = ['O'];
  for (const label of PII_LABELS) {
    if (label === 'O') continue;
    out.push(`B-${label}`, `I-${label}`, `E-${label}`, `S-${label}`);
  }
  return out;
})();

/** Total number of labels emitted by the model — `LABEL_MAP.length`. */
export const NUM_LABELS = LABEL_MAP.length;

/** Parse a BIOES label string. Throws for malformed input. */
export function parseLabel(label: string): ParsedLabel {
  if (label === 'O') return { tag: 'O' };
  const dash = label.indexOf('-');
  if (dash <= 0 || dash === label.length - 1) {
    throw new Error(`parseLabel: malformed label '${label}'`);
  }
  const tag = label.slice(0, dash);
  const entity = label.slice(dash + 1) as PiiCategory;
  if (tag !== 'B' && tag !== 'I' && tag !== 'E' && tag !== 'S') {
    throw new Error(`parseLabel: unknown tag '${tag}' in '${label}'`);
  }
  return { tag, entity };
}

/**
 * Whether a transition `from → to` is valid under BIOES constraints.
 *
 * Rules:
 * - `O`, `E-*`, `S-*` may be followed by `O`, `B-*`, `S-*`
 * - `B-X` and `I-X` may only be followed by `I-X` or `E-X` (same entity)
 */
export function isValidTransition(from: string, to: string): boolean {
  const f = parseLabel(from);
  const t = parseLabel(to);
  const isOpen = f.tag === 'B' || f.tag === 'I';
  if (isOpen) {
    return (t.tag === 'I' || t.tag === 'E') && t.entity === f.entity;
  }
  return t.tag === 'O' || t.tag === 'B' || t.tag === 'S';
}

/** Whether `tag` is permitted as the first label of a sequence. */
export function isValidStart(label: string): boolean {
  const p = parseLabel(label);
  return p.tag === 'O' || p.tag === 'B' || p.tag === 'S';
}
