import type { NullPiiConfig } from '../types/index.js';

export interface CliConfigOptions {
  readonly modelDir?: string;
  readonly backend?: string;
  readonly variant?: string;
  readonly threshold?: number;
  readonly threads?: number;
}

/** Build a `NullPiiConfig` from CLI flags, dropping undefined entries. */
export function configFromOptions(options: CliConfigOptions): NullPiiConfig {
  const out: { -readonly [K in keyof NullPiiConfig]: NullPiiConfig[K] } = {};
  if (options.modelDir !== undefined) out.modelDir = options.modelDir;
  if (options.backend !== undefined) {
    out.backend = options.backend as NonNullable<NullPiiConfig['backend']>;
  }
  if (options.variant !== undefined) {
    out.variant = options.variant as NonNullable<NullPiiConfig['variant']>;
  }
  if (options.threshold !== undefined && Number.isFinite(options.threshold)) {
    out.threshold = options.threshold;
  }
  if (options.threads !== undefined && Number.isFinite(options.threads) && options.threads >= 0) {
    out.intraOpNumThreads = options.threads;
  }
  return out;
}
