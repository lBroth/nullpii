// SPDX-License-Identifier: Apache-2.0

import type { Command } from 'commander';
import { configFilePath, loadConfigFile } from '../../config-file.js';
import { DEFAULT_RESTORE_TOOLS } from '../../defaults.js';

const JSON_INDENT = 2;

interface ConfigOptions {
  readonly config?: string;
}

export function registerConfig(program: Command): void {
  program
    .command('config')
    .description(
      'validate the masking-policy config file and print it, with the restore-tool list in effect',
    )
    .option(
      '--config <file>',
      'config file to check (default: $NULLPII_CONFIG, else ~/.config/nullpii/config.json if present)',
    )
    .action(showConfig);
}

/** Print `{ file, policy, restoreTools }` as JSON. An invalid file throws
 * `InvalidConfigError`, which the CLI reports with exit status 1. */
function showConfig(options: ConfigOptions): void {
  const file = configFilePath(options.config);
  const policy = file === null ? {} : loadConfigFile(file);
  const restoreTools = policy.restoreTools ?? DEFAULT_RESTORE_TOOLS;
  process.stdout.write(`${JSON.stringify({ file, policy, restoreTools }, null, JSON_INDENT)}\n`);
}
