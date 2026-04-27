// SPDX-License-Identifier: Apache-2.0

/** Hardware/runtime backends the library can dispatch to. */
export type BackendName = 'cpu' | 'mps' | 'cuda' | 'rocm' | 'auto';

/**
 * ONNX model variant the backend will load.
 * - `fp32` — full-precision baseline
 * - `fp16` — half-precision; lossless in practice (≤0.5% F1 divergence)
 * - `int8` — dynamic quantization; production-acceptable (≤1% divergence)
 * - `int4` / `int4f16` — edge / memory-constrained (≤6% divergence)
 *
 * `'auto'` picks the most accurate variant the chosen backend can run
 * without exceeding available memory.
 */
export type ModelVariant = 'fp32' | 'fp16' | 'int8' | 'int4' | 'int4f16' | 'auto';

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
  /** Cap on input tokens per inference. Defaults to `MAX_SEQUENCE_LENGTH`. */
  readonly maxSequenceLength?: number;
  /** Throw `TextTooLongError` instead of silently truncating. Default: `false`. */
  readonly strictLength?: boolean;
  /** Confidence threshold; spans below are dropped. Default: `0` (keep all). */
  readonly threshold?: number;
  /** Timeout for first-time model download. */
  readonly downloadTimeoutMs?: number;
}
