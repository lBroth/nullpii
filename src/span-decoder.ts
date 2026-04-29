import { parseLabel } from './labels-bioes.js';
import type { PiiCategory, PiiSpan } from './types/index.js';

/**
 * Decode a sequence of BIOES labels into character-level `PiiSpan`s using
 * the tokenizer's offset mapping.
 *
 * Assumes a Viterbi-constrained label sequence (no invalid transitions).
 * Multi-token entities (`B-X`, `I-X`, ..., `E-X`) coalesce into one span
 * spanning from the first token's start char to the last token's end char.
 * `S-X` is emitted as a one-token span.
 *
 * @param labels per-token BIOES labels.
 * @param offsetMapping per-token `[startChar, endChar]` from the tokenizer.
 * @param scores per-token softmax scores for the chosen label (`[seqLen]`);
 *   the span score is the mean of its tokens.
 * @param text the original input text — used to populate `span.text`.
 */
export function decodeSpans(
  labels: readonly string[],
  offsetMapping: ReadonlyArray<readonly [number, number]>,
  scores: ReadonlyArray<number>,
  text: string,
): PiiSpan[] {
  if (labels.length !== offsetMapping.length || labels.length !== scores.length) {
    throw new Error(
      `decodeSpans: length mismatch labels=${labels.length} ` +
        `offsets=${offsetMapping.length} scores=${scores.length}`,
    );
  }
  const spans: PiiSpan[] = [];
  let cur: { entity: PiiCategory; start: number; end: number; tokenScores: number[] } | null = null;

  for (let i = 0; i < labels.length; i++) {
    const label = labels[i];
    const offset = offsetMapping[i];
    const score = scores[i];
    if (label === undefined || offset === undefined || score === undefined) continue;
    const parsed = parseLabel(label);

    if (parsed.tag === 'O') {
      cur = null;
      continue;
    }
    if (parsed.tag === 'B') {
      cur = { entity: parsed.entity, start: offset[0], end: offset[1], tokenScores: [score] };
      continue;
    }
    if (parsed.tag === 'I' && cur !== null && cur.entity === parsed.entity) {
      cur.end = offset[1];
      cur.tokenScores.push(score);
      continue;
    }
    if (parsed.tag === 'E' && cur !== null && cur.entity === parsed.entity) {
      cur.end = offset[1];
      cur.tokenScores.push(score);
      spans.push(buildSpan(cur, text));
      cur = null;
      continue;
    }
    if (parsed.tag === 'S') {
      spans.push(
        buildSpan(
          { entity: parsed.entity, start: offset[0], end: offset[1], tokenScores: [score] },
          text,
        ),
      );
      cur = null;
    }
  }
  return spans;
}

function buildSpan(
  acc: { entity: PiiCategory; start: number; end: number; tokenScores: number[] },
  text: string,
): PiiSpan {
  const sum = acc.tokenScores.reduce((s, v) => s + v, 0);
  return {
    label: acc.entity,
    start: acc.start,
    end: acc.end,
    score: sum / acc.tokenScores.length,
    text: text.slice(acc.start, acc.end),
  };
}
