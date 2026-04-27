// SPDX-License-Identifier: Apache-2.0
//
// Single source of truth for every user-facing default in nullpii.
// Adding a new default? Put it here. Reading a default elsewhere? Import
// from here. No `?? 'auto'` / `?? MAGIC_NUMBER` scattered across modules.
//
// Strict TS index-access fallbacks (e.g. `arr[i] ?? 0` under
// `noUncheckedIndexedAccess`) are NOT user-facing defaults and stay inline.

import type { BackendName, ModelVariant } from './types/index.js';

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
  'rocm',
  'cpu',
];

/** Variant the `ModelManager` downloads when `variant: 'auto'`.
 * `int4f16` (~772 MB) is the smallest variant that still passes the
 * inter-format consistency gate. Halves the first-run download vs int8
 * (~1.5 GB) at a modest accuracy cost (≤6% F1 divergence vs fp32). */
export const MANAGER_DEFAULT_VARIANT: Exclude<ModelVariant, 'auto'> = 'int4f16';

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
