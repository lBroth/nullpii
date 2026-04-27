// SPDX-License-Identifier: Apache-2.0
import type { NullPiiConfig } from '../types/index.js';

export interface CliConfigOptions {
  readonly modelDir?: string;
  readonly backend?: string;
  readonly variant?: string;
}

/** Build a `NullPiiConfig` from CLI flags, dropping undefined entries. */
export function configFromOptions(options: CliConfigOptions): NullPiiConfig {
  const out: { -readonly [K in keyof NullPiiConfig]: NullPiiConfig[K] } = {};
  if (options.modelDir !== undefined) {
    out.modelDir = options.modelDir;
  }
  if (options.backend !== undefined) {
    out.backend = options.backend as NonNullable<NullPiiConfig['backend']>;
  }
  if (options.variant !== undefined) {
    out.variant = options.variant as NonNullable<NullPiiConfig['variant']>;
  }
  return out;
}
