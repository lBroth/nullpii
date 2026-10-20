// SPDX-License-Identifier: Apache-2.0

import type { Command } from 'commander';
import { NullPii } from '../../nullpii.js';
import type { SanitizeResult } from '../../types/index.js';
import { type EngineOptions, addEngineOptions, engineConfig } from '../engine-options.js';

export function registerSanitize(program: Command): void {
  const cmd = program
    .command('sanitize [text]')
    .description('sanitize <text> (or stdin) and print the result')
    .option('--stdin', 'read input text from stdin')
    .option('--format <fmt>', 'output format: pretty | json', 'pretty');
  addEngineOptions(cmd).action(
    async (
      text: string | undefined,
      options: { stdin?: boolean; format: string } & EngineOptions,
    ) => {
      const input = await readInput(text, Boolean(options.stdin));
      const engine = new NullPii(engineConfig(options));
      let result: SanitizeResult;
      try {
        result = await engine.sanitize(input);
      } finally {
        await engine.dispose();
      }

      // The vault lives in this process only, so no session id is printed:
      // nothing outside it could restore the placeholders.
      if (options.format === 'json') {
        process.stdout.write(
          `${JSON.stringify({ sanitized: result.sanitized, spans: result.spans }, null, 2)}\n`,
        );
        return;
      }
      process.stdout.write(`${result.sanitized}\n`);
    },
  );
}

async function readInput(text: string | undefined, useStdin: boolean): Promise<string> {
  if (useStdin) return readStdin();
  if (text === undefined) {
    throw new Error('sanitize: pass <text> or --stdin');
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
