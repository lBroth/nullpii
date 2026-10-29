#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Starts a real nullpii gateway with its sidecar on, runs the mod's
// end-to-end suite against it (tests/e2e-run.mjs, with
// NULLPII_E2E_SIDECAR_URL and NULLPII_E2E_SIDECAR_TOKEN set), always stops
// the gateway, and exits with the suite's status.
//
//   NULLPII_MODEL_DIR=<the model's folder> node packages/claude-code-mod/tests/e2e-sidecar.mjs
//
// Needs this checkout's gateway built (`npm run build` in
// packages/gateway), `nullpii` resolving to this checkout's core
// (node_modules/nullpii linked to the repository root, which is built),
// and the `claude` CLI on PATH.
//
// The gateway is this checkout's (packages/gateway/bin), on a free port of
// 127.0.0.1, with a fresh token (32 random bytes, in hex) that is never
// printed, and an empty policy file of its own (the defaults), so a policy
// in ~/.config/nullpii is neither read nor written. Its log is kept in
// memory and printed only when it does not come up.

import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { createServer } from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { setTimeout as sleep } from 'node:timers/promises';
import { fileURLToPath } from 'node:url';
import { onExitSignals, stopChild } from './e2e-process.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HERE, '..', '..', '..');
const GATEWAY_BIN = join(REPO_ROOT, 'packages', 'gateway', 'bin', 'nullpii-gateway.mjs');
const RUN_SCRIPT = join(HERE, 'e2e-run.mjs');
const HOST = '127.0.0.1';
const TOKEN_BYTES = 32;
const STATUS_PATH = '/v1/sidecar/status';
/** How long the gateway may take to get its model ready, and how often
 * its status is read meanwhile. */
const READY_TIMEOUT_MS = 300_000;
const READY_POLL_MS = 500;
const STATUS_TIMEOUT_MS = 5_000;
/** How long the gateway gets to stop before it is killed. */
const STOP_TIMEOUT_MS = 10_000;
/** The lines of the gateway's log kept for a failure report. */
const LOG_LINES_KEPT = 200;
const EXIT_FAILED = 1;
const EXIT_USAGE = 2;
const PRIVATE_FILE_MODE = 0o600;

function say(line) {
  process.stderr.write(`e2e-sidecar: ${line}\n`);
}

/** A port of 127.0.0.1 no one listens on, as the system hands it out. */
function freePort() {
  return new Promise((resolve, reject) => {
    const server = createServer();
    server.on('error', reject);
    server.listen(0, HOST, () => {
      const { port } = server.address();
      server.close(() => resolve(port));
    });
  });
}

/** The last lines of a child's output, kept for a failure report. */
function keepLog(stream, lines) {
  stream.setEncoding('utf8').on('data', (piece) => {
    lines.push(...piece.split('\n').filter((line) => line !== ''));
    lines.splice(0, Math.max(0, lines.length - LOG_LINES_KEPT));
  });
}

/** Start the gateway in the background, its log kept in memory. */
function startGateway(env) {
  const child = spawn(process.execPath, [GATEWAY_BIN], {
    cwd: REPO_ROOT,
    env: { ...process.env, ...env },
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  const log = [];
  keepLog(child.stdout, log);
  keepLog(child.stderr, log);
  const exited = new Promise((resolve) =>
    child.once('exit', (code, signal) => resolve(code ?? signal)),
  );
  return { child, log, exited };
}

/** Whether a failed status read means only that the gateway is not up
 * yet: nothing listens (fetch's TypeError), or it did not answer in time. */
function notUpYet(err) {
  return err instanceof TypeError || (err instanceof Error && err.name === 'TimeoutError');
}

/** The gateway's sidecar status, or undefined while it is not up yet. */
async function readStatus(url, token) {
  let res;
  try {
    res = await fetch(url + STATUS_PATH, {
      headers: { authorization: `Bearer ${token}` },
      signal: AbortSignal.timeout(STATUS_TIMEOUT_MS),
    });
  } catch (err) {
    if (notUpYet(err)) return undefined;
    throw err;
  }
  if (!res.ok) throw new Error(`the sidecar status answered ${res.status}`);
  return res.json();
}

/** Wait until the gateway's model is ready: its status reports the
 * `startup` phase `ready` (a gateway without the field is ready once it
 * answers). Fails when the warmup fails, the gateway exits, or time runs out. */
async function waitReady(gateway, url, token) {
  let gone = false;
  gateway.exited.then(() => {
    gone = true;
  });
  const deadline = Date.now() + READY_TIMEOUT_MS;
  while (Date.now() < deadline) {
    if (gone) throw new Error('the gateway exited before its model was ready');
    const status = await readStatus(url, token);
    const phase = status?.startup?.phase;
    if (status !== undefined && (status.startup === undefined || phase === 'ready')) return;
    if (phase === 'failed')
      throw new Error(`the gateway's warmup failed (${status.startup.while})`);
    await sleep(READY_POLL_MS);
  }
  throw new Error(`the gateway's model was not ready within ${READY_TIMEOUT_MS / 1000} s`);
}

/** Run the suite against the sidecar, its process kept in `suites` while
 * it runs; resolves with its exit status. */
function runSuite(url, token, suites) {
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [RUN_SCRIPT], {
      env: { ...process.env, NULLPII_E2E_SIDECAR_URL: url, NULLPII_E2E_SIDECAR_TOKEN: token },
      stdio: 'inherit',
    });
    suites.add(child);
    child.on('error', reject);
    child.on('close', (code) => {
      suites.delete(child);
      resolve(code ?? EXIT_FAILED);
    });
  });
}

/** Stop the gateway, and kill it if it does not stop in time; nothing
 * when it was not started. */
async function stopGateway(gateway) {
  if (gateway === undefined) return;
  if (await stopChild(gateway.child, gateway.exited, STOP_TIMEOUT_MS)) {
    say(`the gateway did not stop within ${STOP_TIMEOUT_MS / 1000} s: killed it`);
  }
}

/** Remove the gateway's scratch folder; nothing when it was not made. */
function removeScratch(scratch) {
  if (scratch !== undefined) rmSync(scratch, { recursive: true, force: true });
}

/** On Ctrl-C, a kill or a hang-up: kill the gateway, pass the signal on
 * to the suite (which then removes its own scratch copy), remove the
 * gateway's scratch folder, and exit as the signal would. `run` holds
 * what was made so far (`scratch`, `gateway`, `suites`), so the handler is
 * in place before anything is made. A second signal finds it again. */
function stopOnSignal(run) {
  onExitSignals((signal, exitCode) => {
    run.gateway?.child.kill('SIGKILL');
    for (const suite of run.suites) suite.kill(signal);
    removeScratch(run.scratch);
    process.exit(exitCode);
  });
}

async function main() {
  const modelDir = process.env.NULLPII_MODEL_DIR;
  if (modelDir === undefined || modelDir === '') {
    say('set NULLPII_MODEL_DIR to the folder of the model (the core e2e suite uses the same one)');
    return EXIT_USAGE;
  }
  const run = { scratch: undefined, gateway: undefined, suites: new Set() };
  stopOnSignal(run);
  try {
    run.scratch = mkdtempSync(join(tmpdir(), 'nullpii-e2e-gateway-'));
    const policyFile = join(run.scratch, 'config.json');
    writeFileSync(policyFile, '{}\n', { mode: PRIVATE_FILE_MODE });
    const token = randomBytes(TOKEN_BYTES).toString('hex');
    const port = await freePort();
    const url = `http://${HOST}:${port}`;
    run.gateway = startGateway({
      NULLPII_SIDECAR_TOKEN: token,
      NULLPII_HOST: HOST,
      NULLPII_PORT: String(port),
      NULLPII_MODEL_DIR: modelDir,
      NULLPII_CONFIG: policyFile,
    });
    const { gateway } = run;
    const started = Date.now();
    await waitReady(gateway, url, token).catch((err) => {
      process.stderr.write(`${gateway.log.join('\n')}\n`);
      throw err;
    });
    say(`gateway ready on ${url} after ${((Date.now() - started) / 1000).toFixed(1)} s`);
    return await runSuite(url, token, run.suites);
  } finally {
    await stopGateway(run.gateway);
    removeScratch(run.scratch);
  }
}

main().then(
  (code) => {
    process.exitCode = code;
  },
  (err) => {
    say(`failed: ${err instanceof Error ? err.message : String(err)}`);
    process.exitCode = EXIT_FAILED;
  },
);
