// SPDX-License-Identifier: Apache-2.0

import chalk from 'chalk';
import cliProgress from 'cli-progress';
import type { Command } from 'commander';
import { ModelManager } from '../../model-manager.js';

export function registerPrefetch(program: Command): void {
  program
    .command('prefetch')
    .description(
      'download the model into the local cache (run once at install / CI / Docker build)',
    )
    .action(runPrefetch);
}

async function runPrefetch(): Promise<void> {
  const bar = new cliProgress.SingleBar(
    { format: 'prefetch |{bar}| {percentage}%' },
    cliProgress.Presets.shades_grey,
  );
  bar.start(100, 0);
  try {
    const manager = new ModelManager();
    const result = await manager.ensure({
      onProgress: (p) => bar.update(Math.round(p * 100)),
    });
    bar.update(100);
    bar.stop();
    process.stdout.write(`${chalk.green('cached at:')} ${result.modelDir}\n`);
  } catch (err) {
    bar.stop();
    throw err;
  }
}
