// SPDX-License-Identifier: Apache-2.0
import type { PiiCategory } from './labels.js';
import type { Recognizer } from './recognizer.js';
import type { TransitionBiases } from './transition-biases.js';

/** Hardware/runtime backends the library can dispatch to. */
export type BackendName = 'cpu' | 'mps' | 'cuda' | 'rocm' | 'auto';

/**
 * ONNX model variant the backend will load.
 * - `fp32` — full-precision baseline (~5 GB)
 * - `int4` — quantized; ~6% F1 drop, ~875 MB; default
 *
 * `'auto'` defers to the backend's preferred default (currently `int4`
 * everywhere — small footprint, acceptable accuracy. Pin `'fp32'` for
 * regression baselines or maximum accuracy).
 */
export type ModelVariant = 'fp32' | 'int4' | 'auto';

/** Identifies which model artifact set to load. */
export interface ModelRefConfig {
  readonly repo: string;
  readonly revision: string;
}

/** User-facing configuration for the public `nullpii` API. Every field optional. */
export interface NullPiiConfig {
  /** Local directory holding the fetched model artifacts. */
  readonly modelDir?: string;
  /** Override the default model registry entry. */
  readonly model?: ModelRefConfig;
  /** Hardware backend. `'auto'` picks the best available. */
  readonly backend?: BackendName;
  /** ONNX variant. `'auto'` picks based on backend + memory. */
  readonly variant?: ModelVariant;
  /** Cap on input tokens per chunk. Defaults to `MAX_SEQUENCE_LENGTH` (512).
   * Long inputs are split into overlapping chunks of this size unless
   * `strictLength` is set. */
  readonly maxSequenceLength?: number;
  /** Token overlap between adjacent chunks. Defaults to
   * `CHUNK_OVERLAP_TOKENS` (64). Spans shorter than this never split. */
  readonly chunkOverlap?: number;
  /** Throw `TextTooLongError` instead of chunking when input exceeds
   * `maxSequenceLength`. Default: `false`. */
  readonly strictLength?: boolean;
  /** Global confidence threshold; spans below are dropped. Default: `0` (keep all).
   * Per-label overrides via `categoryThresholds`. */
  readonly threshold?: number;
  /** Per-category confidence thresholds. When set, takes priority over the
   * global `threshold` for that label. Useful when secrets need stricter
   * filtering than names. */
  readonly categoryThresholds?: Partial<Record<PiiCategory, number>>;
  /** Per-category log-prob biases shifted into the Viterbi transition
   * matrix. Lets callers trade precision and recall without retraining.
   * All defaults `0` = no shift (current behavior). */
  readonly transitionBiases?: TransitionBiases;
  /** Number of intra-op threads for the ONNX Runtime session.
   * `0` = ORT default (typically physical core count). Lower values cap
   * CPU usage; higher values may help on big-core machines. */
  readonly intraOpNumThreads?: number;
  /** Number of inter-op threads for the ONNX Runtime session.
   * Rarely needed for token-classification; default `0` (ORT picks). */
  readonly interOpNumThreads?: number;
  /** Timeout for first-time model download. */
  readonly downloadTimeoutMs?: number;
  /** Recognizer set to register at construction.
   * - omitted (default) → `DEFAULT_RECOGNIZERS` from `defaults.ts`
   *   (URL, email, AWS/GitHub/Stripe/OpenAI/Anthropic keys, IBAN, SSN)
   * - `'none'` → no built-in recognizers; only what you add via
   *   `np.addRecognizer(...)` runs as a post-pass
   * - `Recognizer[]` → exact list, replaces defaults (but you can
   *   re-add defaults manually via `import { DEFAULT_RECOGNIZERS }`) */
  readonly recognizers?: 'none' | readonly Recognizer[];
  /** Trim whitespace + common punctuation from span edges as a final
   * post-pass. Improves partial-match (IoU≥0.5) scoring. Default: `true`. */
  readonly boundaryRefine?: boolean;
}
