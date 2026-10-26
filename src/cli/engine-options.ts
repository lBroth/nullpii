// SPDX-License-Identifier: Apache-2.0

import { type Command, InvalidArgumentError, Option } from 'commander';
import { resolveConfigFile, toEngineConfig } from '../config-file.js';
import type { BackendName, NullPiiConfig } from '../types/index.js';

const BACKENDS: readonly BackendName[] = ['auto', 'cpu', 'mps', 'cuda'];

/** The engine flags shared by every command that runs the model. */
export interface EngineOptions {
  readonly config?: string;
  readonly modelDir?: string;
  readonly backend?: BackendName;
  readonly threshold?: number;
  readonly threads?: number;
}

/** Register the shared engine flags on `cmd`. */
export function addEngineOptions(cmd: Command): Command {
  return cmd
    .option(
      '--config <file>',
      'masking-policy config file (default: $NULLPII_CONFIG, else ~/.config/nullpii/config.json if present)',
    )
    .option('--model-dir <path>', 'use a local model directory (skip download)')
    .addOption(new Option('--backend <name>', 'force a backend').choices(BACKENDS))
    .option('--threshold <score>', 'decode and post-filter threshold, in [0, 1]', parseUnitScore)
    .option('--threads <n>', 'ONNX Runtime intra-op threads (0 = runtime default)', parseThreads);
}

/** The engine config: the config file's policy, then the flags over it. */
export function engineConfig(options: EngineOptions): NullPiiConfig {
  const file = resolveConfigFile(options.config);
  return {
    ...(file !== null ? toEngineConfig(file) : {}),
    ...(options.modelDir !== undefined && { modelDir: options.modelDir }),
    ...(options.backend !== undefined && { backend: options.backend }),
    ...(options.threshold !== undefined && { threshold: options.threshold }),
    ...(options.threads !== undefined && { intraOpNumThreads: options.threads }),
  };
}

function parseUnitScore(value: string): number {
  const n = Number(value);
  if (value.trim() === '' || !(n >= 0 && n <= 1))
    throw new InvalidArgumentError('expected a number in [0, 1]');
  return n;
}

function parseThreads(value: string): number {
  const n = Number(value);
  if (!Number.isInteger(n) || n < 0)
    throw new InvalidArgumentError('expected a non-negative integer');
  return n;
}
