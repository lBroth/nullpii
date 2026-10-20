// SPDX-License-Identifier: Apache-2.0

import type { PiiCategory } from './labels.js';
import type { Recognizer } from './recognizer.js';

/** Hardware/runtime backends the library can dispatch to. */
export type BackendName = 'cpu' | 'mps' | 'cuda' | 'auto';

/** ONNX precision. `'fp16'` is for the CUDA backend, where it is faster
 * with the same measured recall. `'auto'` picks fp16 on CUDA when the model
 * ships it, and fp32 everywhere else. */
export type ModelVariant = 'fp32' | 'fp16' | 'auto';

/** User-facing configuration for the public `nullpii` API. Every field optional. */
export interface NullPiiConfig {
  /** Local directory holding the fetched model artifacts (`model.onnx`,
   * `tokenizer.json`, `gliner_config.json`, `tokenizer_config.json`).
   * Override only for tests / air-gapped installs / a fork that mirrors
   * the layout verbatim. The default repo + revision are hardcoded. */
  readonly modelDir?: string;
  /** Hardware backend. `'auto'` picks the best available. */
  readonly backend?: BackendName;
  /** ONNX precision. Default `'auto'`: `model_fp16.onnx` with
   * `backend: 'cuda'` when the model directory or revision has it, else
   * `model.onnx`. `'fp16'` requires `model_fp16.onnx`; `'fp32'` always loads
   * `model.onnx`. */
  readonly variant?: ModelVariant;
  /** Cap on subword tokens fed to the GLiNER encoder per window. Default
   * 384 (matches `gliner_config.json:max_len`). A window longer than this
   * is cut and the next window resumes at the first word that was cut, so
   * every word still reaches the model. */
  readonly maxSequenceLength?: number;
  /** Throw `TextTooLongError` whenever a window exceeds
   * `maxSequenceLength`, instead of re-windowing. Default: `false`. */
  readonly strictLength?: boolean;
  /** Global confidence threshold; spans below are dropped.
   *
   * Two pipeline stages consume this value:
   *
   *  1. **Decode** (`gliner-decoder`): filters raw GLiNER logits before
   *     they reach the recognizer merge. Unset → `DEFAULT_DECODE_THRESHOLD`
   *     (= 0.05): recall-first, because a missed character leaks.
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
   * `threshold` (and the post-filter default) for that label. Unset →
   * `DEFAULT_CATEGORY_THRESHOLDS` (IP and MAC at 0.5, date 0.125, email 0.075);
   * passing any object replaces those defaults entirely. */
  readonly categoryThresholds?: Partial<Record<PiiCategory, number>>;
  /** Categories to leave unmasked. They are not prompted to the model
   * (fewer labels also mean a shorter prompt per window) and their spans
   * are dropped from every detector, recognizers included. Default: none,
   * so every category is masked. Typical use: keep organisations and
   * occupations visible in business text with
   * `['private_organization', 'private_occupation']`. */
  readonly disabledCategories?: readonly PiiCategory[];
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
  /** Which URLs stay readable. A URL is released only when it holds no
   * credentials, no second URL and no other PII span. Default: the
   * built-in policy (`DEFAULT_URL_RELEASES`): code hosts such as
   * github.com keep only their host readable, reference and package
   * hosts the whole URL. Pass `'none'` to mask every URL, or a
   * {@link UrlAllowlistConfig} to change hosts. */
  readonly urlAllowlist?: 'none' | UrlAllowlistConfig;
}

/** How much of a URL on a listed host stays readable:
 * - `'full'`: the whole URL;
 * - `'host'`: the scheme and host; the path, query and fragment are masked;
 * - `'mask'`: nothing (use it to switch off a built-in host). */
export type UrlRelease = 'full' | 'host' | 'mask';

/** Per-host URL policy. */
export interface UrlAllowlistConfig {
  /** Host → release, merged over the built-in policy. A key is a
   * lowercase host (`docs.python.org`), or `*.` and a domain for the
   * domain and every subdomain (`*.github.com`). The most specific key
   * wins: an exact host, then the nearest wildcard. */
  readonly hosts?: Readonly<Record<string, UrlRelease>>;
  /** `true`: use only `hosts`, without the built-in policy. Default `false`. */
  readonly replaceDefaults?: boolean;
}
