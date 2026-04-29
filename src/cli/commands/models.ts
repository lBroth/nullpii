// SPDX-License-Identifier: Apache-2.0
import { existsSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import chalk from 'chalk';
import cliProgress from 'cli-progress';
import type { Command } from 'commander';
import { ModelManager, defaultCacheDir } from '../../model-manager.js';

type Variant = 'fp32' | 'int4' | 'auto';
const VARIANT_HELP = 'fp32 | int4 | auto';

export function registerModels(program: Command): void {
  const models = program.command('models').description('manage cached model artifacts');
  models.command('list').description('list cached model files with sizes').action(listModels);
  models
    .command('download')
    .description('download model files for a given variant (default: auto)')
    .option('--variant <v>', VARIANT_HELP, 'auto')
    .action(downloadModel);
}

function listModels(): void {
  const dir = defaultCacheDir();
  if (!existsSync(dir)) {
    process.stdout.write(chalk.dim('no models cached\n'));
    return;
  }
  for (const f of walk(dir)) {
    const size = (statSync(f).size / 1024 / 1024).toFixed(1);
    process.stdout.write(`${chalk.cyan(`${size.padStart(8)} MB`)}  ${f.slice(dir.length + 1)}\n`);
  }
}

async function downloadModel(options: { variant: string }): Promise<void> {
  const bar = new cliProgress.SingleBar({
    format: 'download |{bar}| {percentage}% | {value}/{total}',
    hideCursor: true,
  });
  bar.start(100, 0);
  const result = await new ModelManager().ensure({ variant: options.variant as Variant });
  bar.update(100);
  bar.stop();
  process.stdout.write(`${chalk.green('cached at:')} ${result.modelDir}\n`);
}

function* walk(dir: string): IterableIterator<string> {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) yield* walk(full);
    else yield full;
  }
}
