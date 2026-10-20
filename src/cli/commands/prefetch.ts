// SPDX-License-Identifier: Apache-2.0

import chalk from 'chalk';
import cliProgress from 'cli-progress';
import { type Command, Option } from 'commander';
import { ModelManager } from '../../model-manager.js';
import type { BackendName, ModelVariant } from '../../types/index.js';

const BACKENDS: readonly BackendName[] = ['cpu', 'mps', 'cuda', 'auto'];
const VARIANTS: readonly ModelVariant[] = ['fp32', 'fp16', 'auto'];

interface PrefetchOptions {
  readonly backend: BackendName;
  readonly variant: ModelVariant;
}

export function registerPrefetch(program: Command): void {
  program
    .command('prefetch')
    .description(
      'download the model into the local cache (run once at install / CI / Docker build)',
    )
    .addOption(
      new Option('--backend <name>', 'backend the model will run on')
        .choices(BACKENDS)
        .default('auto'),
    )
    .addOption(
      new Option('--variant <variant>', 'ONNX precision; auto fetches fp16 for --backend cuda')
        .choices(VARIANTS)
        .default('auto'),
    )
    .action(runPrefetch);
}

async function runPrefetch(options: PrefetchOptions): Promise<void> {
  const { backend, variant } = options;
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
