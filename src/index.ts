// SPDX-License-Identifier: Apache-2.0

//
// Public API surface. Internal modules (`gliner-tokenizer`,
// `gliner-spans`, `gliner-decoder`, `hf-hub`) are deliberately not
// re-exported.

// Errors
export {
  InvalidPathError,
  ModelNotFoundError,
  ModelNotInitializedError,
  NullPiiError,
  OrtNotInstalledError,
  SessionMismatchError,
  SessionNotFoundError,
  TextTooLongError,
  UnknownPlaceholderError,
} from './errors.js';

// Types & constants
export {
  GLINER_MODEL_CATEGORIES,
  MAX_SEQUENCE_LENGTH,
  MODEL_DOWNLOAD_TIMEOUT_MS,
  PII_LABELS,
  PLACEHOLDER_REGEX,
  PLACEHOLDER_TEMPLATE,
  SESSION_PREFIX_LEN,
  type BackendName,
  type InferenceInputs,
  type InferenceOutputs,
  type ModelVariant,
  type NullPiiConfig,
  type Recognizer,
  type PiiCategory,
  type PiiLabel,
  type PiiSpan,
  type RestoreOptions,
  type RestoreResult,
  type SanitizeResult,
  type VaultToken,
} from './types/index.js';

// Model cache control
export { defaultCacheDir, type EnsureOptions, ModelManager } from './model-manager.js';

// Vault — advanced API for direct vault control
export { PiiVault } from './vault.js';

// Public engine + functional wrappers
export { NullPii, restore, sanitize } from './nullpii.js';

// LLM-prompt helper
export { LLM_PRESERVATION_HINT, wrapForLLM } from './wrap-for-llm.js';
