import { isValidStart, isValidTransition, parseLabel } from './labels-bioes.js';
import type { TransitionBiases } from './types/index.js';

const NEG_INF = Number.NEGATIVE_INFINITY;

/**
 * Categorize a valid (`from → to`) transition for bias application.
 *
 * - `background`: `O → O`
 * - `enter`:      `O/E/S → B/S` — opening a new span
 * - `continue`:   `B/I → I/E` — staying inside or closing the active span
 * - `exit`:       `E/S → O` — boundary handoff back to background
 */
function classifyTransition(
  from: string,
  to: string,
): 'background' | 'enter' | 'continue' | 'exit' {
  const f = parseLabel(from);
  const t = parseLabel(to);
  if (f.tag === 'O' && t.tag === 'O') return 'background';
  if (t.tag === 'B' || t.tag === 'S') return 'enter';
  if ((f.tag === 'E' || f.tag === 'S') && t.tag === 'O') return 'exit';
  return 'continue';
}

/**
 * Build an `[N × N]` log-transition matrix.
 *
 * Forbidden transitions are `-Infinity`. Allowed transitions default to
 * `0`; per-category biases (`background`, `enterSpan`, `continueSpan`)
 * are added when supplied — exposing the precision/recall lever the
 * upstream model card recommends.
 */
export function buildTransitionMatrix(
  labels: readonly string[],
  biases: TransitionBiases = {},
): Float64Array {
  const n = labels.length;
  const t = new Float64Array(n * n).fill(NEG_INF);
  const background = biases.background ?? 0;
  const enter = biases.enterSpan ?? 0;
  const cont = biases.continueSpan ?? 0;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const from = labels[i];
      const to = labels[j];
      if (from === undefined || to === undefined || !isValidTransition(from, to)) continue;
      switch (classifyTransition(from, to)) {
        case 'background':
          t[i * n + j] = background;
          break;
        case 'enter':
          t[i * n + j] = enter;
          break;
        case 'continue':
          t[i * n + j] = cont;
          break;
        case 'exit':
          t[i * n + j] = 0;
          break;
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
  biases: TransitionBiases = {},
): string[] {
  if (labelMap.length !== numLabels) {
    throw new Error(
      `viterbiBioesDecode: labelMap length ${labelMap.length} ≠ numLabels ${numLabels}`,
    );
  }
  if (seqLen === 0) return [];

  const transition = buildTransitionMatrix(labelMap, biases);
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

/**
 * Compute log-marginals `P(y_t = j | x)` via the forward-backward
 * algorithm under the same constrained transition graph used by Viterbi.
 *
 * Returned matrix is `[seqLen × numLabels]` of natural-log marginals.
 * Used for span scoring: more faithful to the model's full posterior
 * than the per-token argmax softmax, especially when the chosen path
 * disagrees with local-best labels.
 */
export function forwardBackwardMarginals(
  logits: Float32Array,
  seqLen: number,
  numLabels: number,
  labelMap: readonly string[],
  biases: TransitionBiases = {},
): Float64Array {
  if (labelMap.length !== numLabels) {
    throw new Error(
      `forwardBackwardMarginals: labelMap length ${labelMap.length} ≠ numLabels ${numLabels}`,
    );
  }
  if (seqLen === 0) return new Float64Array(0);

  const transition = buildTransitionMatrix(labelMap, biases);
  const emissions: Float64Array[] = new Array(seqLen);
  for (let t = 0; t < seqLen; t++) emissions[t] = logSoftmaxRow(logits, t * numLabels, numLabels);

  const alpha = new Float64Array(seqLen * numLabels).fill(NEG_INF);
  const beta = new Float64Array(seqLen * numLabels).fill(NEG_INF);

  // Forward pass.
  const e0 = emissions[0] ?? new Float64Array(numLabels);
  for (let j = 0; j < numLabels; j++) {
    const lbl = labelMap[j];
    if (lbl !== undefined && isValidStart(lbl)) {
      alpha[j] = e0[j] ?? NEG_INF;
    }
  }
  for (let t = 1; t < seqLen; t++) {
    const emit = emissions[t] ?? new Float64Array(numLabels);
    for (let j = 0; j < numLabels; j++) {
      let acc = NEG_INF;
      for (let i = 0; i < numLabels; i++) {
        const trans = transition[i * numLabels + j];
        if (trans === undefined || trans === NEG_INF) continue;
        const a = alpha[(t - 1) * numLabels + i];
        if (a === undefined || a === NEG_INF) continue;
        acc = logAdd(acc, a + trans);
      }
      alpha[t * numLabels + j] = acc + (emit[j] ?? NEG_INF);
    }
  }

  // Backward pass — terminal beta = 0 for all labels (no end-state restriction).
  const lastBase = (seqLen - 1) * numLabels;
  for (let j = 0; j < numLabels; j++) beta[lastBase + j] = 0;
  for (let t = seqLen - 2; t >= 0; t--) {
    const emitNext = emissions[t + 1] ?? new Float64Array(numLabels);
    for (let i = 0; i < numLabels; i++) {
      let acc = NEG_INF;
      for (let j = 0; j < numLabels; j++) {
        const trans = transition[i * numLabels + j];
        if (trans === undefined || trans === NEG_INF) continue;
        const b = beta[(t + 1) * numLabels + j];
        if (b === undefined || b === NEG_INF) continue;
        acc = logAdd(acc, trans + (emitNext[j] ?? NEG_INF) + b);
      }
      beta[t * numLabels + i] = acc;
    }
  }

  // Log partition function from final-row alpha.
  let logZ = NEG_INF;
  for (let j = 0; j < numLabels; j++) {
    const v = alpha[lastBase + j];
    if (v !== undefined && v !== NEG_INF) logZ = logAdd(logZ, v);
  }

  const out = new Float64Array(seqLen * numLabels).fill(NEG_INF);
  if (logZ === NEG_INF) return out;
  for (let t = 0; t < seqLen; t++) {
    for (let j = 0; j < numLabels; j++) {
      const a = alpha[t * numLabels + j];
      const b = beta[t * numLabels + j];
      if (a === undefined || b === undefined || a === NEG_INF || b === NEG_INF) continue;
      out[t * numLabels + j] = a + b - logZ;
    }
  }
  return out;
}

function logAdd(a: number, b: number): number {
  if (a === NEG_INF) return b;
  if (b === NEG_INF) return a;
  const max = a > b ? a : b;
  const min = a > b ? b : a;
  return max + Math.log1p(Math.exp(min - max));
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
