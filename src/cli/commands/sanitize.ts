// SPDX-License-Identifier: Apache-2.0
import { readFileSync } from 'node:fs';
import chalk from 'chalk';
import type { Command } from 'commander';
import { NullPii } from '../../nullpii.js';
import { type CliConfigOptions, configFromOptions } from '../config-from-options.js';

export function registerSanitize(program: Command): void {
  program
    .command('sanitize [text]')
    .description('sanitize <text> (or stdin) and print the result')
    .option('--stdin', 'read input text from stdin')
    .option('--format <fmt>', 'output format: pretty | json', 'pretty')
    .option('--session <id>', 'reuse an existing vault session id')
    .option('--model-dir <path>', 'use a local model directory (skip download)')
    .option('--backend <name>', 'force backend: cpu | mps | cuda | rocm | auto')
    .option('--variant <v>', 'fp32 | fp16 | int8 | int4 | int4f16 | auto')
    .action(
      async (
        text: string | undefined,
        options: { stdin?: boolean; format: string; session?: string } & CliConfigOptions,
      ) => {
        const input = await readInput(text, Boolean(options.stdin));
        const engine = new NullPii(configFromOptions(options));
        const result = await engine.sanitize(input, options.session);
        await engine.dispose();

        if (options.format === 'json') {
          process.stdout.write(
            `${JSON.stringify({ sessionId: result.sessionId, sanitized: result.sanitized, spans: result.spans }, null, 2)}\n`,
          );
          return;
        }
        process.stdout.write(`${chalk.dim('session:')} ${result.sessionId}\n`);
        process.stdout.write(`${result.sanitized}\n`);
      },
    );
}

async function readInput(text: string | undefined, useStdin: boolean): Promise<string> {
  if (useStdin) return readStdin();
  if (text === undefined) {
    throw new Error('sanitize: pass <text> or --stdin');
  }
  if (text.startsWith('@')) {
    return readFileSync(text.slice(1), 'utf-8');
  }
  return text;
}

async function readStdin(): Promise<string> {
  const chunks: Buffer[] = [];
  for await (const chunk of process.stdin) {
    chunks.push(Buffer.from(chunk as Uint8Array));
  }
  return Buffer.concat(chunks).toString('utf-8');
}
