import type { PiiCategory } from './labels.js';
import type { Recognizer } from './recognizer.js';

/** Hardware/runtime backends the library can dispatch to. */
export type BackendName = 'cpu' | 'mps' | 'cuda' | 'auto';

/** ONNX variant. Reserved for future quantized-shard packs; current
 * release ships FP32 only. */
export type ModelVariant = 'fp32' | 'int4' | 'auto';

/** User-facing configuration for the public `nullpii` API. Every field optional. */
export interface NullPiiConfig {
  /** Local directory holding the fetched model artifacts. Override only
   * for tests / air-gapped installs / a fork that mirrors the layout
   * verbatim. The default repo (full router stack) is hardcoded. */
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
  /** Global confidence threshold; spans below are dropped. Default: `0.5`.
   * Per-label overrides via `categoryThresholds`. */
  readonly threshold?: number;
  /** Per-category confidence thresholds. When set, takes priority over the
   * global `threshold` for that label. */
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
