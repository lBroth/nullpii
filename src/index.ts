// SPDX-License-Identifier: Apache-2.0

//
// Public API surface. Internal modules (`gliner-tokenizer`,
// `gliner-spans`, `gliner-decoder`, `hf-hub`) are deliberately not
// re-exported.

// Errors
export {
  EngineDisposedError,
  InvalidConfigError,
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
  GLINER_EXTENDED_CATEGORIES,
  GLINER_MODEL_CATEGORIES,
  MAX_SEQUENCE_LENGTH,
  MODEL_DOWNLOAD_TIMEOUT_MS,
  PII_LABELS,
  PLACEHOLDER_REGEX,
  PLACEHOLDER_TEMPLATE,
  SESSION_PREFIX_LEN,
  type BackendName,
  type EnginePolicy,
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
  type SanitizeOptions,
  type MaskResult,
  type SanitizeResult,
  type UrlAllowlistConfig,
  type UrlRelease,
  type VaultToken,
} from './types/index.js';

// Model cache control
export { defaultCacheDir, type EnsureOptions, ModelManager } from './model-manager.js';

// Vault — advanced API for direct vault control
export { PiiVault } from './vault.js';

// Streaming restore — SSE-safe placeholder buffer
export { RestoreStream, type RestoreCapable } from './restore-stream.js';

// Public engine
export { NullPii } from './nullpii.js';

// Shared masking-policy config file (library, CLI, gateway, Claude Code mod)
export {
  type CategoryMode,
  categoryModes,
  configFilePath,
  defaultConfigPath,
  loadConfigFile,
  type NullPiiFileConfig,
  parseConfig,
  resolveConfigFile,
  toEngineConfig,
} from './config-file.js';
export {
  DEFAULT_DISABLED_CATEGORIES,
  DEFAULT_RESTORE_TOOLS,
  DEFAULT_URL_RELEASES,
  MAX_CONFIG_FILE_BYTES,
} from './defaults.js';

// LLM-prompt helper
export { LLM_PRESERVATION_HINT, wrapForLLM } from './wrap-for-llm.js';

// Structural validators — exported so recognizer packs can reuse the
// canonical implementations instead of duplicating them. Each returns
// `true` only when the candidate satisfies the well-defined checksum
// for its format (mod-97 IBAN, Luhn cards, base58check BTC,
// mod-11 × 2 CPF, weighted-position Codice Fiscale, Luhn-style Partita IVA).
export {
  base58CheckValid,
  codiceFiscaleValid,
  cpfValid,
  iban97Valid,
  latLonPairInRange,
  luhnValid,
  macAddressNonReserved,
  partitaIvaValid,
  vinValid,
} from './validators.js';
