/**
 * Tunable log-prob biases added to the Viterbi transition matrix.
 *
 * Forbidden BIOES transitions stay `-Infinity`. Allowed transitions in each
 * category get the corresponding bias added before the dynamic-programming
 * pass — letting callers shift the precision/recall tradeoff without
 * retraining the model.
 *
 * All fields default to `0` (no shift, identical to the unbiased decoder).
 *
 * Practical guide:
 * - **Boost recall** (catch more spans, accept a few false positives):
 *   `enterSpan: +0.5` or `background: -0.5`.
 * - **Boost precision** (drop borderline detections): `enterSpan: -0.5` or
 *   `background: +0.5`.
 * - **Keep multi-token spans intact** (avoid fragmentation in long names,
 *   addresses, secrets): `continueSpan: +0.3`.
 */
export interface TransitionBiases {
  /** Bias on `O → O` self-loops (staying in the background class). */
  readonly background?: number;
  /** Bias on transitions that *open* a new span (`O/E/S → B/S`). */
  readonly enterSpan?: number;
  /** Bias on transitions that *stay inside or close* an active span
   * (`B/I → I/E`). */
  readonly continueSpan?: number;
}
