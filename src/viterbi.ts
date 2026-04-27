// SPDX-License-Identifier: Apache-2.0
import { isValidStart, isValidTransition } from './labels-bioes.js';

const NEG_INF = Number.NEGATIVE_INFINITY;

/**
 * Build an `[N × N]` log-transition matrix where `T[from*N + to]` is `0`
 * for valid BIOES transitions and `-Infinity` otherwise.
 */
export function buildTransitionMatrix(labels: readonly string[]): Float64Array {
  const n = labels.length;
  const t = new Float64Array(n * n).fill(NEG_INF);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const from = labels[i];
      const to = labels[j];
      if (from !== undefined && to !== undefined && isValidTransition(from, to)) {
        t[i * n + j] = 0;
      }
    }
  }
  return t;
}

/** Numerically stable per-row log-softmax over `numLabels` columns. */
function logSoftmaxRow(logits: Float32Array, offset: number, numLabels: number): Float64Array {
  let max = NEG_INF;
  for (let j = 0; j < numLabels; j++) {
    const v = logits[offset + j] ?? NEG_INF;
    if (v > max) max = v;
  }
  let sumExp = 0;
  for (let j = 0; j < numLabels; j++) {
    sumExp += Math.exp((logits[offset + j] ?? NEG_INF) - max);
  }
  const logZ = max + Math.log(sumExp);
  const out = new Float64Array(numLabels);
  for (let j = 0; j < numLabels; j++) {
    out[j] = (logits[offset + j] ?? NEG_INF) - logZ;
  }
  return out;
}

/**
 * Constrained Viterbi decode for BIOES sequence labelling.
 *
 * @param logits    `[seqLen × numLabels]` row-major raw model output.
 * @param seqLen    number of tokens.
 * @param numLabels number of label classes (must equal `labelMap.length`).
 * @param labelMap  index → label name; index 0 must be `'O'`.
 * @returns array of `seqLen` label strings — globally optimal under the
 *          BIOES transition constraints.
 */
export function viterbiBioesDecode(
  logits: Float32Array,
  seqLen: number,
  numLabels: number,
  labelMap: readonly string[],
): string[] {
  if (labelMap.length !== numLabels) {
    throw new Error(
      `viterbiBioesDecode: labelMap length ${labelMap.length} ≠ numLabels ${numLabels}`,
    );
  }
  if (seqLen === 0) return [];

  const transition = buildTransitionMatrix(labelMap);
  const dp = new Float64Array(seqLen * numLabels).fill(NEG_INF);
  const back = new Int32Array(seqLen * numLabels).fill(-1);

  const emit0 = logSoftmaxRow(logits, 0, numLabels);
  for (let j = 0; j < numLabels; j++) {
    const lbl = labelMap[j];
    if (lbl !== undefined && isValidStart(lbl)) {
      dp[j] = emit0[j] ?? NEG_INF;
    }
  }

  for (let t = 1; t < seqLen; t++) {
    const emit = logSoftmaxRow(logits, t * numLabels, numLabels);
    for (let j = 0; j < numLabels; j++) {
      let bestScore = NEG_INF;
      let bestPrev = -1;
      for (let i = 0; i < numLabels; i++) {
        const trans = transition[i * numLabels + j];
        if (trans === undefined || trans === NEG_INF) continue;
        const prev = dp[(t - 1) * numLabels + i];
        if (prev === undefined || prev === NEG_INF) continue;
        const score = prev + trans;
        if (score > bestScore) {
          bestScore = score;
          bestPrev = i;
        }
      }
      const e = emit[j] ?? NEG_INF;
      dp[t * numLabels + j] = bestScore + e;
      back[t * numLabels + j] = bestPrev;
    }
  }

  return backtrack(dp, back, seqLen, numLabels, labelMap);
}

function backtrack(
  dp: Float64Array,
  back: Int32Array,
  seqLen: number,
  numLabels: number,
  labelMap: readonly string[],
): string[] {
  let bestLast = 0;
  let bestScore = NEG_INF;
  const lastBase = (seqLen - 1) * numLabels;
  for (let j = 0; j < numLabels; j++) {
    const v = dp[lastBase + j] ?? NEG_INF;
    if (v > bestScore) {
      bestScore = v;
      bestLast = j;
    }
  }

  const indices = new Int32Array(seqLen);
  indices[seqLen - 1] = bestLast;
  for (let t = seqLen - 1; t > 0; t--) {
    const prev = back[t * numLabels + (indices[t] ?? 0)];
    indices[t - 1] = prev ?? 0;
  }

  const out: string[] = new Array(seqLen);
  for (let t = 0; t < seqLen; t++) {
    out[t] = labelMap[indices[t] ?? 0] ?? 'O';
  }
  return out;
}
