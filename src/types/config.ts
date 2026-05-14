// SPDX-License-Identifier: Apache-2.0

import type { PiiCategory } from './labels.js';
import type { Recognizer } from './recognizer.js';

/** Hardware/runtime backends the library can dispatch to. */
export type BackendName = 'cpu' | 'mps' | 'cuda' | 'auto';

/** ONNX variant. Reserved for future quantized-shard packs; current
 * release ships FP32 only. */
export type ModelVariant = 'fp32' | 'int4' | 'auto';

/** User-facing configuration for the public `nullpii` API. Every field optional. */
export interface NullPiiConfig {
  /** Local directory holding the fetched model artifacts (`model.onnx`,
   * `tokenizer.json`, `gliner_config.json`, `tokenizer_config.json`).
   * Override only for tests / air-gapped installs / a fork that mirrors
   * the layout verbatim. The default repo + revision are hardcoded. */
  readonly modelDir?: string;
  /** Hardware backend. `'auto'` picks the best available. */
  readonly backend?: BackendName;
  /** ONNX variant. Reserved (FP32 only at present). */
  readonly variant?: ModelVariant;
  /** Cap on subword tokens fed to the GLiNER encoder. Default 384
   * (matches `gliner_config.json:max_len`). Inputs longer than this
   * are silently truncated unless `strictLength` is set. */
  readonly maxSequenceLength?: number;
  /** Throw `TextTooLongError` instead of truncating when input exceeds
   * `maxSequenceLength`. Default: `false`. */
  readonly strictLength?: boolean;
  /** Global confidence threshold; spans below are dropped.
   *
   * Two pipeline stages consume this value:
   *
   *  1. **Decode** (`gliner-decoder`): filters raw GLiNER logits before
   *     they reach the recognizer merge. Unset → `DEFAULT_DECODE_THRESHOLD`
   *     (= 0.5) on the unified ONNX (recall / low-confidence trade-off).
   *  2. **Post-filter** (`applyThresholds`): final pass over the merged
   *     ML + recognizer span set. Unset → `DEFAULT_POST_FILTER_THRESHOLD`
   *     (= 0), i.e. trust decode + recognizer confidences without an
   *     extra global cull. High-confidence recognizers (≥ 0.9) survive.
   *
   * Setting this field applies the same value to BOTH stages — usually
   * what callers mean. For finer control, leave it alone and tune
   * `categoryThresholds`. */
  readonly threshold?: number;
  /** Per-category confidence thresholds applied in the post-filter
   * stage. When set for a label, takes priority over the global
   * `threshold` (and the post-filter default) for that label. */
  readonly categoryThresholds?: Partial<Record<PiiCategory, number>>;
  /** Number of intra-op threads for the ONNX Runtime session. `0` = ORT
   * default (typically physical core count). */
  readonly intraOpNumThreads?: number;
  /** Number of inter-op threads. Rarely useful for span NER; default `0`. */
  readonly interOpNumThreads?: number;
  /** Timeout for first-time model download. */
  readonly downloadTimeoutMs?: number;
  /** Recognizer set to register at construction.
   * - omitted → built-in `DEFAULT_RECOGNIZERS` (URL, email, AWS / GitHub /
   *   Stripe / OpenAI / Anthropic keys, IBAN, SSN, …)
   * - `'none'` → no built-in recognizers; only what you add via `np.addRecognizer(...)`
   * - `Recognizer[]` → exact list, replaces defaults */
  readonly recognizers?: 'none' | readonly Recognizer[];
  /** Trim whitespace + common punctuation from span edges as a final
   * post-pass. Default: `true`. */
  readonly boundaryRefine?: boolean;
}
