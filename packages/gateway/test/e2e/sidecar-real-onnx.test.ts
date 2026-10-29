// SPDX-License-Identifier: Apache-2.0
//
// The sidecar API (`/v1/sidecar/*`) on the real GLiNER model: the life of
// a session, sanitize of a prompt and of a JSON tool result, the sanitize
// cache, one placeholder per value, restore into tools by the gateway's
// rules, and a live policy change. Gated like the core real-ONNX suite
// (see `helpers.ts`); skipped in the default unit run.

import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import type { FastifyInstance } from 'fastify';
import { DEFAULT_RESTORE_TOOLS, type NullPii, PLACEHOLDER_TEMPLATE } from 'nullpii';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { buildServer } from '../../src/server.js';
import {
  E2E_CONFIG,
  PII,
  PROMPT,
  SKIP,
  TEST_TIMEOUT_MS,
  WARMUP_TIMEOUT_MS,
  leaked,
  placeholderLabels,
  placeholdersIn,
  sessionPrefixOf,
  startRealEngine,
  total,
} from './helpers.js';
import {
  CACHE_HEADER,
  type PolicyView,
  type RestoreAnswer,
  SIDECAR_TOKEN,
  type SanitizeAnswer,
  type SidecarSession,
  bearerOnly,
  maskIn,
  openSession,
  placeholderOf,
  policyNow,
  putPolicy,
  restoreIn,
  sanitizeIn,
  sessionHeaders,
  sessionPath,
  unmaskIn,
} from './sidecar-client.js';

const OK = 200;
const NO_CONTENT = 204;
const FORBIDDEN = 403;
const NOT_FOUND = 404;
const POLICY_CHANGED = 412;
/** 32 random bytes in base64url: the length of a session secret. */
const SECRET_LENGTH = 43;
const SECRET_PATTERN = new RegExp(`^[A-Za-z0-9_-]{${SECRET_LENGTH}}$`);
const POLICY_VERSION_PATTERN = /^[0-9a-f]{32}$/;
const POLICY_FILE_NAME = 'config.json';
/** A vault index no session of this suite reaches. */
const UNMINTED_INDEX = 99_999;

/** A tool result as an agent reads it: nested objects and arrays, with a
 * number, a boolean and a null that pass through. */
const TOOL_RESULT = {
  tool: 'lookup_customer',
  result: {
    customer: { name: PII.person, contact: { email: PII.email } },
    accounts: [{ iban: PII.iban, balance: 1200, active: true }],
    credentials: [`AWS_ACCESS_KEY_ID=${PII.awsKey}`],
    tags: ['vip'],
    notes: null,
  },
};

/** The same email twice and the prompt's person, in a later turn. */
const REPEATED_VALUES = `${PII.person} wrote from ${PII.email}; reply to ${PII.email} before Friday.`;

/** Tools outside `DEFAULT_RESTORE_TOOLS`: a network tool and an MCP one. */
const HELD_TOOLS = ['WebFetch', 'mcp__crm__update_contact'] as const;
const OWNERS_FILE = '/repo/docs/OWNERS';
const NOTES_FILE = '/repo/docs/NOTES';
const OWNER_TBD = 'Owner: TBD';

/** A policy that leaves emails readable; `{}` is the default policy. */
const EMAIL_READABLE = { categories: { private_email: 'off' } };
const DEFAULT_POLICY = {};

/** `value` with every string leaf replaced by `'string'`: its keys, its
 * nesting and its other values, which masking must keep. */
function shapeOf(value: unknown): unknown {
  if (typeof value === 'string') return 'string';
  if (Array.isArray(value)) return value.map(shapeOf);
  if (value === null || typeof value !== 'object') return value;
  return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, shapeOf(v)]));
}

/** `captured` and `capturedByLabel` agree with each other and with the
 * placeholders the answer holds. */
function expectCountsConsistent(answer: SanitizeAnswer): void {
  expect(total(answer.capturedByLabel)).toBe(answer.captured);
  expect(placeholderLabels(JSON.stringify(answer.value))).toEqual(answer.capturedByLabel);
}

describe.skipIf(SKIP)('gateway e2e · sidecar on the real model', () => {
  let np: NullPii;
  let app: FastifyInstance;
  let policyDir: string;
  let policyFile: string;

  beforeAll(async () => {
    np = await startRealEngine();
    policyDir = mkdtempSync(join(tmpdir(), 'nullpii-gateway-e2e-'));
    policyFile = join(policyDir, POLICY_FILE_NAME);
    app = await buildServer({
      config: { ...E2E_CONFIG, sidecarToken: SIDECAR_TOKEN, policyFile },
      np,
    });
  }, WARMUP_TIMEOUT_MS);

  afterEach(() => {
    vi.restoreAllMocks();
  });

  afterAll(async () => {
    // The server first: closing it destroys its sessions in the engine.
    if (app !== undefined) await app.close();
    if (np !== undefined) await np.dispose();
    if (policyDir !== undefined) rmSync(policyDir, { recursive: true, force: true });
  });

  /** Sanitize a string in `session`; its masked text. */
  async function maskText(session: SidecarSession, text: string): Promise<string> {
    const { value } = await maskIn(app, session, text);
    if (typeof value !== 'string') throw new Error('a masked string came back as another type');
    return value;
  }

  describe('sessions', () => {
    it(
      'reports the real engine and the default policy in its status',
      async () => {
        const res = await app.inject({
          method: 'GET',
          url: '/v1/sidecar/status',
          headers: bearerOnly(),
        });
        expect(res.statusCode).toBe(OK);
        expect(res.json()).toMatchObject({
          status: 'ok',
          backend: 'cpu',
          // A model directory of the caller's own: no pinned revision.
          model: { revision: null, filesPinned: false },
          policy: {
            version: expect.stringMatching(POLICY_VERSION_PATTERN),
            restoreTools: [...DEFAULT_RESTORE_TOOLS],
          },
        });
      },
      TEST_TIMEOUT_MS,
    );

    it(
      'creates a session with its secret, keeps it from a wrong secret, and deletes it',
      async () => {
        const session = await openSession(app);
        expect(session.secret).toMatch(SECRET_PATTERN);
        const masked = await maskText(session, PROMPT);

        const intruder: SidecarSession = { key: session.key, secret: 'x'.repeat(SECRET_LENGTH) };
        const refused = [
          await sanitizeIn(app, intruder, PROMPT),
          await restoreIn(app, intruder, { value: masked }),
          await app.inject({
            method: 'DELETE',
            url: sessionPath(session.key),
            headers: sessionHeaders(intruder),
          }),
        ];
        for (const res of refused) {
          expect(res.statusCode).toBe(FORBIDDEN);
          expect(res.json()).toEqual({ error: 'bad_session_secret' });
        }
        expect((await unmaskIn(app, session, { value: masked })).value).toBe(PROMPT);

        const deleted = await app.inject({
          method: 'DELETE',
          url: sessionPath(session.key),
          headers: sessionHeaders(session),
        });
        expect(deleted.statusCode).toBe(NO_CONTENT);
        const gone = await restoreIn(app, session, { value: masked });
        expect(gone.statusCode).toBe(NOT_FOUND);
        expect(gone.json()).toEqual({ error: 'session_not_found' });
      },
      TEST_TIMEOUT_MS,
    );
  });

  describe('sanitize', () => {
    it(
      'masks a prompt: no value is left, the counts match its placeholders, and it restores',
      async () => {
        const session = await openSession(app);
        const res = await sanitizeIn(app, session, PROMPT);
        expect(res.statusCode).toBe(OK);
        expect(res.headers[CACHE_HEADER]).toBe('miss');
        expect(leaked(res.body)).toEqual([]);

        const answer = res.json<SanitizeAnswer>();
        expectCountsConsistent(answer);
        expect(answer.capturedByLabel.private_email).toBeGreaterThanOrEqual(1);
        expect(answer.modelUnscannedWords).toBe(0);
        expect((await unmaskIn(app, session, { value: answer.value })).value).toBe(PROMPT);
      },
      TEST_TIMEOUT_MS,
    );

    it(
      'masks a JSON tool result at every depth, keeping its keys and non-string values',
      async () => {
        const session = await openSession(app);
        const answer = await maskIn(app, session, TOOL_RESULT);
        expect(leaked(JSON.stringify(answer.value))).toEqual([]);
        expect(shapeOf(answer.value)).toEqual(shapeOf(TOOL_RESULT));
        expectCountsConsistent(answer);
        expect(Object.keys(answer.capturedByLabel)).toEqual(
          expect.arrayContaining(['private_email', 'account_number', 'secret']),
        );

        const back = await unmaskIn(app, session, { value: answer.value });
        expect(back.value).toEqual(TOOL_RESULT);
        expect(back.replacements).toBe(answer.captured);
      },
      TEST_TIMEOUT_MS,
    );

    it(
      'answers the same sanitize again from the cache, byte for byte, without the model',
      async () => {
        const session = await openSession(app);
        const model = vi.spyOn(np, 'sanitize');
        const first = await sanitizeIn(app, session, TOOL_RESULT);
        const callsForFirst = model.mock.calls.length;
        const second = await sanitizeIn(app, session, TOOL_RESULT);

        expect(callsForFirst).toBeGreaterThan(0);
        expect(first.headers[CACHE_HEADER]).toBe('miss');
        expect(second.headers[CACHE_HEADER]).toBe('hit');
        expect(second.body).toBe(first.body);
        expect(model.mock.calls.length).toBe(callsForFirst);
      },
      TEST_TIMEOUT_MS,
    );

    it(
      'gives a value one placeholder across the calls of a session, and another in another session',
      async () => {
        const session = await openSession(app);
        const prompt = await maskText(session, PROMPT);
        const later = await maskText(session, REPEATED_VALUES);
        expect(leaked(later)).toEqual([]);
        const email = await placeholderOf(app, session, prompt, PII.email);
        const person = await placeholderOf(app, session, prompt, PII.person);
        expect(placeholdersIn(later).filter((p) => p === email)).toHaveLength(2);
        expect(placeholdersIn(later)).toContain(person);

        const other = await openSession(app);
        const elsewhere = await maskText(other, PROMPT);
        expect(await placeholderOf(app, other, elsewhere, PII.email)).not.toBe(email);
      },
      TEST_TIMEOUT_MS,
    );
  });

  describe('restore into a tool', () => {
    interface MaskedPrompt {
      readonly session: SidecarSession;
      readonly person: string;
      readonly email: string;
    }

    /** A session that masked the prompt, and the placeholders of its
     * person and its email, as a model would write them in a tool call. */
    async function maskedPrompt(): Promise<MaskedPrompt> {
      const session = await openSession(app);
      const masked = await maskText(session, PROMPT);
      return {
        session,
        person: await placeholderOf(app, session, masked, PII.person),
        email: await placeholderOf(app, session, masked, PII.email),
      };
    }

    it(
      'puts the real values back into an Edit call',
      async () => {
        const { session, person, email } = await maskedPrompt();
        const value = {
          file_path: OWNERS_FILE,
          old_string: OWNER_TBD,
          new_string: `Owner: ${person} <${email}>`,
        };
        const back = await unmaskIn(app, session, { value, tool: 'Edit' });
        expect(back.value).toEqual({ ...value, new_string: `Owner: ${PII.person} <${PII.email}>` });
        expect(back.replacements).toBe(2);
        expect(back.unknownPlaceholders + back.foreignPlaceholders).toBe(0);
        expect(back).not.toHaveProperty('heldForTool');
        expect(back).not.toHaveProperty('shellKeptMasked');
      },
      TEST_TIMEOUT_MS,
    );

    it(
      'restores only the named fields of an Edit call, the others keep their placeholders',
      async () => {
        const { session, person, email } = await maskedPrompt();
        const value = {
          file_path: OWNERS_FILE,
          old_string: `Owner: ${person}`,
          new_string: `Owner: ${person} <${email}>`,
        };
        const back = await unmaskIn(app, session, { value, tool: 'Edit', fields: ['new_string'] });
        expect(back.value).toEqual({ ...value, new_string: `Owner: ${PII.person} <${PII.email}>` });
        expect(back.replacements).toBe(2);
      },
      TEST_TIMEOUT_MS,
    );

    it.each(HELD_TOOLS)(
      'puts nothing back into %s, a tool outside restoreTools, and counts what it held',
      async (tool) => {
        const { session, person, email } = await maskedPrompt();
        const value = { url: `https://crm.example/search?q=${email}`, prompt: `Who is ${person}?` };
        const res = await restoreIn(app, session, { value, tool });
        expect(res.statusCode).toBe(OK);
        expect(leaked(res.body)).toEqual([]);
        expect(res.json()).toEqual({
          value,
          replacements: 0,
          replacementsByLabel: {},
          unknownPlaceholders: 0,
          foreignPlaceholders: 0,
          heldForTool: 2,
        });
      },
      TEST_TIMEOUT_MS,
    );

    it(
      'keeps every placeholder of a Bash call masked and lists them',
      async () => {
        const { session, person, email } = await maskedPrompt();
        const value = {
          command: `printf '%s\\n' '${person} <${email}>' >> owners.txt`,
          description: `Record ${person} as the owner`,
        };
        const res = await restoreIn(app, session, { value, tool: 'Bash' });
        expect(res.statusCode).toBe(OK);
        expect(leaked(res.body)).toEqual([]);
        const back = res.json<RestoreAnswer>();
        expect(back.value).toEqual(value);
        expect(back.replacements).toBe(0);
        expect([...(back.shellKeptMasked ?? [])].sort()).toEqual([person, email].sort());
      },
      TEST_TIMEOUT_MS,
    );

    it(
      'leaves unknown and foreign placeholders literal next to a restored one',
      async () => {
        const { session, person, email } = await maskedPrompt();
        const other = await openSession(app);
        const otherPrompt = await maskText(other, PROMPT);
        const foreign = await placeholderOf(app, other, otherPrompt, PII.email);
        const unknown = PLACEHOLDER_TEMPLATE(
          'private_person',
          UNMINTED_INDEX,
          sessionPrefixOf(person),
        );
        const value = { file_path: NOTES_FILE, content: `${email} | ${foreign} | ${unknown}` };

        const back = await unmaskIn(app, session, { value, tool: 'Write' });
        expect(back.value).toEqual({
          file_path: NOTES_FILE,
          content: `${PII.email} | ${foreign} | ${unknown}`,
        });
        expect(back).toMatchObject({
          replacements: 1,
          unknownPlaceholders: 1,
          foreignPlaceholders: 1,
        });
      },
      TEST_TIMEOUT_MS,
    );
  });

  describe('policy', () => {
    afterEach(async () => {
      // The engine is shared by every test of this file: put its default
      // policy back.
      expect((await putPolicy(app, DEFAULT_POLICY)).statusCode).toBe(OK);
    });

    /** Turn emails off on top of `seen`; the policy now in effect. */
    async function turnEmailOff(seen: string): Promise<PolicyView> {
      const put = await putPolicy(app, EMAIL_READABLE, seen);
      expect(put.statusCode).toBe(OK);
      return put.json<{ policy: PolicyView }>().policy;
    }

    it(
      'turning a category off leaves its value readable on the next sanitize',
      async () => {
        const before = (await policyNow(app)).version;
        const earlier = await openSession(app);
        const masked = await sanitizeIn(app, earlier, PROMPT, before);
        expect(masked.statusCode).toBe(OK);
        expect(leaked(masked.body)).toEqual([]);

        const policy = await turnEmailOff(before);
        expect(policy.version).not.toBe(before);
        expect(policy.disabledCategories).toContain('private_email');
        expect(JSON.parse(readFileSync(policyFile, 'utf8'))).toEqual(EMAIL_READABLE);

        // A session that never masked the email: one that did keeps it
        // masked (the next test).
        const session = await openSession(app);
        const readable = await sanitizeIn(app, session, PROMPT, policy.version);
        expect(readable.statusCode).toBe(OK);
        expect(leaked(readable.body), readable.body).toEqual([PII.email]);
        expect(readable.json<SanitizeAnswer>().capturedByLabel).not.toHaveProperty('private_email');
      },
      TEST_TIMEOUT_MS,
    );

    // The vault masks again every value an earlier call of the session
    // masked (README, "Once a session has masked a value…"), whatever the
    // policy says now: shown in clear later in the same conversation, the
    // value would sit beside its own placeholder, and Claude could read
    // every earlier mention of it.
    it(
      'keeps a value the session masked before its category was turned off masked in that session',
      async () => {
        const before = (await policyNow(app)).version;
        const session = await openSession(app);
        expect((await sanitizeIn(app, session, PROMPT, before)).statusCode).toBe(OK);
        const policy = await turnEmailOff(before);

        const after = await sanitizeIn(app, session, PROMPT, policy.version);
        expect(after.statusCode).toBe(OK);
        expect(leaked(after.body), after.body).toEqual([]);
      },
      TEST_TIMEOUT_MS,
    );

    // #92: a category turned off stays in the model's prompt, so the model
    // does not file its values under the nearest label still prompted
    // (before the fix, an email with its category off was masked as
    // `private_person` in 6 of 8 contexts).
    it(
      'turning email off leaves an email readable wherever it stands, not masked under another label',
      async () => {
        const policy = await turnEmailOff((await policyNow(app)).version);
        const session = await openSession(app);
        const value = {
          headers: `Reply-To: ${PII.email}`,
          note: `cc ${PII.email} on the thread`,
        };
        const res = await sanitizeIn(app, session, value, policy.version);
        expect(res.statusCode).toBe(OK);
        const answer = res.json<SanitizeAnswer>();
        expect(answer.capturedByLabel, res.body).toEqual({});
        expect(answer.value).toEqual(value);
      },
      TEST_TIMEOUT_MS,
    );

    it(
      'refuses (412) a sanitize sent with a stale policy version, without running the model',
      async () => {
        const session = await openSession(app);
        const seen = (await policyNow(app)).version;
        expect((await putPolicy(app, EMAIL_READABLE)).statusCode).toBe(OK);
        const current = (await policyNow(app)).version;
        const model = vi.spyOn(np, 'sanitize');

        const res = await sanitizeIn(app, session, PROMPT, seen);
        expect(res.statusCode).toBe(POLICY_CHANGED);
        expect(res.json()).toEqual({ error: 'policy_changed', version: current });
        expect(model).not.toHaveBeenCalled();
      },
      TEST_TIMEOUT_MS,
    );
  });
});
