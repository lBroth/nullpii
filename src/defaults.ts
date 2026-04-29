// SPDX-License-Identifier: Apache-2.0
//
// Single source of truth for every user-facing default in nullpii.
// Adding a new default? Put it here. Reading a default elsewhere? Import
// from here. No `?? 'auto'` / `?? MAGIC_NUMBER` scattered across modules.
//
// Strict TS index-access fallbacks (e.g. `arr[i] ?? 0` under
// `noUncheckedIndexedAccess`) are NOT user-facing defaults and stay inline.

import type { BackendName, ModelVariant } from './types/index.js';
import type { Recognizer } from './types/recognizer.js';

/** Backend chosen when the user passes nothing (or `'auto'`) — the router
 * then walks `BACKEND_AUTO_PRIORITY`. */
export const DEFAULT_BACKEND: BackendName = 'auto';

/** Model variant chosen when the user passes nothing (or `'auto'`).
 * Each backend resolves `'auto'` via its own `BackendConfig.autoVariant`. */
export const DEFAULT_VARIANT: ModelVariant = 'auto';

/** Backend lookup order under `DEFAULT_BACKEND === 'auto'`. */
export const BACKEND_AUTO_PRIORITY: readonly Exclude<BackendName, 'auto'>[] = [
  'cuda',
  'mps',
  'cpu',
];

/** Variant the `ModelManager` downloads when `variant: 'auto'`.
 * `int4` (~875 MB, ~6% F1 drop) — small first-run footprint. Pin
 * `variant: 'fp32'` (~5 GB) when you need maximum accuracy or a
 * regression baseline. */
export const MANAGER_DEFAULT_VARIANT: Exclude<ModelVariant, 'auto'> = 'int4';

/** ONNX subdirectory inside a model directory. */
export const ONNX_SUBDIR = 'onnx';

/** Tokenizer file name within a model directory. */
export const TOKENIZER_FILE = 'tokenizer.json';

/** Sigstore signature file name within a model directory (optional artifact). */
export const SIGNATURE_FILE = 'model.sig';

/** SHA256 sidecar suffix (`<file>.sha256`). */
export const CHECKSUM_SUFFIX = '.sha256';

/** XDG-style cache layout. Default: `$XDG_CACHE_HOME/nullpii/` if set,
 * else `~/.cache/nullpii/`. Shared across projects on the same host. */
export const CACHE_DIR_NAME = 'nullpii';
export const CACHE_MODELS_SUBDIR = 'models';

/** Pinned default model registry entry. Pluggable: callers can pass
 * `model: { repo, revision }` in `NullPiiConfig` to swap. */
export const DEFAULT_MODEL_REPO = 'openai/privacy-filter';
export const DEFAULT_MODEL_REVISION = '7ffa9a043d54d1be65afb281eddf0ffbe629385b';

/** Target HF mirror for the publish step (deferred). */
export const TARGET_HF_REPO = 'nullpii/privacy-filter-onnx';

/** Built-in recognizers auto-registered on every `NullPii` instance
 * unless the user passes `recognizers: 'none'` or supplies their own
 * array via config.
 *
 * These are the regex patterns proved necessary in the iter-N eval loop
 * (high precision, low FP rate). The ML model alone misses ~66% of URLs
 * and most secrets even when they are surrounded by clear context.
 *
 * Order is irrelevant — the runtime dedupes overlapping spans by
 * confidence (ML wins, then highest-confidence recognizer). */
export const DEFAULT_RECOGNIZERS: readonly Recognizer[] = [
  // URL: only http(s) + www. — bare-domain.tld dropped (FP-prone).
  {
    id: 'core:url',
    pattern: /\b(?:https?:\/\/|www\.)[^\s<>"]+/g,
    label: 'private_url',
    confidence: 0.95,
  },
  // Email — straightforward.
  {
    id: 'core:email',
    pattern: /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/g,
    label: 'private_email',
    confidence: 0.95,
  },
  // AWS access key (IAM `AKIA…`, STS `ASIA…`).
  {
    id: 'core:aws-access-key',
    pattern: /\b(?:AKIA|ASIA)[0-9A-Z]{16}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  // GitHub PAT (classic + fine-grained).
  {
    id: 'core:github-pat-classic',
    pattern: /\bghp_[A-Za-z0-9]{36,}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:github-server-token',
    pattern: /\bghs_[A-Za-z0-9]{36,}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  {
    id: 'core:github-pat-fine-grained',
    pattern: /\bgithub_pat_[A-Za-z0-9_]{82,}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  // Stripe live/test keys.
  {
    id: 'core:stripe-key',
    pattern: /\bsk_(?:live|test)_[A-Za-z0-9]{24,}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  // OpenAI generic + Anthropic.
  {
    id: 'core:openai-key',
    pattern: /\bsk-[A-Za-z0-9]{32,}\b/g,
    label: 'secret',
    confidence: 0.95,
  },
  {
    id: 'core:anthropic-key',
    pattern: /\bsk-ant-[A-Za-z0-9_-]{50,}\b/g,
    label: 'secret',
    confidence: 0.99,
  },
  // IBAN (rough — IT, GB, DE, FR, ES; trims at non-alphanum).
  {
    id: 'core:iban',
    pattern: /\b[A-Z]{2}\d{2}[A-Z0-9]{1,4}(?:[ \t]?\d{4}){2,5}(?:[ \t]?\d{1,4})?\b/g,
    label: 'account_number',
    confidence: 0.9,
  },
  // SSN (US).
  {
    id: 'core:ssn',
    pattern: /\b\d{3}-\d{2}-\d{4}\b/g,
    label: 'account_number',
    confidence: 0.9,
  },
];

/** Whether `DEFAULT_RECOGNIZERS` are auto-registered on every
 * `NullPii` instance. Override with `new NullPii({ recognizers: 'none' })`
 * or supply a custom list via `recognizers: [...]`. */
export const DEFAULT_RECOGNIZERS_ENABLED = true;

/** Whether to trim leading/trailing whitespace + common punctuation
 * from span edges as a final post-pass. Helps partial-match scoring
 * (IoU >= 0.5) where the model includes trailing dots / brackets that
 * ground-truth annotations exclude. */
export const DEFAULT_BOUNDARY_REFINE = true;

/** Characters trimmed from span edges when boundary-refine is on. */
export const BOUNDARY_REFINE_TRIM_CHARS = ' \t\n\r,.;:!?"\'()[]{}<>';
