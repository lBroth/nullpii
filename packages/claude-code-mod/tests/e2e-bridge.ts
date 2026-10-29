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
// answer the mod got in it is the real sidecar's answer to that request,
// but for the challenges, as below.
//
// The challenge (`POST /v1/sidecar/challenge`), which the mod sends before
// every other request, carries a fresh random nonce every time, and a test
// cannot make it reproducible (the mod's hooks draw it from their own
// `crypto`, which a test's stub does not reach). So no recorded answer can
// match one word for word, and no challenge of the verdict run is answered
// by the sidecar while the run goes on, not even its first. The first
// challenge the mod sends, in the first run, waits like any other request:
// the runner sends it, exactly as the mod wrote it, to the sidecar and
// records the answer, which must be a 200 with the proof the mod expects
// for that nonce. Every later challenge must be that same request but for
// its nonce, which must be as long as the recorded one and drawn from the
// same characters; the bridge then answers it itself, with the recorded
// answer, its proof signed with the sidecar's token for the new nonce (the
// mod's own `expectedProof`), and prints the request and that answer on a
// `nullpii-e2e signed` line. Once the verdict run is over, the runner sends
// each of those requests to the sidecar, exactly as the mod wrote it, and
// fails the run unless the sidecar's answer is the bridge's (status,
// content type and body): the challenge holds no state, so its answer
// then is its answer during the run. A challenge that differs from the
// recorded one in anything else (method, path or query, a header, the rest
// of the body) leaves the recorded path, and its test fails.

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
export const CHALLENGE_PATH = '/v1/sidecar/challenge';
const HTTP_OK = 200;
const HTTP_SUCCESS_END = 300;
/** What stands in for a challenge's nonce when two challenges are compared. */
const NONCE_MASK = '<nonce>';
/** Why the bridge refuses a request it has no answer for yet. */
const NO_ANSWER_YET = 'nullpii e2e bridge: the sidecar has not answered this request yet';
/** Why the bridge refuses a request that is not the one the sidecar answered. */
const OFF_PATH = 'nullpii e2e bridge: not the request the sidecar answered';

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
  /** The first challenge the mod sent, as it sent it, and the real
   * sidecar's answer to it; absent until the runner has sent one. */
  readonly challenge?: WireStep;
  /** The sidecar's answers, by scenario, in the order they were asked for. */
  readonly steps: Readonly<Record<string, readonly WireStep[]>>;
}

/** One test's view of the bridge. */
export interface Wire {
  /** Every request answered so far in this test (challenges left out), in order. */
  readonly calls: readonly WireStep[];
  /** How many of the mod's challenges were answered so far in this test. */
  readonly challenges: number;
  /** Send a request of the test's own to the sidecar, in turn with the mod's. */
  send(request: WireRequest): Promise<WireResponse>;
  /** Run the test's body, and settle the test: it fails as the body does,
   * or when the mod's requests are not the recorded ones; it passes, so the
   * runner can answer, while a request still waits for the sidecar. */
  run(body: () => Promise<void>): Promise<void>;
}

/** A `$.http.fetch` call of the mod's, as the bridge's hook gets it. */
export interface FetchCall {
  readonly url: string;
  readonly init?: { method?: string; headers?: Record<string, string>; body?: string };
}

/** What the bridge's hook answers a `$.http.fetch` call with. */
export type FetchAnswer =
  | { readonly deny: string }
  | {
      readonly value: {
        status: number;
        ok: boolean;
        headers: Record<string, string>;
        text: string;
      };
    };

/** The bridge of one scenario: its hook's answer to each call, and the
 * test's view of it. */
export interface Bridge {
  readonly wire: Wire;
  fetch(call: FetchCall): Promise<FetchAnswer>;
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

function readStep(value: unknown, what: string): WireStep {
  if (!isRecord(value)) throw new Error(`e2e exchange: ${what} is not an object`);
  return {
    request: readRequest(value.request, `${what}.request`),
    response: readResponse(value.response, `${what}.response`),
  };
}

function readSteps(value: unknown): Record<string, WireStep[]> {
  if (!isRecord(value)) throw new Error('e2e exchange: steps is not an object');
  return Object.fromEntries(
    Object.entries(value).map(([scenario, steps]) => {
      if (!Array.isArray(steps)) throw new Error(`e2e exchange: steps.${scenario} is not a list`);
      return [scenario, steps.map((step: unknown, i) => readStep(step, `steps.${scenario}[${i}]`))];
    }),
  );
}

/** The exchange the runner wrote, checked; undefined when there is none
 * (the file as committed: no sidecar to talk to). */
export function readExchange(raw: unknown): Exchange | undefined {
  if (raw === undefined) return undefined;
  if (!isRecord(raw)) throw new Error('e2e exchange: not an object');
  return {
    url: readString(raw.url, 'url'),
    token: readString(raw.token, 'token'),
    run: readString(raw.run, 'run'),
    ...(raw.challenge !== undefined && { challenge: readStep(raw.challenge, 'challenge') }),
    steps: readSteps(raw.steps),
  };
}

/** Where the bridge prints its lines for the runner. */
export type PrintLine = (line: string) => void;

/** The test runner's console: the test sandbox has no other way out. */
const toConsole: PrintLine = (line) => console.info(line);

/** Print one line for the runner, a `kind` and its payload. */
function printLine(kind: string, payload: unknown, print: PrintLine = toConsole): void {
  print(`${LINE_PREFIX} ${kind} ${JSON.stringify(payload)}`);
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
function wireRequest(token: string, url: URL, init: FetchCall['init']): WireRequest {
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

/** `text` as a JSON object; undefined when it is not one. */
function jsonObject(text: string | undefined): Record<string, unknown> | undefined {
  if (text === undefined) return undefined;
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return undefined;
  }
  return isRecord(parsed) ? parsed : undefined;
}

/** The nonce a challenge's body carries; undefined when it carries none. */
function nonceIn(request: WireRequest): string | undefined {
  const nonce = jsonObject(request.body)?.nonce;
  return typeof nonce === 'string' && nonce !== '' ? nonce : undefined;
}

/** A challenge's canonical form, its nonce masked. */
function maskedForm(request: WireRequest, nonce: string): string {
  return canonical({ ...request, body: (request.body ?? '').split(nonce).join(NONCE_MASK) });
}

/** The kind of a nonce's character, to compare two nonces' alphabets. */
function charKind(char: string): string {
  if (/[0-9]/.test(char)) return 'digit';
  if (/[a-f]/.test(char)) return 'lower-case hex';
  if (/[A-F]/.test(char)) return 'upper-case hex';
  return JSON.stringify(char);
}

function charKinds(nonce: string): Set<string> {
  return new Set([...nonce].map(charKind));
}

/** Why `nonce` is not of the recorded nonce's length and characters;
 * undefined when it is. */
function nonceMismatch(nonce: string, recorded: string): string | undefined {
  if (nonce.length !== recorded.length) {
    return `its nonce has ${nonce.length} characters, the recorded one ${recorded.length}`;
  }
  const allowed = charKinds(recorded);
  const stray = [...charKinds(nonce)].filter((kind) => !allowed.has(kind));
  if (stray.length === 0) return undefined;
  return `its nonce holds characters the recorded one has none of (${stray.join(', ')})`;
}

/** The recorded challenge, checked: its nonce, and the body of the
 * sidecar's answer, which holds the proof the mod expects for that nonce.
 * A string says why it is not that. */
async function recordedChallenge(
  token: string,
  recorded: WireStep,
): Promise<{ readonly nonce: string; readonly answer: Record<string, unknown> } | string> {
  const nonce = nonceIn(recorded.request);
  if (nonce === undefined) return 'the recorded challenge holds no nonce';
  if (recorded.response.status !== HTTP_OK) {
    return `the sidecar answered the mod's challenge with ${recorded.response.status}, not ${HTTP_OK}`;
  }
  const answer = jsonObject(recorded.response.text);
  if (answer === undefined || answer.proof !== (await expectedProof(token, nonce))) {
    return "the sidecar's answer to the mod's challenge is not the proof the mod expects";
  }
  return { nonce, answer };
}

/** The recorded answers of one scenario, walked in order. */
class Cursor {
  readonly calls: WireStep[] = [];
  challenges = 0;
  waiting = false;
  diverged: string | undefined;

  constructor(
    readonly scenario: string,
    private readonly recorded: readonly WireStep[],
    private readonly print: PrintLine,
  ) {}

  /** Print a `kind` line of this scenario's for the runner. */
  report(kind: string, payload: Record<string, unknown>): void {
    printLine(kind, { scenario: this.scenario, ...payload }, this.print);
  }

  /** Whether the scenario stopped: a request waits, or one left the path. */
  get stopped(): boolean {
    return this.waiting || this.diverged !== undefined;
  }

  /** Why the bridge refuses a request it gives no answer to. */
  get refusal(): string {
    return this.diverged === undefined ? NO_ANSWER_YET : OFF_PATH;
  }

  /** Stop at a request the sidecar has not answered yet, printed for the
   * runner on a `kind` line. */
  wait(kind: 'wait' | 'challenge', payload: Record<string, unknown>): void {
    this.waiting = true;
    this.report(kind, payload);
  }

  /** Mark the scenario as off the recorded path, for `why`. */
  leave(why: string): void {
    this.diverged ??= why;
  }

  /** The sidecar's answer to `request`, the next one asked for; undefined
   * when there is none yet (printed for the runner), or the request is not
   * the recorded one. */
  answer(request: WireRequest): WireResponse | undefined {
    if (this.stopped) return undefined;
    const index = this.calls.length;
    const step = this.recorded[index];
    if (step === undefined) {
      this.wait('wait', { index, request });
      return undefined;
    }
    if (canonical(step.request) !== canonical(request)) {
      this.leave(
        `request ${index} (${request.method} ${request.path}) is not the one the sidecar answered (${step.request.method} ${step.request.path}): the mod's requests changed between runs`,
      );
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

/** Why the mod's challenge `request` is not the recorded one but for its
 * nonce; undefined when it is that. */
function challengeMismatch(
  request: WireRequest,
  nonce: string,
  recorded: { readonly request: WireRequest; readonly nonce: string },
): string | undefined {
  const shape = nonceMismatch(nonce, recorded.nonce);
  if (shape !== undefined)
    return `the mod's challenge is not the one the sidecar answered: ${shape}`;
  if (maskedForm(request, nonce) === maskedForm(recorded.request, recorded.nonce)) return undefined;
  return `the mod's challenge (${request.method} ${request.path}) is not the one the sidecar answered (${recorded.request.method} ${recorded.request.path}) but for its nonce: the mod's challenge changed between runs`;
}

/** The answer to the mod's challenge `request`: the recorded answer, its
 * proof the one for this nonce, when the request is the recorded one but
 * for its nonce. The bridge signs it, not the sidecar, so it prints the
 * request and the answer on a `signed` line, for the runner to send that
 * request to the sidecar once the run is over and compare the answers. */
async function answerChallenge(
  cursor: Cursor,
  exchange: Exchange,
  request: WireRequest,
): Promise<FetchAnswer> {
  if (cursor.stopped) return { deny: cursor.refusal };
  if (exchange.challenge === undefined) {
    cursor.wait('challenge', { request });
    return { deny: NO_ANSWER_YET };
  }
  const recorded = await recordedChallenge(exchange.token, exchange.challenge);
  if (typeof recorded === 'string') {
    cursor.leave(recorded);
    return { deny: OFF_PATH };
  }
  const nonce = nonceIn(request);
  if (nonce === undefined) {
    cursor.leave("the mod's challenge holds no nonce");
    return { deny: OFF_PATH };
  }
  const why = challengeMismatch(request, nonce, {
    ...recorded,
    request: exchange.challenge.request,
  });
  if (why !== undefined) {
    cursor.leave(why);
    return { deny: OFF_PATH };
  }
  cursor.challenges += 1;
  const proof = await expectedProof(exchange.token, nonce);
  const text = JSON.stringify({ ...recorded.answer, proof });
  const response = { ...exchange.challenge.response, text };
  cursor.report('signed', { request, response });
  return { value: httpResponse(response) };
}

/**
 * The bridge of scenario `scenario`: it answers the mod's `$.http.fetch`
 * calls from the sidecar's recorded answers, and prints its lines for the
 * runner with `print` (the test runner's console unless given).
 */
export function openBridge(
  exchange: Exchange,
  scenario: string,
  print: PrintLine = toConsole,
): Bridge {
  const cursor = new Cursor(scenario, exchange.steps[scenario] ?? [], print);
  const wire: Wire = {
    calls: cursor.calls,
    get challenges() {
      return cursor.challenges;
    },
    async send(request) {
      const response = cursor.answer({
        ...request,
        headers: redacted(exchange.token, request.headers),
      });
      if (response === undefined) throw new Error(cursor.refusal);
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
      printLine('done', scenario, print);
    },
  };
  return {
    wire,
    async fetch(call) {
      const url = new URL(call.url);
      if (url.origin !== exchange.url) {
        cursor.leave(`the mod sent a request to ${url.origin}, not to the sidecar`);
        return { deny: 'nullpii e2e bridge: not the sidecar' };
      }
      const request = wireRequest(exchange.token, url, call.init);
      if (url.pathname === CHALLENGE_PATH) return answerChallenge(cursor, exchange, request);
      const response = cursor.answer(request);
      return response === undefined ? { deny: cursor.refusal } : { value: httpResponse(response) };
    },
  };
}

/**
 * Answer the mod's `$.http.fetch` calls in scenario `scenario` from the
 * sidecar's recorded answers, beneath the mod: the test's own hook, as the
 * unit tests' fake sidecar is.
 */
export function openWire(on: On, exchange: Exchange, scenario: string): Wire {
  const bridge = openBridge(exchange, scenario);
  on('http.fetch', ($, e) => bridge.fetch(e));
  return bridge.wire;
}
