// SPDX-License-Identifier: Apache-2.0
//
// The mod end to end, against a real nullpii sidecar and its model: no
// fake masks anything here. Each scenario stubs only what the mod needs
// from a session (its id, directory, store, toasts, the line under the
// prompt) and the results of the tools it calls. Every request the mod
// sends goes through e2e-bridge.ts, which answers it with the real
// sidecar's answer to that very request, but for a challenge: its nonce is
// new each time, so the bridge answers it itself when it is the mod's first
// one, which the sidecar answered, but for its nonce, and the runner sends
// each challenge the bridge answered to the sidecar once the run is over,
// to check the sidecar answers it the same. The bridge says why it is a
// bridge and not a fetch.
//
// Run it with `node packages/claude-code-mod/tests/e2e-sidecar.mjs`, which
// starts a gateway, or with tests/e2e-run.mjs against a gateway you
// started, NULLPII_E2E_SIDECAR_URL and NULLPII_E2E_SIDECAR_TOKEN set. A
// plain `claude plugin test` has no sidecar to talk to: this file then
// declares one test, which says so and passes.
//
// The values are ones the core's real-model suite proves the model finds
// (test/e2e/sanitize-real-onnx.test.ts). The assertions are on what is
// absent or put back, never on a placeholder's spelling or a score.

import type { On } from 'claude-code';
import type { Engine } from 'claude-code/testing';
import { expect, mock, test } from 'claude-code/testing';
import { PLACEHOLDER, expectedProof } from '../hooks/policy.ts';
import {
  CHALLENGE_PATH,
  type Exchange,
  type Wire,
  type WireStep,
  announceScenarios,
  openWire,
  readExchange,
} from './e2e-bridge.ts';
import { EXCHANGE } from './e2e-exchange.ts';

const CWD = '/work';
const NAME = 'Claude Dupont';
const SURNAME = 'Dupont';
const EMAIL = 'john.smith@acme.io';
/** A prompt with a name and an email. The email ends it, so its
 * placeholder is the masked prompt's last word. */
const PROMPT = `Ask ${NAME} from accounting about the invoice; his email is ${EMAIL}`;
/** The values in the prompt: the name and the email. */
const VALUES_IN_PROMPT = 2;
const FILE_EMAIL = 'claude.dupont@acme.io';
/** A file with a name and an email, as a Read returns it. */
const CONTACTS = `# Contacts\n\nowner: ${NAME} <${FILE_EMAIL}>\nbilling: Ask ${NAME} from accounting about the invoice.\n`;
/** Every real value of the scenarios: none may reach Claude or `/pii`. */
const VALUES = [NAME, SURNAME, EMAIL, FILE_EMAIL];
const SESSIONS_PATH = '/v1/sidecar/sessions/';
const SECRET_HEADER = 'x-nullpii-session-secret';
const JSON_TYPE = { 'content-type': 'application/json' } as const;
const HTTP_OK = 200;
const CREATED = 201;
const COMPOSER = { kind: 'composer' } as const;
/** How a command typed at the prompt is drawn: the main screen, 100 columns. */
const PRESENTATION = { isFullscreen: false, columns: 100 } as const;
/** The line under the prompt while masking is on: the padlock and the count. */
const STATUS_ON = '🔒';
/** The bridge answers from memory, so a scenario is quick; room for a slow runner. */
const TEST_TIMEOUT_MS = 20_000;

/** One scenario's session, its stubs, and its line to the sidecar. */
interface Scene {
  readonly $: Engine;
  readonly on: On;
  readonly wire: Wire;
  readonly exchange: Exchange;
  /** The sidecar session key: the stubbed Claude Code session id. */
  readonly key: string;
  /** Each prompt as it reached the end of `prompt.submit`: what Claude reads. */
  readonly prompts: string[];
  /** Each line the mod pinned under the prompt. */
  readonly statusLines: (string | undefined)[];
}

interface Scenario {
  readonly id: string;
  readonly name: string;
  /** Registers the scenario's own stubs first, then drives the session. */
  readonly body: (scene: Scene) => Promise<void>;
}

/** What the mod needs from a session to run, answered beneath it. */
function stubSession(on: On, key: string): Pick<Scene, 'prompts' | 'statusLines'> {
  const prompts: string[] = [];
  const statusLines: (string | undefined)[] = [];
  mock.store(on, {});
  on('session.start', () => ({ cwd: CWD }));
  on('session.cwd', () => ({ value: CWD }));
  on('session.id', () => ({ value: key }));
  on('session.end', ($, e) => ({ sessionId: e.sessionId }));
  on('command.register', ($, e) => ({ value: { command: e.name } }));
  on('ui.toast', () => ({ value: undefined }));
  on('ui.log', () => ({ value: undefined }));
  on('ui.status', ($, e) => {
    statusLines.push(e.text);
    return { value: undefined };
  });
  on('prompt.submit', ($, e) => {
    prompts.push(e.text);
    return { text: e.text };
  });
  return { prompts, statusLines };
}

async function start(scene: Scene): Promise<void> {
  await scene.$.session.start({ surface: 'terminal', isInteractive: true, cwd: CWD });
}

/** Send `text` as the person's prompt; resolves with what Claude reads. */
async function submit(scene: Scene, text: string): Promise<string> {
  const out = await scene.$.prompt.submit({ text, wait: false, origin: COMPOSER });
  expect(out.drop, 'the prompt was handed back instead of sent').toBeUndefined();
  const handed = scene.prompts.at(-1);
  if (handed === undefined) throw new Error('no prompt reached Claude');
  return handed;
}

/** Run `/pii <args>` as the person types it; resolves with what it printed. */
async function pii(scene: Scene, args: string): Promise<string> {
  const out = await scene.$.command.run({
    command: 'pii',
    args,
    origin: COMPOSER,
    presentation: PRESENTATION,
  });
  return out.text ?? '';
}

function sessionPath(key: string): string {
  return SESSIONS_PATH + encodeURIComponent(key);
}

/** `METHOD path status` of each request the sidecar answered so far. */
function routes(wire: Wire): string[] {
  return wire.calls.map(({ request, response }) => {
    return `${request.method} ${request.path} ${response.status}`;
  });
}

/** The JSON body of an answer, as an object. */
function answerBody(step: WireStep): Record<string, unknown> {
  const body: unknown = JSON.parse(step.response.text);
  if (typeof body !== 'object' || body === null) throw new Error('the answer is not an object');
  return body as Record<string, unknown>;
}

/** The secret the sidecar handed out when it created the session `key`. */
function sessionSecret(wire: Wire, key: string): string {
  const created = wire.calls.find(
    ({ request, response }) =>
      request.method === 'PUT' && request.path === sessionPath(key) && response.status === CREATED,
  );
  const secret = created === undefined ? undefined : answerBody(created).secret;
  if (typeof secret !== 'string') throw new Error('the sidecar did not create the session');
  return secret;
}

/** The headers of a request of the test's own on the session `key`. */
function ownerHeaders(scene: Scene, secret: string): Record<string, string> {
  return { authorization: `Bearer ${scene.exchange.token}`, [SECRET_HEADER]: secret };
}

/** How many values the sidecar's sanitize answers masked, all told. */
function maskedBySidecar(wire: Wire): number {
  return wire.calls
    .filter(({ request }) => request.path.endsWith('/sanitize'))
    .reduce((sum, step) => {
      const captured = answerBody(step).captured;
      return sum + (typeof captured === 'number' ? captured : 0);
    }, 0);
}

function lastWord(text: string): string {
  return text.slice(text.lastIndexOf(' ') + 1);
}

/** Fail when `seen` holds any of the scenarios' real values. */
function expectNoValue(seen: unknown, what: string): void {
  const text = JSON.stringify(seen);
  for (const value of VALUES) expect(text, `${what} holds a real value`).not.toContain(value);
}

/** What the Read tool answers for a text file. */
function readResult(filePath: string, content: string) {
  const numLines = content.split('\n').length;
  return {
    type: 'text',
    file: { filePath, content, numLines, startLine: 1, totalLines: numLines },
  } as const;
}

/** A reply of Claude's on screen, as the terminal draws it. */
function replySite(text: string) {
  return {
    plugin: 'nullpii',
    component: 'AssistantMessage',
    requestId: 'reply-1',
    surface: 'terminal',
    viewport: { columns: 100, rows: 30 },
    props: { text, isFirstOfReply: true },
  } as const;
}

const SCENARIOS: readonly Scenario[] = [
  {
    id: 'challenge',
    name: "the real sidecar answers the mod's own challenge with the proof the mod expects",
    async body(scene) {
      await start(scene);
      // The first challenge the mod sent, as it sent it, and the real
      // sidecar's answer to it.
      const recorded = scene.exchange.challenge;
      if (recorded === undefined) throw new Error("no challenge of the mod's was recorded");
      expect(recorded.request.path).toBe(CHALLENGE_PATH);
      expect(recorded.response.status).toBe(HTTP_OK);
      const nonce: unknown = JSON.parse(recorded.request.body ?? '{}').nonce;
      if (typeof nonce !== 'string') throw new Error("the mod's challenge holds no nonce");
      const proof: unknown = JSON.parse(recorded.response.text).proof;
      expect(proof).toBe(await expectedProof(scene.exchange.token, nonce));
      // The mod challenges the sidecar before each of its requests, and
      // each challenge was that one but for its nonce (the bridge answered
      // them; the runner checks the sidecar answers them the same).
      expect(scene.wire.calls.length).toBeGreaterThan(0);
      expect(scene.wire.challenges).toBe(scene.wire.calls.length);
    },
  },
  {
    id: 'session-start',
    name: 'the session start opens a session on the real sidecar, under the session id',
    async body(scene) {
      await start(scene);
      expect(routes(scene.wire)).toEqual([
        `PUT ${sessionPath(scene.key)} 201`,
        'GET /v1/sidecar/status 200',
      ]);
      // Opened again with the secret the sidecar handed out, the session
      // is one the sidecar holds.
      const secret = sessionSecret(scene.wire, scene.key);
      const again = await scene.wire.send({
        method: 'PUT',
        path: sessionPath(scene.key),
        headers: ownerHeaders(scene, secret),
      });
      expect(again.status).toBe(200);
      expect(JSON.parse(again.text)).toEqual({ status: 'exists' });
      expect(await pii(scene, 'status')).toContain('Status: on');
      expect(scene.statusLines.at(-1)).toBe(`${STATUS_ON} 0`);
    },
  },
  {
    id: 'prompt',
    name: 'a prompt with a name and an email reaches Claude masked by the sidecar',
    async body(scene) {
      await start(scene);
      const handed = await submit(scene, PROMPT);
      expect(scene.prompts).toHaveLength(1);
      expectNoValue(handed, 'the prompt Claude reads');
      expect(handed).toMatch(PLACEHOLDER);
      // What Claude reads is the sidecar's own answer.
      const sanitized = scene.wire.calls.filter(({ request }) =>
        request.path.endsWith('/sanitize'),
      );
      expect(sanitized).toHaveLength(1);
      const [step] = sanitized;
      if (step === undefined) throw new Error('no sanitize call');
      expect(answerBody(step).value).toEqual({ text: handed, context: [] });
    },
  },
  {
    id: 'read-result',
    name: 'a Read result with personal data reaches Claude masked',
    async body(scene) {
      const reads: string[] = [];
      scene.on('tool.call', { tool: 'Read' }, ($, e) => {
        reads.push(e.file_path);
        return { result: readResult(e.file_path, CONTACTS) };
      });
      await start(scene);
      const out = await scene.$.tool.call({ tool: 'Read', file_path: `${CWD}/contacts.md` });
      expect(reads).toEqual([`${CWD}/contacts.md`]);
      expectNoValue(out, 'the Read result Claude reads');
      expect(JSON.stringify(out.result)).toMatch(PLACEHOLDER);
      // The call held no placeholder, so it ran as Claude wrote it.
      expect(routes(scene.wire).filter((route) => route.includes('/restore'))).toEqual([]);
    },
  },
  {
    id: 'restore-local',
    name: 'a placeholder in a Read or Edit call gets its real value back before the tool runs',
    async body(scene) {
      const reads: string[] = [];
      const edits: { file_path: string; old_string: string; new_string: string }[] = [];
      scene.on('tool.call', { tool: 'Read' }, ($, e) => {
        reads.push(e.file_path);
        return { result: readResult(e.file_path, `To: ${EMAIL}\n`) };
      });
      scene.on('tool.call', { tool: 'Edit' }, ($, e) => {
        edits.push({ file_path: e.file_path, old_string: e.old_string, new_string: e.new_string });
        return {
          result: { filePath: e.file_path, oldString: e.old_string, newString: e.new_string },
        };
      });
      await start(scene);
      const masked = await submit(scene, PROMPT);
      const email = lastWord(masked);
      expect(email).toMatch(PLACEHOLDER);
      const read = await scene.$.tool.call({ tool: 'Read', file_path: `${CWD}/mail/${email}.txt` });
      expect(reads).toEqual([`${CWD}/mail/${EMAIL}.txt`]);
      expectNoValue(read, 'the Read result Claude reads');
      // The whole masked prompt comes back word for word.
      const edit = await scene.$.tool.call({
        tool: 'Edit',
        file_path: `${CWD}/notes.md`,
        old_string: masked,
        new_string: `${masked} (done)`,
      });
      expect(edits).toEqual([
        { file_path: `${CWD}/notes.md`, old_string: PROMPT, new_string: `${PROMPT} (done)` },
      ]);
      expectNoValue(edit, 'the Edit result Claude reads');
    },
  },
  {
    id: 'webfetch',
    name: 'a placeholder in a WebFetch call stays a placeholder: nothing goes back into a tool that sends data away',
    async body(scene) {
      const urls: string[] = [];
      scene.on('tool.call', { tool: 'WebFetch' }, ($, e) => {
        urls.push(e.url);
        return { result: 'No results.' };
      });
      await start(scene);
      const email = lastWord(await submit(scene, PROMPT));
      expect(email).toMatch(PLACEHOLDER);
      const url = `https://example.com/search?q=${email}`;
      await scene.$.tool.call({ tool: 'WebFetch', url, prompt: 'List the results' });
      expect(urls).toEqual([url]);
      const report = await pii(scene, 'status');
      expect(report).toContain('Real values put back into local tool calls: 0');
      expect(report).toContain('Placeholders kept in calls to other tools: 1');
    },
  },
  {
    id: 'bash',
    name: 'a Bash call that holds a placeholder is refused, and never runs',
    async body(scene) {
      const commands: string[] = [];
      scene.on('tool.call', { tool: 'Bash' }, ($, e) => {
        commands.push(e.command);
        return { result: { stdout: '', stderr: '' } };
      });
      await start(scene);
      const email = lastWord(await submit(scene, PROMPT));
      expect(email).toMatch(PLACEHOLDER);
      const out = await scene.$.tool.call({ tool: 'Bash', command: `grep -rl ${email} .` });
      expect(commands).toEqual([]);
      expect(out.deny).toContain('nullpii puts no real value into a shell command');
      expect(out.deny).toContain(email);
      expectNoValue(out, 'the refusal Claude reads');
      // The refusal follows the sidecar's answer, which listed the placeholder.
      expect(routes(scene.wire)).toContain(`POST ${sessionPath(scene.key)}/restore 200`);
    },
  },
  {
    id: 'pii-report',
    name: '/pii reports what was masked as counts by type, never a value',
    async body(scene) {
      scene.on('tool.call', { tool: 'Read' }, ($, e) => ({
        result: readResult(e.file_path, CONTACTS),
      }));
      await start(scene);
      await submit(scene, PROMPT);
      await scene.$.tool.call({ tool: 'Read', file_path: `${CWD}/contacts.md` });
      // `/pii` with nothing to answer its menu prints the status and the help.
      const report = await pii(scene, '');
      // The count is the sum of what the sidecar's answers say they masked.
      const masked = maskedBySidecar(scene.wire);
      expect(masked).toBeGreaterThanOrEqual(VALUES_IN_PROMPT);
      expect(report).toContain(`Masked before Claude read them: ${masked} (`);
      expect(report).toMatch(/\bperson \d+\b/);
      expect(report).toMatch(/\bemail \d+\b/);
      expectNoValue(report, 'the /pii report');
      expect(scene.statusLines.at(-1)).toBe(`${STATUS_ON} ${masked}`);
    },
  },
  {
    id: 'session-end',
    name: "the session's end closes its session on the real sidecar, and its values go with it",
    async body(scene) {
      await start(scene);
      const masked = await submit(scene, PROMPT);
      const secret = sessionSecret(scene.wire, scene.key);
      await scene.$.session.end({
        reason: 'prompt_input_exit',
        sessionId: scene.key,
        resume: { id: scene.key },
      });
      expect(routes(scene.wire).at(-1)).toBe(`DELETE ${sessionPath(scene.key)} 204`);
      // A restore on that session, with its own secret, finds no session.
      const after = await scene.wire.send({
        method: 'POST',
        path: `${sessionPath(scene.key)}/restore`,
        headers: { ...ownerHeaders(scene, secret), ...JSON_TYPE },
        body: JSON.stringify({ value: masked }),
      });
      expect(after.status).toBe(404);
      expect(JSON.parse(after.text)).toEqual({ error: 'session_not_found' });
    },
  },
  {
    id: 'display',
    name: "Claude's reply is drawn with the real values, while Claude reads the placeholders",
    async body(scene) {
      scene.on('ui.render', { component: 'AssistantMessage' }, ($, e) => ({
        type: 'Text',
        props: {},
        children: [e.props.text],
      }));
      await start(scene);
      const masked = await submit(scene, PROMPT);
      expectNoValue(masked, 'the prompt Claude reads');
      const ui = await scene.$.ui.mount(replySite(`Done: ${masked}`));
      expect(await ui.find({ type: 'Text', text: `Done: ${PROMPT}` })).toBeDefined();
      await ui.unmount();
    },
  },
];

/** The plugin options of every scenario: the real sidecar, its token, and
 * no sidecar of the mod's own (the test kit runs no process). */
function optionsOf(exchange: Exchange) {
  return { sidecar_url: exchange.url, sidecar_token: exchange.token, autostart: false };
}

function declareScenarios(exchange: Exchange): void {
  announceScenarios(SCENARIOS.map(({ id }) => id));
  for (const scenario of SCENARIOS) {
    const options = { options: optionsOf(exchange), timeoutMs: TEST_TIMEOUT_MS };
    test(scenario.name, options, async ($, on) => {
      const key = `e2e-${exchange.run}-${scenario.id}`;
      const wire = openWire(on, exchange, scenario.id);
      const scene: Scene = { $, on, wire, exchange, key, ...stubSession(on, key) };
      await wire.run(() => scenario.body(scene));
    });
  }
}

const exchange = readExchange(EXCHANGE);
if (exchange === undefined) {
  test('end to end against a real sidecar: not run here, as no sidecar was given (tests/e2e-sidecar.mjs starts one and runs it, with NULLPII_E2E_SIDECAR_URL and NULLPII_E2E_SIDECAR_TOKEN set)', () =>
    undefined);
} else {
  declareScenarios(exchange);
}
