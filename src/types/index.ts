// SPDX-License-Identifier: Apache-2.0

export {
  GLINER_EXTENDED_CATEGORIES,
  GLINER_MODEL_CATEGORIES,
  GLINER_ZERO_SHOT_EXTRA,
  PII_LABELS,
  type PiiCategory,
  type PiiLabel,
} from './labels.js';
export {
  MAX_SEQUENCE_LENGTH,
  MODEL_DOWNLOAD_TIMEOUT_MS,
  PLACEHOLDER_REGEX,
  PLACEHOLDER_TEMPLATE,
  SESSION_PREFIX_LEN,
} from './constants.js';
export type { PiiSpan } from './spans.js';
export type { VaultToken } from './vault.js';
export type {
  RestoreOptions,
  RestoreResult,
  SanitizeOptions,
  MaskResult,
  SanitizeResult,
} from './results.js';
export type {
  BackendName,
  EnginePolicy,
  ModelVariant,
  NullPiiConfig,
  UrlAllowlistConfig,
  UrlRelease,
} from './config.js';
export type { InferenceInputs, InferenceOutputs } from './backend.js';
export type { Recognizer } from './recognizer.js';
