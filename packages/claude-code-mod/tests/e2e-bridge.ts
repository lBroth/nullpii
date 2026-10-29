// SPDX-License-Identifier: Apache-2.0
//
// The bridge between the mod and a real nullpii sidecar, for e2e.test.ts.
//
// `claude plugin test` runs a test in the sandbox a mod's hooks run in: no
// network, file system or environment, and nothing beneath the plugins
// answers `$.http.fetch`. So a test cannot reach a sidecar itself. Instead
// the bridge answers the mod's `http.fetch` calls (the mod's one door to
// the sidecar) from the real sidecar's answers that tests/e2e-run.mjs
// recorded, in order, after checking that each request is the very one its
// answer was recorded for. At the first request it has no answer for, it
// prints that request on a `nullpii-e2e wait` line and refuses it. The
// runner sends the request to the sidecar, records the answer, and runs
// the suite again. The run in which no test waits is the verdict: each
// answer the mod got in it is the real sidecar's answer to that request.
//
// The challenge (`POST /v1/sidecar/challenge`) carries a fresh random nonce
// every time, so no recorded answer can match it. The bridge signs it with
// the sidecar's token, as the sidecar does: one test checks that the real
// sidecar's proof is the one the mod expects.

import type { On } from 'claude-code';
import { expectedProof } from '../hooks/policy.ts';

/** The test runner's console, which a test file has (claude-code.d.ts
 * types a hooks module's globals, which have none): its lines reach the
 * runner's stderr, the one way out of the test sandbox. */
declare const console: { info(line: string): void };

/** Leads every line the suite prints for the runner, on stderr. Kept in
 * step with `LINE_PREFIX` in e2e-run.mjs. */
export const LINE_PREFIX = 'nullpii-e2e';
/** What a printed request carries in place of the sidecar token, which is
 * never printed; the runner puts the token back before it sends the
 * request. Kept in step with `REDACTED_AUTHORIZATION` in e2e-run.mjs. */
export const REDACTED_AUTHORIZATION = 'Bearer <the sidecar token>';
const CHALLENGE_PATH = '/v1/sidecar/challenge';
const HTTP_OK = 200;
const HTTP_SUCCESS_END = 300;
const JSON_HEADERS: Readonly<Record<string, string>> = { 'content-type': 'application/json' };
/** Why the bridge refuses a request it has no answer for yet. */
const NO_ANSWER_YET = 'nullpii e2e bridge: the sidecar has not answered this request yet';

/** One request to the sidecar, as the runner sends it. */
export interface WireRequest {
  readonly method: string;
  /** Path and query, from the sidecar's origin. */
  readonly path: string;
  readonly headers: Readonly<Record<string, string>>;
  readonly body?: string;
}

/** The sidecar's answer to one request. */
export interface WireResponse {
  readonly status: number;
  /** Lower-case names, as `$.http.fetch` answers them. */
  readonly headers: Readonly<Record<string, string>>;
  readonly text: string;
}

export interface WireStep {
  readonly request: WireRequest;
  readonly response: WireResponse;
}

/** What tests/e2e-run.mjs hands the suite: the sidecar, and its answers so far. */
export interface Exchange {
  /** The sidecar's origin, `http://127.0.0.1:<port>`. */
  readonly url: string;
  /** Its token: the mod's `sidecar_token` option, and the challenge key. */
  readonly token: string;
  /** Unique to this run of the suite, in every sidecar session key. */
  readonly run: string;
  /** One challenge the real sidecar answered, with a nonce of the runner's. */
  readonly challenge: { readonly nonce: string; readonly proof: string };
  /** The sidecar's answers, by scenario, in the order they were asked for. */
  readonly steps: Readonly<Record<string, readonly WireStep[]>>;
}

/** One test's view of the bridge. */
export interface Wire {
  /** Every request answered so far in this test (challenges left out), in order. */
  readonly calls: readonly WireStep[];
  /** Send a request of the test's own to the sidecar, in turn with the mod's. */
  send(request: WireRequest): Promise<WireResponse>;
  /** Run the test's body, and settle the test: it fails as the body does,
   * or when the mod's requests are not the recorded ones; it passes, so the
   * runner can answer, while a request still waits for the sidecar. */
  run(body: () => Promise<void>): Promise<void>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function readString(value: unknown, what: string): string {
  if (typeof value !== 'string') throw new Error(`e2e exchange: ${what} is not a string`);
  return value;
}

function readStrings(value: unknown, what: string): Record<string, string> {
  if (!isRecord(value)) throw new Error(`e2e exchange: ${what} is not an object`);
  return Object.fromEntries(
    Object.entries(value).map(([key, entry]) => [key, readString(entry, `${what}.${key}`)]),
  );
}

function readRequest(value: unknown, what: string): WireRequest {
  if (!isRecord(value)) throw new Error(`e2e exchange: ${what} is not an object`);
  return {
    method: readString(value.method, `${what}.method`),
    path: readString(value.path, `${what}.path`),
    headers: readStrings(value.headers, `${what}.headers`),
    ...(value.body !== undefined && { body: readString(value.body, `${what}.body`) }),
  };
}

function readResponse(value: unknown, what: string): WireResponse {
  if (!isRecord(value) || typeof value.status !== 'number') {
    throw new Error(`e2e exchange: ${what} has no status`);
  }
  return {
    status: value.status,
    headers: readStrings(value.headers, `${what}.headers`),
    text: readString(value.text, `${what}.text`),
  };
}

function readSteps(value: unknown): Record<string, WireStep[]> {
  if (!isRecord(value)) throw new Error('e2e exchange: steps is not an object');
  return Object.fromEntries(
    Object.entries(value).map(([scenario, steps]) => {
      if (!Array.isArray(steps)) throw new Error(`e2e exchange: steps.${scenario} is not a list`);
      return [
        scenario,
        steps.map((step: unknown, i) => {
          const what = `steps.${scenario}[${i}]`;
          if (!isRecord(step)) throw new Error(`e2e exchange: ${what} is not an object`);
          return {
            request: readRequest(step.request, `${what}.request`),
            response: readResponse(step.response, `${what}.response`),
          };
        }),
      ];
    }),
  );
}

/** The exchange the runner wrote, checked; undefined when there is none
 * (the file as committed: no sidecar to talk to). */
export function readExchange(raw: unknown): Exchange | undefined {
  if (raw === undefined) return undefined;
  if (!isRecord(raw)) throw new Error('e2e exchange: not an object');
  const challenge = raw.challenge;
  if (!isRecord(challenge)) throw new Error('e2e exchange: challenge is not an object');
  return {
    url: readString(raw.url, 'url'),
    token: readString(raw.token, 'token'),
    run: readString(raw.run, 'run'),
    challenge: {
      nonce: readString(challenge.nonce, 'challenge.nonce'),
      proof: readString(challenge.proof, 'challenge.proof'),
    },
    steps: readSteps(raw.steps),
  };
}

/** Print one line for the runner. The test sandbox has no other way out. */
function printLine(kind: string, payload: unknown): void {
  console.info(`${LINE_PREFIX} ${kind} ${JSON.stringify(payload)}`);
}

/** Tell the runner which scenarios the suite holds, so it can check that
 * each of them ran to its end. */
export function announceScenarios(ids: readonly string[]): void {
  printLine('plan', ids);
}

/** `headers` as the runner gets them: the token never printed. */
function redacted(
  token: string,
  headers: Readonly<Record<string, string>>,
): Record<string, string> {
  const out = { ...headers };
  if (out.authorization === `Bearer ${token}`) out.authorization = REDACTED_AUTHORIZATION;
  return out;
}

/** A `$.http.fetch` call of the mod's, as the runner sends it. */
function wireRequest(
  token: string,
  url: URL,
  init: { method?: string; headers?: Record<string, string>; body?: string } | undefined,
): WireRequest {
  return {
    method: init?.method ?? 'GET',
    path: url.pathname + url.search,
    headers: redacted(token, init?.headers ?? {}),
    ...(init?.body !== undefined && { body: init.body }),
  };
}

/** One form of a request whatever the order of its headers. */
function canonical(request: WireRequest): string {
  const headers = Object.entries(request.headers).sort(([a], [b]) => a.localeCompare(b));
  return JSON.stringify([request.method, request.path, headers, request.body ?? null]);
}

function httpResponse(response: WireResponse) {
  const ok = response.status >= HTTP_OK && response.status < HTTP_SUCCESS_END;
  return { status: response.status, ok, headers: { ...response.headers }, text: response.text };
}

/** The sidecar's answer to a challenge: its proof that it holds `token`. */
async function challengeAnswer(token: string, body: string | undefined) {
  const parsed: unknown = JSON.parse(body ?? '{}');
  const nonce = isRecord(parsed) && typeof parsed.nonce === 'string' ? parsed.nonce : '';
  const text = JSON.stringify({ proof: await expectedProof(token, nonce) });
  return { value: { status: HTTP_OK, ok: true, headers: { ...JSON_HEADERS }, text } };
}

/** The recorded answers of one scenario, walked in order. */
class Cursor {
  readonly calls: WireStep[] = [];
  waiting = false;
  diverged: string | undefined;

  constructor(
    private readonly scenario: string,
    private readonly recorded: readonly WireStep[],
  ) {}

  /** The sidecar's answer to `request`, the next one asked for; undefined
   * when there is none yet (printed for the runner), or the request is not
   * the recorded one. */
  answer(request: WireRequest): WireResponse | undefined {
    if (this.waiting || this.diverged !== undefined) return undefined;
    const index = this.calls.length;
    const step = this.recorded[index];
    if (step === undefined) {
      this.waiting = true;
      printLine('wait', { scenario: this.scenario, index, request });
      return undefined;
    }
    if (canonical(step.request) !== canonical(request)) {
      this.diverged = `request ${index} (${request.method} ${request.path}) is not the one the sidecar answered (${step.request.method} ${step.request.path}): the mod's requests changed between runs`;
      return undefined;
    }
    this.calls.push(step);
    return step.response;
  }

  /** Throw when the mod's requests left the recorded path. */
  checkPath(): void {
    if (this.diverged !== undefined) throw new Error(`e2e bridge: ${this.diverged}`);
  }
}

/**
 * Answer the mod's `$.http.fetch` calls in scenario `scenario` from the
 * sidecar's recorded answers, beneath the mod: the test's own hook, as the
 * unit tests' fake sidecar is.
 */
export function openWire(on: On, exchange: Exchange, scenario: string): Wire {
  const cursor = new Cursor(scenario, exchange.steps[scenario] ?? []);
  on('http.fetch', async ($, e) => {
    const url = new URL(e.url);
    if (url.origin !== exchange.url) {
      cursor.diverged ??= `the mod sent a request to ${url.origin}, not to the sidecar`;
      return { deny: 'nullpii e2e bridge: not the sidecar' };
    }
    if (url.pathname === CHALLENGE_PATH) return challengeAnswer(exchange.token, e.init?.body);
    const response = cursor.answer(wireRequest(exchange.token, url, e.init));
    return response === undefined ? { deny: NO_ANSWER_YET } : { value: httpResponse(response) };
  });
  return {
    calls: cursor.calls,
    async send(request) {
      const response = cursor.answer({
        ...request,
        headers: redacted(exchange.token, request.headers),
      });
      if (response === undefined) throw new Error(NO_ANSWER_YET);
      return response;
    },
    async run(body) {
      let failure: { readonly error: unknown } | undefined;
      try {
        await body();
      } catch (error) {
        failure = { error };
      }
      cursor.checkPath();
      // A request waits for the sidecar: what failed here failed for want
      // of its answer (the mod failed closed). The runner answers it and
      // runs the suite again; the final run has nothing waiting.
      if (cursor.waiting) return;
      if (failure !== undefined) throw failure.error;
      printLine('done', scenario);
    },
  };
}
