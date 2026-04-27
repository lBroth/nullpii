// SPDX-License-Identifier: Apache-2.0
import { createInterface } from 'node:readline';
import type { Command } from 'commander';
import { NullPii } from '../../nullpii.js';
import type { PiiSpan } from '../../types/index.js';
import { type CliConfigOptions, configFromOptions } from '../config-from-options.js';

interface ServeRequest {
  readonly text: string;
  readonly id?: string | number;
}
interface ServeResponse {
  readonly id: string | number | null;
  readonly spans: ReadonlyArray<PiiSpan>;
  readonly error?: string;
}

export function registerServe(program: Command): void {
  program
    .command('serve')
    .description('long-running JSON-lines daemon (stdin → stdout). Keeps the model in memory.')
    .option('--model-dir <path>', 'use a local model directory (skip download)')
    .option('--backend <name>', 'force backend: cpu | mps | cuda | rocm | auto')
    .option('--variant <v>', 'fp32 | fp16 | int8 | int4 | int4f16 | auto')
    .option('--enter-bias <n>', 'transition bias added on entering a span', Number.parseFloat)
    .option('--background-bias <n>', 'transition bias on O→O self-loops', Number.parseFloat)
    .option('--continue-bias <n>', 'transition bias on B/I → I/E', Number.parseFloat)
    .option('--threshold <n>', 'global score threshold; spans below are dropped', Number.parseFloat)
    .option('--threads <n>', 'ORT intraOp thread count (0 = ORT default)', Number.parseInt)
    .action(runServe);
}

async function runServe(options: CliConfigOptions): Promise<void> {
  const engine = new NullPii(configFromOptions(options));
  await engine.init();
  process.stderr.write('nullpii serve ready\n');

  const rl = createInterface({ input: process.stdin, crlfDelay: Number.POSITIVE_INFINITY });
  for await (const line of rl) {
    const trimmed = line.trim();
    if (trimmed === '') continue;
    await handle(engine, trimmed);
  }
  await engine.dispose();
}

async function handle(engine: NullPii, line: string): Promise<void> {
  let req: ServeRequest;
  try {
    req = JSON.parse(line) as ServeRequest;
  } catch (err) {
    write({ id: null, spans: [], error: asMessage(err) });
    return;
  }
  try {
    const result = await engine.sanitize(req.text);
    write({ id: req.id ?? null, spans: result.spans });
  } catch (err) {
    write({ id: req.id ?? null, spans: [], error: asMessage(err) });
  }
}

function write(resp: ServeResponse): void {
  process.stdout.write(`${JSON.stringify(resp)}\n`);
}

function asMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
