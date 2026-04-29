//
// Public API surface. Internal modules (`labels-bioes`, `viterbi`,
// `span-decoder`, `tokenizer`, `hf-hub`) are deliberately not re-exported.

// Errors
export {
  BackendNotAvailableError,
  InvalidPathError,
  ModelNotFoundError,
  ModelNotInitializedError,
  NullPiiError,
  SessionNotFoundError,
  TextTooLongError,
} from './errors.js';

// Types & constants
export {
  DEFAULT_MODEL_DIR,
  MAX_SEQUENCE_LENGTH,
  MODEL_DOWNLOAD_TIMEOUT_MS,
  PII_LABELS,
  PLACEHOLDER_REGEX,
  PLACEHOLDER_TEMPLATE,
  type BackendName,
  type BackendProvider,
  type InferenceInputs,
  type InferenceOutputs,
  type ModelRefConfig,
  type ModelVariant,
  type NullPiiConfig,
  type Recognizer,
  type PiiCategory,
  type PiiLabel,
  type PiiSpan,
  type RestoreResult,
  type SanitizeResult,
  type VaultToken,
} from './types/index.js';

// Advanced control: backend selection + caching
export { selectBackend } from './router.js';
export { defaultCacheDir, type EnsureOptions, ModelManager } from './model-manager.js';

// Vault — advanced API for direct vault control
export { PiiVault } from './vault.js';

// Public engine + functional wrappers
export { NullPii, restore, sanitize } from './nullpii.js';
