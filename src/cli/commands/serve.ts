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
    .option(
      '--idle-timeout-ms <n>',
      'auto-terminate after this many ms with no requests (socket mode only)',
      Number.parseInt,
    )
    .option(
      '--parent-pid <n>',
      'auto-terminate when the given pid no longer exists (socket mode only)',
      Number.parseInt,
    )
    .action(runServe);
}

interface ServeOptions extends CliConfigOptions {
  socket?: string;
  idleTimeoutMs?: number;
  parentPid?: number;
}

async function runServe(options: ServeOptions): Promise<void> {
  const engine = new NullPii(configFromOptions(options));
  await engine.init();
  process.stderr.write('nullpii serve ready\n');

  if (typeof options.socket === 'string' && options.socket !== '') {
    await runSocket(engine, options.socket, {
      idleTimeoutMs: options.idleTimeoutMs,
      parentPid: options.parentPid,
    });
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

interface SocketOptions {
  readonly idleTimeoutMs: number | undefined;
  readonly parentPid: number | undefined;
}

function runSocket(engine: NullPii, socketPath: string, opts: SocketOptions): Promise<void> {
  return new Promise((resolve, reject) => {
    let lastActivity = Date.now();
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
          lastActivity = Date.now();
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
    const shutdown = (reason: string): void => {
      process.stderr.write(`nullpii serve shutting down: ${reason}\n`);
      server.close(() => {
        engine.dispose().finally(() => resolve());
      });
    };
    process.on('SIGTERM', () => shutdown('SIGTERM'));
    process.on('SIGINT', () => shutdown('SIGINT'));

    // Best-effort cleanup if Claude Code (parent) crashes without
    // invoking the Stop hook. Two independent watchdogs:
    //   1. idle timeout — kill self after N ms of no requests
    //   2. parent-pid liveness — poll if the registered pid is gone
    const idleMs = opts.idleTimeoutMs ?? 30 * 60_000;
    if (idleMs > 0) {
      setInterval(() => {
        if (Date.now() - lastActivity > idleMs) {
          shutdown(`idle for ${Math.round((Date.now() - lastActivity) / 1000)}s`);
        }
      }, 60_000).unref();
    }
    if (typeof opts.parentPid === 'number' && opts.parentPid > 0) {
      const pid = opts.parentPid;
      setInterval(() => {
        try {
          process.kill(pid, 0); // signal 0 = liveness check, no actual signal
        } catch {
          shutdown(`parent pid ${pid} no longer exists`);
        }
      }, 5_000).unref();
    }
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
