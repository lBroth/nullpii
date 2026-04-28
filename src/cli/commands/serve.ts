// SPDX-License-Identifier: Apache-2.0
import { type Socket, createServer } from 'node:net';
import { createInterface } from 'node:readline';
import type { Command } from 'commander';
import { NullPii } from '../../nullpii.js';
import type { PiiSpan } from '../../types/index.js';
import { type CliConfigOptions, configFromOptions } from '../config-from-options.js';

interface ServeRequest {
  readonly text: string;
  readonly id?: string | number;
  readonly sessionId?: string;
}
interface ServeResponse {
  readonly id: string | number | null;
  readonly sanitized?: string;
  readonly sessionId?: string;
  readonly spans: ReadonlyArray<PiiSpan>;
  readonly error?: string;
}

export function registerServe(program: Command): void {
  program
    .command('serve')
    .description(
      'long-running JSON-lines daemon. Default = stdin/stdout. Use --socket to listen on a Unix socket.',
    )
    .option('--model-dir <path>', 'use a local model directory (skip download)')
    .option('--backend <name>', 'force backend: cpu | mps | cuda | rocm | auto')
    .option('--variant <v>', 'fp32 | fp16 | int8 | int4 | int4f16 | auto')
    .option('--enter-bias <n>', 'transition bias added on entering a span', Number.parseFloat)
    .option('--background-bias <n>', 'transition bias on O→O self-loops', Number.parseFloat)
    .option('--continue-bias <n>', 'transition bias on B/I → I/E', Number.parseFloat)
    .option('--threshold <n>', 'global score threshold; spans below are dropped', Number.parseFloat)
    .option('--threads <n>', 'ORT intraOp thread count (0 = ORT default)', Number.parseInt)
    .option(
      '--socket <path>',
      'listen on a Unix socket; one JSON request per line, response per line',
    )
    .action(runServe);
}

async function runServe(options: CliConfigOptions & { socket?: string }): Promise<void> {
  const engine = new NullPii(configFromOptions(options));
  await engine.init();
  process.stderr.write('nullpii serve ready\n');

  if (typeof options.socket === 'string' && options.socket !== '') {
    await runSocket(engine, options.socket);
    return;
  }
  await runStdio(engine);
}

async function runStdio(engine: NullPii): Promise<void> {
  const rl = createInterface({ input: process.stdin, crlfDelay: Number.POSITIVE_INFINITY });
  for await (const line of rl) {
    const trimmed = line.trim();
    if (trimmed === '') continue;
    const resp = await handle(engine, trimmed);
    process.stdout.write(`${JSON.stringify(resp)}\n`);
  }
  await engine.dispose();
}

function runSocket(engine: NullPii, socketPath: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const server = createServer((sock: Socket) => {
      let buffer = '';
      sock.setEncoding('utf8');
      sock.on('data', (chunk) => {
        buffer += chunk;
        for (;;) {
          const nl = buffer.indexOf('\n');
          if (nl < 0) break;
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (line === '') continue;
          handle(engine, line)
            .then((resp) => sock.write(`${JSON.stringify(resp)}\n`))
            .catch((err) =>
              sock.write(`${JSON.stringify({ id: null, spans: [], error: asMessage(err) })}\n`),
            );
        }
      });
      sock.on('error', () => {
        // client disconnected mid-write — fine
      });
    });
    server.on('error', reject);
    server.listen(socketPath, () => {
      process.stderr.write(`nullpii serve listening on ${socketPath}\n`);
    });
    const shutdown = (): void => {
      server.close(() => {
        engine.dispose().finally(() => resolve());
      });
    };
    process.on('SIGTERM', shutdown);
    process.on('SIGINT', shutdown);
  });
}

async function handle(engine: NullPii, line: string): Promise<ServeResponse> {
  let req: ServeRequest;
  try {
    req = JSON.parse(line) as ServeRequest;
  } catch (err) {
    return { id: null, spans: [], error: asMessage(err) };
  }
  try {
    const result = await engine.sanitize(req.text, req.sessionId);
    return {
      id: req.id ?? null,
      sanitized: result.sanitized,
      sessionId: result.sessionId,
      spans: result.spans,
    };
  } catch (err) {
    return { id: req.id ?? null, spans: [], error: asMessage(err) };
  }
}

function asMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
