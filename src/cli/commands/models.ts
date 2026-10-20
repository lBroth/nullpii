// SPDX-License-Identifier: Apache-2.0

import { existsSync } from 'node:fs';
import { opendir, stat } from 'node:fs/promises';
import { join } from 'node:path';
import chalk from 'chalk';
import type { Command } from 'commander';
import { defaultCacheDir } from '../../model-manager.js';

export function registerModels(program: Command): void {
  const models = program.command('models').description('manage cached model artifacts');
  models.command('list').description('list cached model files with sizes').action(listModels);
}

async function listModels(): Promise<void> {
  const dir = defaultCacheDir();
  if (!existsSync(dir)) {
    process.stdout.write(chalk.dim('no models cached\n'));
    return;
  }
  for await (const f of walk(dir)) {
    const st = await stat(f);
    const size = (st.size / 1024 / 1024).toFixed(1);
    process.stdout.write(`${chalk.cyan(`${size.padStart(8)} MB`)}  ${f.slice(dir.length + 1)}\n`);
  }
}

async function* walk(dir: string): AsyncIterableIterator<string> {
  const handle = await opendir(dir);
  for await (const entry of handle) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      yield* walk(full);
    } else {
      yield full;
    }
  }
}
