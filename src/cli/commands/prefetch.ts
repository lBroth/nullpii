// SPDX-License-Identifier: Apache-2.0

import chalk from 'chalk';
import cliProgress from 'cli-progress';
import type { Command } from 'commander';
import { ModelManager } from '../../model-manager.js';
import type { BackendName, ModelVariant } from '../../types/index.js';

const BACKENDS: readonly BackendName[] = ['cpu', 'mps', 'cuda', 'auto'];
const VARIANTS: readonly ModelVariant[] = ['fp32', 'fp16', 'auto'];

interface PrefetchOptions {
  readonly backend: string;
  readonly variant: string;
}

export function registerPrefetch(program: Command): void {
  program
    .command('prefetch')
    .description(
      'download the model into the local cache (run once at install / CI / Docker build)',
    )
    .option('--backend <name>', `backend the model will run on (${BACKENDS.join(', ')})`, 'auto')
    .option(
      '--variant <variant>',
      `ONNX precision (${VARIANTS.join(', ')}); auto fetches fp16 for --backend cuda`,
      'auto',
    )
    .action(runPrefetch);
}

function oneOf<T extends string>(value: string, allowed: readonly T[], flag: string): T {
  const hit = allowed.find((a) => a === value);
  if (hit === undefined) throw new Error(`${flag} must be one of ${allowed.join(', ')}`);
  return hit;
}

async function runPrefetch(options: PrefetchOptions): Promise<void> {
  const backend = oneOf(options.backend, BACKENDS, '--backend');
  const variant = oneOf(options.variant, VARIANTS, '--variant');
  const bar = new cliProgress.SingleBar(
    { format: 'prefetch |{bar}| {percentage}%' },
    cliProgress.Presets.shades_grey,
  );
  bar.start(100, 0);
  try {
    const manager = new ModelManager();
    const result = await manager.ensure({
      backend,
      variant,
      onProgress: (p) => bar.update(Math.round(p * 100)),
    });
    bar.update(100);
    bar.stop();
    process.stdout.write(`${chalk.green('cached at:')} ${result.modelDir} (${result.onnxFile})\n`);
  } catch (err) {
    bar.stop();
    throw err;
  }
}
