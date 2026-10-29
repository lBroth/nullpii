// SPDX-License-Identifier: Apache-2.0
//
// The process handling of the Claude Code mod's e2e scripts
// (packages/claude-code-mod/tests/e2e-run.mjs, e2e-sidecar.mjs, and
// e2e-process.mjs, which they share): they end at once when they can, and
// clean up on every signal that ends a run early. And e2e-run.mjs's check
// of the challenges the bridge answered itself: the run fails unless the
// sidecar answers each of them the same. Each script runs here as its own
// process, with no real sidecar and no `claude` CLI but stand-ins.

import { type ChildProcess, spawn } from 'node:child_process';
import {
  chmodSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  writeFileSync,
} from 'node:fs';
import { type Server, createServer } from 'node:http';
import type { AddressInfo } from 'node:net';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { afterEach, describe, expect, it } from 'vitest';

const MOD_TESTS = fileURLToPath(new URL('../packages/claude-code-mod/tests/', import.meta.url));
const RUN_SCRIPT = join(MOD_TESTS, 'e2e-run.mjs');
const SIDECAR_SCRIPT = join(MOD_TESTS, 'e2e-sidecar.mjs');
const PROCESS_MODULE = pathToFileURL(join(MOD_TESTS, 'e2e-process.mjs')).href;
const TOKEN = 'a'.repeat(64);
/** No one answers here: the scripts tested never reach the sidecar. */
const SIDECAR_URL = 'http://127.0.0.1:9';
const SCRATCH_PREFIX = 'nullpii-mod-e2e-';
const GATEWAY_SCRATCH_PREFIX = 'nullpii-e2e-gateway-';
const LINES_FILE_VARIABLE = 'FAKE_CLAUDE_LINES_FILE';
const CHALLENGE_PATH = '/v1/sidecar/challenge';
const ANSWER_TYPE = 'application/json; charset=utf-8';
/** The proof the stand-in sidecar answers every challenge with. */
const SIDECAR_PROOF = 'b'.repeat(64);
const PID_FILE_VARIABLE = 'FAKE_CLAUDE_PID_FILE';
const EXIT_FAILED = 1;
const SIGHUP_EXIT = 129;
const SIGTERM_EXIT = 143;
/** The scripts' own timeouts: 300 s for a suite, 10 s for a gateway to stop. */
const SUITE_TIMEOUT_MS = 300_000;
const STOP_TIMEOUT_MS = 10_000;
/** The suite timeout e2e-run.mjs gets in the test of it. */
const SHORT_SUITE_TIMEOUT_MS = 1_000;
/** Well under those: a script that waits on one of them fails the test. */
const PROMPT_EXIT_MS = 5_000;
const POLL_MS = 50;
const TEST_TIMEOUT_MS = 20_000;

interface Ended {
  readonly code: number | null;
  readonly signal: NodeJS.Signals | null;
  readonly stdout: string;
  readonly stderr: string;
  readonly ms: number;
}

const folders: string[] = [];
const servers: Server[] = [];
/** The processes a test started, killed after it when they still run. */
const pids: number[] = [];

function folder(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  folders.push(dir);
  return dir;
}

afterEach(async () => {
  for (const pid of pids.splice(0)) if (alive(pid)) process.kill(pid, 'SIGKILL');
  for (const server of servers.splice(0)) {
    await new Promise((resolve) => server.close(resolve));
  }
  for (const dir of folders.splice(0)) rmSync(dir, { recursive: true, force: true });
});

/** Start `node args`, and resolve once it ends, with how long it ran. */
function run(
  args: string[],
  env: NodeJS.ProcessEnv,
): { child: ChildProcess; ended: Promise<Ended> } {
  const started = Date.now();
  const child = spawn(process.execPath, args, { env, stdio: ['ignore', 'pipe', 'pipe'] });
  if (child.pid !== undefined) pids.push(child.pid);
  const out = { stdout: '', stderr: '' };
  child.stdout?.setEncoding('utf8').on('data', (piece: string) => {
    out.stdout += piece;
  });
  child.stderr?.setEncoding('utf8').on('data', (piece: string) => {
    out.stderr += piece;
  });
  const ended = new Promise<Ended>((resolve, reject) => {
    child.once('error', reject);
    child.once('close', (code, signal) =>
      resolve({ ...out, code, signal, ms: Date.now() - started }),
    );
  });
  return { child, ended };
}

/** e2e-run.mjs's environment: the sidecar's variables, `PATH`, and a
 * temporary folder of the test's own, where its scratch copy goes. */
function runnerEnv(path: string, temp: string, extra: NodeJS.ProcessEnv = {}): NodeJS.ProcessEnv {
  return {
    PATH: path,
    TMPDIR: temp,
    NULLPII_E2E_SIDECAR_URL: SIDECAR_URL,
    NULLPII_E2E_SIDECAR_TOKEN: TOKEN,
    ...extra,
  };
}

/** A `claude` that, as the real one's launcher does, runs the work in a
 * process of its own that shares its stdout and stderr, writes that
 * process's id to `$FAKE_CLAUDE_PID_FILE`, and waits on it: killing the
 * launcher alone leaves that process running, holding the pipes. */
function fakeClaude(): string {
  const bin = folder('nullpii-fake-claude-');
  const file = join(bin, 'claude');
  writeFileSync(file, `#!/bin/sh\nsleep 60 &\necho $! > "$${PID_FILE_VARIABLE}"\nwait\n`);
  chmodSync(file, 0o755);
  return bin;
}

/** A module, for `node --import`, that makes e2e-run.mjs's suite timeout
 * (SUITE_TIMEOUT_MS) SHORT_SUITE_TIMEOUT_MS: every other timer is left as
 * it is. */
function shortSuiteTimeout(): string {
  const file = join(folder('nullpii-preload-'), 'short-suite-timeout.mjs');
  const source = [
    'const real = globalThis.setTimeout;',
    'globalThis.setTimeout = (callback, ms, ...args) =>',
    `  real(callback, ms === ${SUITE_TIMEOUT_MS} ? ${SHORT_SUITE_TIMEOUT_MS} : ms, ...args);`,
  ].join('\n');
  writeFileSync(file, source);
  return pathToFileURL(file).href;
}

function readPid(file: string): number {
  return Number(readFileSync(file, 'utf8').trim());
}

/** A `claude` that prints the lines in `$FAKE_CLAUDE_LINES_FILE` on
 * stderr, as the suite prints its lines for the runner, and exits 0. */
function printingClaude(): string {
  const bin = folder('nullpii-fake-claude-');
  const file = join(bin, 'claude');
  writeFileSync(file, `#!/bin/sh\ncat "$${LINES_FILE_VARIABLE}" >&2\n`);
  chmodSync(file, 0o755);
  return bin;
}

/** A sidecar stand-in on 127.0.0.1 that answers every challenge with
 * SIDECAR_PROOF; resolves with its origin. */
async function proofSidecar(): Promise<string> {
  const server = createServer((req, res) => {
    req.resume();
    req.on('end', () => {
      const ok = req.method === 'POST' && req.url === CHALLENGE_PATH;
      res.writeHead(ok ? 200 : 404, { 'content-type': ANSWER_TYPE });
      res.end(ok ? JSON.stringify({ proof: SIDECAR_PROOF }) : '{}');
    });
  });
  servers.push(server);
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  return `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
}

/** The suite's lines of a verdict round with one scenario, which passed,
 * and in which the bridge answered one challenge itself, with `proof`
 * (none when `proof` is undefined). */
function verdictLines(proof: string | undefined): string {
  const signed = {
    scenario: 'one',
    request: {
      method: 'POST',
      path: CHALLENGE_PATH,
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ nonce: 'c'.repeat(64) }),
    },
    response: {
      status: 200,
      headers: { 'content-type': ANSWER_TYPE },
      text: JSON.stringify({ proof }),
    },
  };
  return [
    'nullpii-e2e plan ["one"]',
    ...(proof === undefined ? [] : [`nullpii-e2e signed ${JSON.stringify(signed)}`]),
    'nullpii-e2e done "one"',
    '',
  ].join('\n');
}

/** Run e2e-run.mjs against a stand-in sidecar, with a `claude` that
 * prints a verdict round in which the bridge answered with `proof`. */
async function runVerdict(proof: string | undefined): Promise<Ended> {
  const linesFile = join(folder('nullpii-fake-claude-lines-'), 'lines');
  writeFileSync(linesFile, verdictLines(proof));
  const env = runnerEnv(`${printingClaude()}:/bin:/usr/bin`, folder('nullpii-e2e-temp-'), {
    NULLPII_E2E_SIDECAR_URL: await proofSidecar(),
    [LINES_FILE_VARIABLE]: linesFile,
  });
  return run([RUN_SCRIPT], env).ended;
}

/** A module, for `node --import`, that sends this process SIGTERM right
 * after its first `mkdtempSync`, before anything else runs. */
function termAfterMkdtemp(): string {
  const file = join(folder('nullpii-preload-'), 'term-after-mkdtemp.mjs');
  const source = [
    "import { createRequire, syncBuiltinESMExports } from 'node:module';",
    "const fs = createRequire(import.meta.url)('node:fs');",
    'const made = fs.mkdtempSync;',
    'fs.mkdtempSync = (...args) => {',
    '  fs.mkdtempSync = made;',
    '  syncBuiltinESMExports();',
    '  const dir = made(...args);',
    "  process.kill(process.pid, 'SIGTERM');",
    '  return dir;',
    '};',
    'syncBuiltinESMExports();',
  ].join('\n');
  writeFileSync(file, source);
  return pathToFileURL(file).href;
}

async function waitFor(what: string, ready: () => boolean): Promise<void> {
  const deadline = Date.now() + PROMPT_EXIT_MS;
  while (!ready()) {
    if (Date.now() > deadline) throw new Error(`${what}: not within ${PROMPT_EXIT_MS} ms`);
    await sleep(POLL_MS);
  }
}

function alive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ESRCH') return false;
    throw err;
  }
}

function scratchCopies(temp: string): string[] {
  return readdirSync(temp).filter((name) => name.startsWith(SCRATCH_PREFIX));
}

describe.skipIf(process.platform === 'win32')('the mod e2e scripts', () => {
  it(
    'e2e-run.mjs fails at once, and says why, when `claude` is not on PATH',
    async () => {
      const temp = folder('nullpii-e2e-temp-');
      const emptyPath = folder('nullpii-empty-path-');
      const { ended } = run([RUN_SCRIPT], runnerEnv(emptyPath, temp));
      const end = await ended;
      expect(end.stderr).toContain('the `claude` CLI is not on PATH');
      expect(end.code).toBe(EXIT_FAILED);
      expect(end.ms).toBeLessThan(PROMPT_EXIT_MS);
      expect(scratchCopies(temp)).toEqual([]);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'e2e-run.mjs on a hang-up kills every process the suite started, removes its scratch copy (and the token in it), and exits 129',
    async () => {
      const temp = folder('nullpii-e2e-temp-');
      const pidFile = join(folder('nullpii-fake-claude-pid-'), 'pid');
      const path = `${fakeClaude()}:/bin:/usr/bin`;
      const { child, ended } = run(
        [RUN_SCRIPT],
        runnerEnv(path, temp, { [PID_FILE_VARIABLE]: pidFile }),
      );
      await waitFor(
        'the suite started',
        () => existsSync(pidFile) && readFileSync(pidFile, 'utf8').trim() !== '',
      );
      const suitePid = readPid(pidFile);
      pids.push(suitePid);
      const [copy] = scratchCopies(temp);
      if (copy === undefined) throw new Error('no scratch copy of the mod');
      const exchange = readFileSync(join(temp, copy, 'tests', 'e2e-exchange.ts'), 'utf8');
      expect(exchange).toContain(TOKEN);
      child.kill('SIGHUP');
      const end = await ended;
      expect(end.signal).toBeNull();
      expect(end.code).toBe(SIGHUP_EXIT);
      expect(scratchCopies(temp)).toEqual([]);
      await waitFor('the suite stopped', () => !alive(suitePid));
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'e2e-run.mjs fails when the suite outlasts its timeout, and kills every process the suite started',
    async () => {
      const temp = folder('nullpii-e2e-temp-');
      const pidFile = join(folder('nullpii-fake-claude-pid-'), 'pid');
      const path = `${fakeClaude()}:/bin:/usr/bin`;
      const env = runnerEnv(path, temp, { [PID_FILE_VARIABLE]: pidFile });
      const end = await run(['--import', shortSuiteTimeout(), RUN_SCRIPT], env).ended;
      const suitePid = readPid(pidFile);
      pids.push(suitePid);
      expect(end.stderr).toContain(`the suite did not end within ${SUITE_TIMEOUT_MS / 1000} s`);
      expect(end.code).toBe(EXIT_FAILED);
      expect(end.ms).toBeLessThan(PROMPT_EXIT_MS);
      expect(scratchCopies(temp)).toEqual([]);
      await waitFor('the suite stopped', () => !alive(suitePid));
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'e2e-run.mjs passes when the sidecar answers each challenge the bridge answered the same',
    async () => {
      const end = await runVerdict(SIDECAR_PROOF);
      expect(end.stderr).toContain(
        '1 challenges, which the bridge answered, sent to the sidecar after it: 1 answered the same',
      );
      expect(end.code).toBe(0);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'e2e-run.mjs fails when the sidecar answers a challenge the bridge answered otherwise',
    async () => {
      const end = await runVerdict('d'.repeat(64));
      expect(end.stderr).toContain(
        'scenario one: the sidecar answers a challenge the bridge answered with another body',
      );
      expect(end.code).toBe(EXIT_FAILED);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'e2e-run.mjs fails when the bridge reported no challenge it answered',
    async () => {
      const end = await runVerdict(undefined);
      expect(end.stderr).toContain('the bridge reported no challenge it answered');
      expect(end.code).toBe(EXIT_FAILED);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'e2e-sidecar.mjs on a kill right after it made its scratch folder removes it, and exits 143',
    async () => {
      const temp = folder('nullpii-e2e-temp-');
      const env = { PATH: '/bin:/usr/bin', TMPDIR: temp, NULLPII_MODEL_DIR: '/nonexistent' };
      const end = await run(['--import', termAfterMkdtemp(), SIDECAR_SCRIPT], env).ended;
      expect(end.signal).toBeNull();
      expect(end.code).toBe(SIGTERM_EXIT);
      expect(readdirSync(temp).filter((name) => name.startsWith(GATEWAY_SCRATCH_PREFIX))).toEqual(
        [],
      );
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'stopChild lets the process exit as soon as the child has stopped',
    async () => {
      const script = [
        "import { spawn } from 'node:child_process';",
        `import { stopChild } from ${JSON.stringify(PROCESS_MODULE)};`,
        "const child = spawn(process.execPath, ['-e', 'setInterval(() => {}, 1000)'], { stdio: 'ignore' });",
        "const exited = new Promise((resolve) => child.once('exit', resolve));",
        "await new Promise((resolve) => child.once('spawn', resolve));",
        `process.stdout.write(String(await stopChild(child, exited, ${STOP_TIMEOUT_MS})));`,
      ].join('\n');
      const end = await run(['--input-type=module', '-e', script], { PATH: '' }).ended;
      expect(end.stderr).toBe('');
      expect(end.stdout).toBe('false');
      expect(end.code).toBe(0);
      expect(end.ms).toBeLessThan(PROMPT_EXIT_MS);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'stopChild kills a child that does not stop in time',
    async () => {
      const ignoresTerm = "process.on('SIGTERM', () => {}); setInterval(() => {}, 1000)";
      const script = [
        "import { spawn } from 'node:child_process';",
        `import { stopChild } from ${JSON.stringify(PROCESS_MODULE)};`,
        `const child = spawn(process.execPath, ['-e', ${JSON.stringify(ignoresTerm)}], { stdio: 'ignore' });`,
        "const exited = new Promise((resolve) => child.once('exit', (code, signal) => resolve(signal)));",
        // Let the child install its SIGTERM handler before it is sent one.
        'await new Promise((resolve) => setTimeout(resolve, 500));',
        'const killed = await stopChild(child, exited, 500);',
        'process.stdout.write(`${killed} ${await exited}`);',
      ].join('\n');
      const end = await run(['--input-type=module', '-e', script], { PATH: '' }).ended;
      expect(end.stderr).toBe('');
      expect(end.stdout).toBe('true SIGKILL');
      expect(end.code).toBe(0);
    },
    TEST_TIMEOUT_MS,
  );
});
