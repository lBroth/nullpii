// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { LABEL_MAP, NUM_LABELS, isValidTransition } from '../src/labels-bioes.js';
import { buildTransitionMatrix, viterbiBioesDecode } from '../src/viterbi.js';

const BIG = 100; // a strongly preferred score

function indexOf(label: string): number {
  const i = LABEL_MAP.indexOf(label);
  if (i < 0) throw new Error(`indexOf: missing label ${label}`);
  return i;
}

function makeLogits(seqLen: number, prefer: ReadonlyArray<string | null>): Float32Array {
  if (prefer.length !== seqLen) throw new Error('prefer.length must equal seqLen');
  const out = new Float32Array(seqLen * NUM_LABELS);
  for (let t = 0; t < seqLen; t++) {
    const target = prefer[t];
    if (target === null || target === undefined) continue;
    out[t * NUM_LABELS + indexOf(target)] = BIG;
  }
  return out;
}

describe('buildTransitionMatrix', () => {
  it('produces an N×N float64 matrix', () => {
    const t = buildTransitionMatrix(LABEL_MAP);
    expect(t.length).toBe(NUM_LABELS * NUM_LABELS);
  });

  it('marks valid pairs as 0 and invalid as -Infinity', () => {
    const t = buildTransitionMatrix(LABEL_MAP);
    const oToO = t[indexOf('O') * NUM_LABELS + indexOf('O')];
    expect(oToO).toBe(0);
    const oToI = t[indexOf('O') * NUM_LABELS + indexOf('I-secret')];
    expect(oToI).toBe(Number.NEGATIVE_INFINITY);
  });
});

describe('viterbiBioesDecode', () => {
  it('returns an empty array for seqLen=0', () => {
    expect(viterbiBioesDecode(new Float32Array(0), 0, NUM_LABELS, LABEL_MAP)).toEqual([]);
  });

  it('output length always equals seqLen', () => {
    const seqLen = 7;
    const logits = makeLogits(seqLen, ['O', 'O', 'O', 'O', 'O', 'O', 'O']);
    const out = viterbiBioesDecode(logits, seqLen, NUM_LABELS, LABEL_MAP);
    expect(out).toHaveLength(seqLen);
  });

  it('all-zero logits with O preferred returns all O', () => {
    const seqLen = 5;
    const logits = makeLogits(seqLen, ['O', 'O', 'O', 'O', 'O']);
    const out = viterbiBioesDecode(logits, seqLen, NUM_LABELS, LABEL_MAP);
    expect(out).toEqual(['O', 'O', 'O', 'O', 'O']);
  });

  it('decodes a coherent B-I-E sequence as a single entity', () => {
    const logits = makeLogits(5, [
      'O',
      'B-private_email',
      'I-private_email',
      'E-private_email',
      'O',
    ]);
    const out = viterbiBioesDecode(logits, 5, NUM_LABELS, LABEL_MAP);
    expect(out).toEqual(['O', 'B-private_email', 'I-private_email', 'E-private_email', 'O']);
  });

  it('decodes an S- as a single-token entity', () => {
    const logits = makeLogits(3, ['O', 'S-secret', 'O']);
    const out = viterbiBioesDecode(logits, 3, NUM_LABELS, LABEL_MAP);
    expect(out).toEqual(['O', 'S-secret', 'O']);
  });

  it('never produces an invalid transition even when logits push for one', () => {
    const logits = makeLogits(4, [
      'O',
      'B-secret',
      'S-secret', // the model is being pushy: B → S is INVALID
      'O',
    ]);
    const out = viterbiBioesDecode(logits, 4, NUM_LABELS, LABEL_MAP);
    for (let i = 0; i < out.length - 1; i++) {
      const f = out[i];
      const t = out[i + 1];
      if (f !== undefined && t !== undefined) {
        expect(isValidTransition(f, t)).toBe(true);
      }
    }
  });

  it('forces multi-token entity to use B-...-E-, never B-...-O directly', () => {
    const logits = makeLogits(3, ['B-secret', 'I-secret', 'O']);
    const out = viterbiBioesDecode(logits, 3, NUM_LABELS, LABEL_MAP);
    if (out[0]?.startsWith('B-')) {
      expect(out[1]).toMatch(/^[IE]-/);
    }
  });

  it('throws when labelMap length mismatches numLabels', () => {
    expect(() =>
      viterbiBioesDecode(new Float32Array(NUM_LABELS), 1, NUM_LABELS - 1, LABEL_MAP),
    ).toThrow();
  });
});
