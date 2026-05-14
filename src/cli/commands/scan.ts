// SPDX-License-Identifier: Apache-2.0

import { writeSync } from 'node:fs';
import { createInterface } from 'node:readline';
import chalk from 'chalk';
import type { Command } from 'commander';
import { NullPii } from '../../nullpii.js';
import { type CliConfigOptions, configFromOptions } from '../config-from-options.js';

export function registerScan(program: Command): void {
  program
    .command('scan [text]')
    .description('detect and display PII spans in <text>')
    .option('--format <fmt>', 'output format: pretty | json', 'pretty')
    .option(
      '--ndjson',
      'read NDJSON from stdin (one {"text": "..."} per line); emit one JSON span result per line. Engine loads once and is reused — for batch detection.',
    )
    .option('--model-dir <path>', 'use a local model directory (skip download)')
    .option('--backend <name>', 'force backend: cpu | mps | cuda | auto')
    .action(
      async (
        text: string | undefined,
        options: { format: string; ndjson?: boolean } & CliConfigOptions,
      ) => {
        const engine = new NullPii(configFromOptions(options));
        try {
          if (options.ndjson) {
            await runNdjson(engine);
            return;
          }
          if (text === undefined) {
            throw new Error('scan: pass <text> or --ndjson with stdin');
          }
          const result = await engine.sanitize(text);
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
        } finally {
          await engine.dispose();
        }
      },
    );
}

async function runNdjson(engine: NullPii): Promise<void> {
  const rl = createInterface({ input: process.stdin, crlfDelay: Number.POSITIVE_INFINITY });
  // `process.stdout.write` is block-buffered when piped (~64KB), so the
  // Python bench harness blocks on readline() and the subprocess looks
  // hung even though it's still inferring. `fs.writeSync(1, ...)` calls
  // write(2) directly on the stdout fd — synchronous, unbuffered.
  const writeLine = (s: string): void => {
    writeSync(1, s);
  };
  for await (const line of rl) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    let payload: { text?: string };
    try {
      payload = JSON.parse(trimmed);
    } catch (e) {
      writeLine(`${JSON.stringify({ error: `invalid json: ${(e as Error).message}` })}\n`);
      continue;
    }
    const text = payload.text;
    if (typeof text !== 'string') {
      writeLine(`${JSON.stringify({ error: 'missing text field' })}\n`);
      continue;
    }
    const result = await engine.sanitize(text);
    writeLine(`${JSON.stringify({ spans: result.spans })}\n`);
  }
}
