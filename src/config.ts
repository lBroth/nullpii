// SPDX-License-Identifier: Apache-2.0

//
// Runtime configuration: every environment-variable read in nullpii.
// Adding a new env var? Put its name here and read it via `readEnvVar`.
// Don't read `process.env` from anywhere else.
//
// (Static defaults live in `defaults.ts`; this file is for runtime env reads.)
//

/** XDG_CACHE_HOME — consumers fall back to ~/.cache themselves when unset. */
export const XDG_CACHE_HOME = 'XDG_CACHE_HOME';

/** NULLPII_MODEL_DIR — optional pre-staged model directory. When set,
 * `NullPii` skips the HuggingFace download and loads artifacts from this
 * path. Equivalent to passing `modelDir` in `NullPiiConfig`; explicit
 * `config.modelDir` takes priority over the env var. */
export const NULLPII_MODEL_DIR = 'NULLPII_MODEL_DIR';

/** Read an env var, returning `undefined` for both unset AND empty-string. */
export function readEnvVar(name: string): string | undefined {
  const v = process.env[name];
  return v !== undefined && v !== '' ? v : undefined;
}
