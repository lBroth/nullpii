// SPDX-License-Identifier: Apache-2.0
import chalk from 'chalk';
import type { Command } from 'commander';
import { NullPii } from '../../nullpii.js';
import { type CliConfigOptions, configFromOptions } from '../config-from-options.js';

export function registerScan(program: Command): void {
  program
    .command('scan <text>')
    .description('detect and display PII spans in <text>')
    .option('--format <fmt>', 'output format: pretty | json', 'pretty')
    .option('--model-dir <path>', 'use a local model directory (skip download)')
    .option('--backend <name>', 'force backend: cpu | mps | cuda | rocm | auto')
    .option('--variant <v>', 'fp32 | int4 | auto')
    .action(async (text: string, options: { format: string } & CliConfigOptions) => {
      const engine = new NullPii(configFromOptions(options));
      const result = await engine.sanitize(text);
      await engine.dispose();

      if (options.format === 'json') {
        process.stdout.write(`${JSON.stringify({ spans: result.spans }, null, 2)}\n`);
        return;
      }
      if (result.spans.length === 0) {
        process.stdout.write(chalk.green('no PII detected\n'));
        return;
      }
      for (const s of result.spans) {
        process.stdout.write(
          `${chalk.cyan(`[${s.start}-${s.end}]`)} ${chalk.yellow(s.label)} ` +
            `${chalk.dim(`(score=${s.score.toFixed(3)})`)} ${chalk.bold(s.text)}\n`,
        );
      }
    });
}
