#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Runs the mod's end-to-end suite (tests/e2e.test.ts) against a real
// nullpii sidecar, already running at NULLPII_E2E_SIDECAR_URL with the
// token NULLPII_E2E_SIDECAR_TOKEN. tests/e2e-sidecar.mjs starts a fresh
// gateway and runs this for you; run it yourself against one you started:
//
//   NULLPII_E2E_SIDECAR_URL=http://127.0.0.1:<port> \
//   NULLPII_E2E_SIDECAR_TOKEN=<its token> \
//     node packages/claude-code-mod/tests/e2e-run.mjs
//
// Use a gateway with the default policy (an empty policy file): the
// scenarios expect names and emails masked and the default restore tools.
//
// `claude plugin test` runs a test in the sandbox a mod's hooks run in:
// no network, file system or environment. So the suite cannot fetch; it
// answers the mod's requests from the sidecar's answers that this script
// records (tests/e2e-bridge.ts). Each round, this script runs the suite on
// a scratch copy of the mod that holds those answers, reads the requests
// the scenarios are waiting on (the `nullpii-e2e wait` lines it prints),
// sends each to the sidecar, records the answer, and runs the suite again.
// The first challenge the mod sends (a `nullpii-e2e challenge` line) is
// sent and recorded the same way; the bridge answers every later one,
// which must be that request but for its nonce, with a proof it signs
// itself (its nonce is new each time, so no recorded answer fits). The
// round in which nothing waits is the verdict, and its report is printed:
// a scenario that waits passes in the rounds before (it has no answer to
// test yet), one that fails keeps failing, and the others go on to their
// end. Then each challenge the bridge answered in the verdict round (its
// `nullpii-e2e signed` lines) is sent to the sidecar exactly as the mod
// wrote it, and the run fails unless the sidecar answers it as the bridge
// did (status, content type, body).
//
// The scratch copy (a private temporary folder, removed at the end, and on
// Ctrl-C, a kill or a hang-up) holds the mod's plugin.json, its hooks and
// the e2e test files; the sidecar's address, token and answers go into its
// tests/e2e-exchange.ts. The token is never printed: the suite prints
// requests with it replaced.
//
// Needs the `claude` CLI on PATH. Exits 0 when every scenario passed, 1
// when one failed (or the suite could not run), 2 when the variables are
// missing.

import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { cpSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { killGroup, onExitSignals } from './e2e-process.mjs';

const URL_VARIABLE = 'NULLPII_E2E_SIDECAR_URL';
const TOKEN_VARIABLE = 'NULLPII_E2E_SIDECAR_TOKEN';
/** Leads every line the suite prints for this script. Kept in step with
 * `LINE_PREFIX` in e2e-bridge.ts. */
const LINE_PREFIX = 'nullpii-e2e';
/** What a printed request carries in place of the token. Kept in step
 * with `REDACTED_AUTHORIZATION` in e2e-bridge.ts. */
const REDACTED_AUTHORIZATION = 'Bearer <the sidecar token>';
const RUN_ID_BYTES = 8;
/** Rounds before the run gives up: a scenario makes about ten requests. */
const MAX_ROUNDS = 40;
/** How long one sidecar request, and one run of the suite, may take. */
const REQUEST_TIMEOUT_MS = 120_000;
const SUITE_TIMEOUT_MS = 300_000;
const EXIT_FAILED = 1;
const EXIT_USAGE = 2;
const PRIVATE_FILE_MODE = 0o600;
const CONTENT_TYPE = 'content-type';

const MOD_DIR = dirname(dirname(fileURLToPath(import.meta.url)));
/** What the scratch copy of the mod holds, from the mod's folder. */
const MOD_FILES = [
  '.claude-plugin/plugin.json',
  'hooks',
  'tests/e2e.test.ts',
  'tests/e2e-bridge.ts',
];
const EXCHANGE_FILE = 'tests/e2e-exchange.ts';
const LOOPBACK_ORIGIN = /^http:\/\/(127\.0\.0\.1|\[::1\]):\d{1,5}$/;
const MIN_TOKEN_LENGTH = 32;

function say(line) {
  process.stderr.write(`e2e: ${line}\n`);
}

/** The sidecar this run tests, from the environment; undefined when unset. */
function readSidecar() {
  const url = process.env[URL_VARIABLE];
  const token = process.env[TOKEN_VARIABLE];
  if (url === undefined || url === '' || token === undefined || token === '') return undefined;
  if (!LOOPBACK_ORIGIN.test(url)) {
    throw new Error(`${URL_VARIABLE} must be http://127.0.0.1:<port> or http://[::1]:<port>`);
  }
  if (token.length < MIN_TOKEN_LENGTH) {
    throw new Error(`${TOKEN_VARIABLE} must be at least ${MIN_TOKEN_LENGTH} characters`);
  }
  return { url, token };
}

/** Send one request to the sidecar, the token put back in its place. */
async function forward(sidecar, request) {
  const headers = { ...request.headers };
  if (headers.authorization === REDACTED_AUTHORIZATION) {
    headers.authorization = `Bearer ${sidecar.token}`;
  }
  const res = await fetch(sidecar.url + request.path, {
    method: request.method,
    headers,
    ...(request.body !== undefined && { body: request.body }),
    redirect: 'manual',
    signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
  });
  return { status: res.status, headers: Object.fromEntries(res.headers), text: await res.text() };
}

/** A private scratch copy of the mod, with the e2e test files only. */
function stageMod() {
  const dir = mkdtempSync(join(tmpdir(), 'nullpii-mod-e2e-'));
  for (const file of MOD_FILES) cpSync(join(MOD_DIR, file), join(dir, file), { recursive: true });
  return dir;
}

function writeExchange(dir, exchange) {
  const source = [
    '// SPDX-License-Identifier: Apache-2.0',
    '// Written by tests/e2e-run.mjs for one run of the e2e suite.',
    `export const EXCHANGE: unknown = ${JSON.stringify(exchange, null, 2)};`,
    '',
  ].join('\n');
  writeFileSync(join(dir, EXCHANGE_FILE), source, { mode: PRIVATE_FILE_MODE });
}

/** Why `claude` did not start, in words. */
function spawnFailure(err) {
  if (err.code === 'ENOENT') return new Error(`the \`claude\` CLI is not on PATH (${err.message})`);
  return err;
}

/** Run `claude plugin test` on the scratch copy, its output captured, its
 * process kept in `running` while it runs, and killed when it outlasts
 * SUITE_TIMEOUT_MS. The timer is this script's own, not spawn's `timeout`
 * option: Node clears that one only on the child's 'exit', which a child
 * that never started never emits, so it would hold this process (and the
 * gateway e2e-sidecar.mjs started) for the whole timeout.
 *
 * `claude` may be a launcher that runs the test in a process of its own,
 * which shares its stdout and stderr: killing the launcher alone leaves
 * that one running, holding the pipes, so 'close' never comes. So `claude`
 * leads a process group of its own (`detached`), and the whole group is
 * killed. Once timed out, the run ends on the launcher's 'exit', its pipes
 * closed, so a process that left the group cannot hold the run up. */
function runSuite(dir, running) {
  return new Promise((resolve, reject) => {
    const child = spawn('claude', ['plugin', 'test', dir], {
      stdio: ['ignore', 'pipe', 'pipe'],
      detached: true,
    });
    running.add(child);
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      killGroup(child);
    }, SUITE_TIMEOUT_MS);
    child.once('exit', () => {
      if (!timedOut) return;
      child.stdout.destroy();
      child.stderr.destroy();
    });
    const settle = () => {
      clearTimeout(timer);
      running.delete(child);
    };
    const out = { stdout: '', stderr: '' };
    child.stdout.setEncoding('utf8').on('data', (piece) => {
      out.stdout += piece;
    });
    child.stderr.setEncoding('utf8').on('data', (piece) => {
      out.stderr += piece;
    });
    child.on('error', (err) => {
      settle();
      reject(spawnFailure(err));
    });
    child.once('close', (status, signal) => {
      settle();
      if (timedOut) reject(new Error(`the suite did not end within ${SUITE_TIMEOUT_MS / 1000} s`));
      else resolve({ ...out, status: status ?? signal });
    });
  });
}

/** Take one line the suite printed for this script into `lines`. */
function takeLine(lines, kind, payload) {
  if (kind === 'plan') lines.plan = payload;
  else if (kind === 'wait') lines.waits.push(payload);
  else if (kind === 'challenge') lines.challenges.push(payload);
  else if (kind === 'signed') lines.signed.push(payload);
  else if (kind === 'done') lines.done.add(payload);
  else throw new Error(`unknown line from the suite: ${kind}`);
}

/** The suite's lines for this script, from either stream (the test kit
 * writes a test's console to stderr), and the rest: the runner's report
 * (stdout) and anything else on stderr. */
function readLines(suite) {
  const lines = {
    plan: undefined,
    waits: [],
    challenges: [],
    signed: [],
    done: new Set(),
    report: [],
    other: [],
  };
  for (const [stream, rest] of [
    [suite.stdout, lines.report],
    [suite.stderr, lines.other],
  ]) {
    for (const line of stream.split('\n')) {
      const match = line.startsWith(`${LINE_PREFIX} `) ? /^\S+ (\w+) (.*)$/.exec(line) : null;
      if (match === null) rest.push(line);
      else takeLine(lines, match[1], JSON.parse(match[2]));
    }
  }
  return lines;
}

/** Send the first of the mod's challenges the scenarios wait on, exactly
 * as the mod wrote it, and record the answer: the bridge answers each
 * later challenge that is this one but for its nonce. Resolves with the
 * number of requests sent. */
async function answerChallenge(sidecar, exchange, challenges) {
  const [first] = challenges;
  if (first === undefined) return 0;
  if (exchange.challenge !== undefined) {
    throw new Error(`scenario ${first.scenario} waits on a challenge, which was answered already`);
  }
  exchange.challenge = { request: first.request, response: await forward(sidecar, first.request) };
  return 1;
}

/** Send each request a scenario waits on, and record the answers. */
async function answerWaits(sidecar, steps, waits) {
  for (const { scenario, index, request } of waits) {
    steps[scenario] ??= [];
    const recorded = steps[scenario];
    if (recorded.length !== index) {
      throw new Error(`scenario ${scenario} waits on request ${index}, not ${recorded.length}`);
    }
    recorded.push({ request, response: await forward(sidecar, request) });
  }
}

/** Why the sidecar's answer `real` is not the bridge's `signed`; undefined
 * when they are the same answer. */
function answerMismatch(real, signed) {
  if (real.status !== signed.status) return `status ${real.status}, the bridge's ${signed.status}`;
  if (real.headers[CONTENT_TYPE] !== signed.headers[CONTENT_TYPE]) {
    return `content type ${real.headers[CONTENT_TYPE]}, the bridge's ${signed.headers[CONTENT_TYPE]}`;
  }
  if (real.text !== signed.text) return 'another body';
  return undefined;
}

/** Send each challenge the bridge answered itself (`signed`) to the
 * sidecar, exactly as the mod wrote it; resolves with how many the
 * sidecar answered otherwise than the bridge, each one said. */
async function checkSigned(sidecar, signed) {
  let wrong = 0;
  for (const { scenario, request, response } of signed) {
    const why = answerMismatch(await forward(sidecar, request), response);
    if (why === undefined) continue;
    wrong += 1;
    say(`scenario ${scenario}: the sidecar answers a challenge the bridge answered with ${why}`);
  }
  return wrong;
}

/** Print what the suite reported, without the bridge's lines. */
function printReport(lines) {
  process.stdout.write(lines.report.join('\n'));
  const other = lines.other.filter((line) => line !== '');
  if (other.length > 0) process.stderr.write(`${other.join('\n')}\n`);
}

/** Whether the final round ran every scenario to its end, and passed. */
function verdict(suite, lines) {
  if (lines.plan === undefined || lines.plan.length === 0) {
    say('the suite ran no scenario: was the exchange file read?');
    return false;
  }
  const missing = lines.plan.filter((id) => !lines.done.has(id));
  if (missing.length > 0) say(`scenarios that did not pass to their end: ${missing.join(', ')}`);
  return suite.status === 0 && missing.length === 0;
}

async function runRounds(sidecar, dir, running) {
  const exchange = {
    url: sidecar.url,
    token: sidecar.token,
    run: randomBytes(RUN_ID_BYTES).toString('hex'),
    steps: {},
  };
  let asked = 0;
  for (let round = 1; round <= MAX_ROUNDS; round += 1) {
    writeExchange(dir, exchange);
    const suite = await runSuite(dir, running);
    const lines = readLines(suite);
    if (lines.waits.length === 0 && lines.challenges.length === 0) {
      printReport(lines);
      const wrong = await checkSigned(sidecar, lines.signed);
      say(
        `${round} rounds, ${asked} requests answered by the sidecar during the rounds, one of them the mod's first challenge; the verdict round's ${lines.signed.length} challenges, which the bridge answered, sent to the sidecar after it: ${lines.signed.length - wrong} answered the same`,
      );
      // The mod challenges the sidecar before every request, so a verdict
      // round with none signed means the bridge reported none: none checked.
      if (lines.signed.length === 0) say('the bridge reported no challenge it answered');
      return verdict(suite, lines) && lines.signed.length > 0 && wrong === 0;
    }
    asked += await answerChallenge(sidecar, exchange, lines.challenges);
    await answerWaits(sidecar, exchange.steps, lines.waits);
    asked += lines.waits.length;
  }
  say(`the scenarios still wait on the sidecar after ${MAX_ROUNDS} rounds`);
  return false;
}

async function main() {
  const sidecar = readSidecar();
  if (sidecar === undefined) {
    say(`set ${URL_VARIABLE} and ${TOKEN_VARIABLE} to run the suite against a sidecar`);
    return EXIT_USAGE;
  }
  const dir = stageMod();
  const running = new Set();
  removeOnSignal(dir, running);
  try {
    return (await runRounds(sidecar, dir, running)) ? 0 : EXIT_FAILED;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

/** On Ctrl-C, a kill or a hang-up: kill the suite, with every process it
 * started (its process group: being a group of its own, it does not get
 * the terminal's Ctrl-C itself), remove the scratch
 * copy (its exchange file holds the token), and exit as the signal would.
 * A second signal (Ctrl-C reaches e2e-sidecar.mjs too, which passes it
 * on) finds this handler again. */
function removeOnSignal(dir, running) {
  onExitSignals((signal, exitCode) => {
    for (const child of running) killGroup(child);
    rmSync(dir, { recursive: true, force: true });
    process.exit(exitCode);
  });
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
