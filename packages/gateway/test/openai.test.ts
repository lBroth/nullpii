// SPDX-License-Identifier: Apache-2.0
//
// OpenAI Chat Completions route (`POST /v1/chat/completions`). The engine
// is mocked (a real PiiVault plus a detector that flags a fixed set of
// values) and so is the upstream `fetch`, so the suite checks the request
// walk, the JSON and SSE restore paths, error passthrough and the
// vault-session lifecycle without ONNX.

import type { FastifyInstance } from 'fastify';
import { LLM_PRESERVATION_HINT, type NullPii, type PiiSpan, PiiVault } from 'nullpii';

import { afterEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import { restoreChatResponse, sanitizeChatRequest } from '../src/openai-sanitizer.js';
import { relayChatSseStream } from '../src/openai-sse-relay.js';
import type {
  ChatCompletionRequest,
  ChatCompletionResponse,
  ChatMessage,
} from '../src/openai-types.js';
import { buildServer } from '../src/server.js';
import { BASE_TEST_CONFIG, TEST_RESTORE_TOOLS } from './fixtures.js';

const OPENAI_UPSTREAM = 'https://openai.test';
const CHAT_URL = '/v1/chat/completions';
const MODEL = 'gpt-test';

const TEST_CONFIG: GatewayConfig = {
  ...BASE_TEST_CONFIG,
  upstreamBaseUrl: 'https://anthropic.test',
  openaiUpstreamBaseUrl: OPENAI_UPSTREAM,
};

const PERSON = 'John';
const EMAIL = 'john@acme.io';
/** Holds quotes: pasted raw into a JSON string, it would break the JSON. */
const ADDRESS = 'Via "Roma" 1';
const CANARY = 'canary.person@example.com';
const PLACEHOLDER = /\{\{PII_[A-Z_]+_\d+_[0-9a-f]+\}\}/g;
const WHOLE_PLACEHOLDER = /^\{\{PII_[A-Z_]+_\d+_[0-9a-f]+\}\}$/;
const DONE_FRAME = 'data: [DONE]\n\n';

type SpanLabel = PiiSpan['label'];

const PATTERNS: ReadonlyArray<[RegExp, SpanLabel]> = [
  [/john@acme\.io/g, 'private_email'],
  [/canary\.person@example\.com/g, 'private_email'],
  [/\bJohn\b/g, 'private_person'],
  [/Via "Roma" 1/g, 'private_address'],
];

interface Engine {
  readonly np: NullPii;
  readonly sanitizeCalls: string[];
  readonly created: string[];
  readonly destroyed: string[];
}

function findSpans(text: string): PiiSpan[] {
  return PATTERNS.flatMap(([re, label]) =>
    [...text.matchAll(re)].map((m) => ({
      label,
      start: m.index ?? 0,
      end: (m.index ?? 0) + m[0].length,
      text: m[0],
      score: 1,
    })),
  );
}

/** Mock engine that records which vault sessions it opened and destroyed. */
function buildEngine(): Engine {
  const vault = new PiiVault();
  const sanitizeCalls: string[] = [];
  const created: string[] = [];
  const destroyed: string[] = [];
  const mock = {
    async sanitize(text: string, sessionId?: string) {
      sanitizeCalls.push(text);
      const id = sessionId ?? vault.createSession();
      const spans = findSpans(text);
      const r = vault.sanitize(text, spans, id);
      return { sessionId: id, sanitized: r.sanitized, spans };
    },
    restore: (text: string, sessionId: string) => vault.restore(text, sessionId),
    createSession() {
      const id = vault.createSession();
      created.push(id);
      return id;
    },
    destroySession(sessionId: string) {
      destroyed.push(sessionId);
      vault.destroySession(sessionId);
    },
  };
  return { np: mock as unknown as NullPii, sanitizeCalls, created, destroyed };
}

interface FetchCall {
  readonly url: string;
  readonly init: RequestInit;
}

function json(body: unknown, status = 200, headers: Record<string, string> = {}): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json', ...headers },
  });
}

function sse(frames: string[]): Response {
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (const f of frames) controller.enqueue(encoder.encode(f));
      controller.close();
    },
  });
  return new Response(body, { status: 200, headers: { 'content-type': 'text/event-stream' } });
}

function completion(message: ChatMessage): ChatCompletionResponse {
  return {
    id: 'chatcmpl-1',
    object: 'chat.completion',
    created: 0,
    model: MODEL,
    choices: [{ index: 0, message, finish_reason: 'stop' }],
  };
}

function chunkFrame(choices: unknown[], extra: Record<string, unknown> = {}): string {
  const chunk = {
    id: 'chatcmpl-1',
    object: 'chat.completion.chunk',
    created: 0,
    model: MODEL,
    choices,
    ...extra,
  };
  return `data: ${JSON.stringify(chunk)}\n\n`;
}

function forwarded(call: FetchCall | undefined): ChatCompletionRequest {
  if (call === undefined) throw new Error('expected an upstream call');
  return JSON.parse(call.init.body as string) as ChatCompletionRequest;
}

function rawBody(call: FetchCall | undefined): string {
  if (call === undefined) throw new Error('expected an upstream call');
  return call.init.body as string;
}

function placeholders(text: unknown): string[] {
  return typeof text === 'string' ? (text.match(PLACEHOLDER) ?? []) : [];
}

const apps: FastifyInstance[] = [];
afterEach(async () => {
  await Promise.all(apps.map((a) => a.close()));
  apps.length = 0;
});

async function setup(respond: (call: FetchCall) => Response) {
  const engine = buildEngine();
  const calls: FetchCall[] = [];
  const fetchImpl = async (url: string, init: RequestInit): Promise<Response> => {
    const call = { url, init };
    calls.push(call);
    return respond(call);
  };
  const app = await buildServer({ config: TEST_CONFIG, np: engine.np, fetchImpl });
  apps.push(app);
  return { app, calls, engine };
}

function post(
  app: FastifyInstance,
  payload: Record<string, unknown>,
  headers: Record<string, string> = {},
) {
  return app.inject({
    method: 'POST',
    url: CHAT_URL,
    headers: { 'content-type': 'application/json', ...headers },
    payload,
  });
}

interface StreamedChoice {
  index: number;
  delta?: {
    content?: string | null;
    tool_calls?: Array<{ index: number; function?: { name?: string; arguments?: string } }>;
  };
}

interface Reassembled {
  readonly content: Map<number, string>;
  /** Keyed `${choiceIndex}:${toolCallIndex}`. */
  readonly args: Map<string, string>;
  readonly names: Map<string, string>;
}

function addChoice(out: Reassembled, choice: StreamedChoice): void {
  const delta = choice.delta ?? {};
  if (typeof delta.content === 'string') {
    out.content.set(choice.index, (out.content.get(choice.index) ?? '') + delta.content);
  }
  for (const call of delta.tool_calls ?? []) {
    const key = `${choice.index}:${call.index}`;
    if (call.function?.name !== undefined) out.names.set(key, call.function.name);
    out.args.set(key, (out.args.get(key) ?? '') + (call.function?.arguments ?? ''));
  }
}

/** Accumulate a relayed stream the way the OpenAI SDKs do. */
function reassemble(body: string): Reassembled {
  const out: Reassembled = { content: new Map(), args: new Map(), names: new Map() };
  for (const frame of body.split('\n\n')) {
    if (!frame.startsWith('data: ') || frame === 'data: [DONE]') continue;
    const chunk = JSON.parse(frame.slice('data: '.length)) as { choices: StreamedChoice[] };
    for (const choice of chunk.choices) addChoice(out, choice);
  }
  return out;
}

describe('openai · request walk', () => {
  it('sanitizes string content, forwards the OpenAI auth headers, restores the reply', async () => {
    const { app, calls } = await setup((call) => {
      const [ph] = placeholders(forwarded(call).messages[0]?.content);
      return json(completion({ role: 'assistant', content: `Hello ${ph}` }));
    });

    const res = await post(
      app,
      { model: MODEL, messages: [{ role: 'user', content: `Hi ${PERSON}` }] },
      { authorization: 'Bearer sk-test', 'openai-organization': 'org-1', 'x-api-key': 'sk-ant' },
    );

    expect(res.statusCode).toBe(200);
    const body = res.json() as ChatCompletionResponse;
    expect(body.choices[0]?.message?.content).toBe(`Hello ${PERSON}`);
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toBe(`${OPENAI_UPSTREAM}/v1/chat/completions`);
    expect(rawBody(calls[0])).not.toContain(PERSON);
    expect(rawBody(calls[0])).toContain('{{PII_PRIVATE_PERSON_');
    const headers = calls[0]?.init.headers as Record<string, string>;
    expect(headers.authorization).toBe('Bearer sk-test');
    expect(headers['openai-organization']).toBe('org-1');
    // Anthropic-only headers are not part of the OpenAI allowlist.
    expect(headers['x-api-key']).toBeUndefined();
  });

  it('scans text parts and forwards image parts untouched', async () => {
    const { app, calls } = await setup(() =>
      json(completion({ role: 'assistant', content: 'ok' })),
    );
    const image = {
      type: 'image_url',
      image_url: { url: 'data:image/png;base64,iVBORw0KGgo=', detail: 'low' },
    };

    const res = await post(app, {
      model: MODEL,
      messages: [{ role: 'user', content: [{ type: 'text', text: `Who is ${PERSON}?` }, image] }],
    });

    expect(res.statusCode).toBe(200);
    const parts = forwarded(calls[0]).messages[0]?.content as Array<Record<string, unknown>>;
    expect(parts[0]?.text).not.toContain(PERSON);
    expect(parts[0]?.text).toContain('{{PII_PRIVATE_PERSON_');
    expect(parts[1]).toEqual(image);
  });

  it('counts image, audio and file parts as unscanned and forwards them as they are', async () => {
    const { np } = buildEngine();
    const media = [
      { type: 'image_url', image_url: { url: 'https://img.example/a.png' } },
      { type: 'input_audio', input_audio: { data: 'UklGRiQAAABXQVZF', format: 'wav' } },
      { type: 'file', file: { file_id: 'file-abc123' } },
    ];
    const body: ChatCompletionRequest = {
      model: MODEL,
      messages: [{ role: 'user', content: [...media, { type: 'text', text: 'Describe these.' }] }],
    };

    const out = await sanitizeChatRequest(np, body, np.createSession());

    expect(out.unscanned).toBe(3);
    expect(out.captured).toBe(0);
    expect((out.body.messages[0]?.content as unknown[]).slice(0, 3)).toEqual(media);
  });

  it("scans a file part's filename and forwards the file data untouched", async () => {
    const { np } = buildEngine();
    const fileData = 'data:application/pdf;base64,JVBERi0xLjQK';
    const body: ChatCompletionRequest = {
      model: MODEL,
      messages: [
        {
          role: 'user',
          content: [
            { type: 'file', file: { filename: `CV of ${PERSON}.pdf`, file_data: fileData } },
          ],
        },
      ],
    };

    const out = await sanitizeChatRequest(np, body, np.createSession());

    const part = (
      out.body.messages[0]?.content as unknown as Array<{ file: Record<string, string> }>
    )[0];
    expect(part?.file.filename).toMatch(/^CV of \{\{PII_PRIVATE_PERSON_\d+_[0-9a-f]+\}\}\.pdf$/);
    expect(part?.file.file_data).toBe(fileData);
    // The file's content still cannot be read.
    expect(out.unscanned).toBe(1);
    expect(out.captured).toBe(1);
  });

  it('sanitizes tool_calls arguments as JSON and keeps call ids and function names', async () => {
    const { app, calls } = await setup(() =>
      json(completion({ role: 'assistant', content: 'ok' })),
    );
    const exactArgs = '{"city": "Rome"}';

    const res = await post(app, {
      model: MODEL,
      messages: [
        { role: 'user', content: 'Email the customer.' },
        {
          role: 'assistant',
          content: null,
          tool_calls: [
            {
              id: 'call_1',
              type: 'function',
              function: {
                name: 'send_email',
                arguments: JSON.stringify({ to: EMAIL, name: PERSON, address: ADDRESS }),
              },
            },
            {
              id: 'call_2',
              type: 'function',
              function: { name: 'note', arguments: `x ${PERSON}` },
            },
            { id: 'call_3', type: 'function', function: { name: 'weather', arguments: exactArgs } },
          ],
        },
        { role: 'tool', tool_call_id: 'call_1', content: 'sent' },
      ],
    });

    expect(res.statusCode).toBe(200);
    const [sent, note, weather] = forwarded(calls[0]).messages[1]?.tool_calls ?? [];
    expect(sent?.id).toBe('call_1');
    expect(sent?.function?.name).toBe('send_email');
    const args = JSON.parse(sent?.function?.arguments ?? '') as Record<string, string>;
    expect(Object.keys(args)).toEqual(['to', 'name', 'address']);
    for (const value of Object.values(args)) expect(value).toMatch(WHOLE_PLACEHOLDER);
    // Not JSON: sanitized as plain text.
    expect(note?.function?.arguments).toMatch(/^x \{\{PII_PRIVATE_PERSON_/);
    // Nothing masked: the client's exact string, whitespace included.
    expect(weather?.function?.arguments).toBe(exactArgs);
    for (const value of [EMAIL, PERSON, 'Roma']) expect(rawBody(calls[0])).not.toContain(value);
  });

  it('sanitizes tool results, participant names and tool descriptions, keeps the structure', async () => {
    const { app, calls } = await setup(() =>
      json(completion({ role: 'assistant', content: 'ok' })),
    );
    const parameters = { type: 'object', properties: { email: { type: 'string' } } };

    const res = await post(app, {
      model: MODEL,
      tools: [
        {
          type: 'function',
          function: { name: 'lookup_user', description: `Find ${PERSON} in the CRM`, parameters },
        },
      ],
      messages: [
        { role: 'user', name: PERSON, content: 'Look me up.' },
        {
          role: 'assistant',
          content: null,
          tool_calls: [
            { id: 'call_7', type: 'function', function: { name: 'lookup_user', arguments: '{}' } },
          ],
        },
        { role: 'tool', tool_call_id: 'call_7', content: `Found ${EMAIL}` },
      ],
    });

    expect(res.statusCode).toBe(200);
    const fwd = forwarded(calls[0]);
    expect(fwd.messages[0]?.role).toBe('user');
    expect(fwd.messages[0]?.name).toMatch(WHOLE_PLACEHOLDER);
    expect(fwd.messages[2]).toMatchObject({ role: 'tool', tool_call_id: 'call_7' });
    expect(fwd.messages[2]?.content).not.toContain(EMAIL);
    expect(fwd.messages[2]?.content).toContain('{{PII_PRIVATE_EMAIL_');
    const tool = fwd.tools?.[0]?.function;
    expect(tool?.name).toBe('lookup_user');
    expect(tool?.description).not.toContain(PERSON);
    expect(tool?.description).toContain('{{PII_PRIVATE_PERSON_');
    expect(tool?.parameters).toEqual(parameters);
  });

  it('appends the preservation hint as the last system message only when something was masked', async () => {
    const { app, calls, engine } = await setup(() =>
      json(completion({ role: 'assistant', content: 'ok' })),
    );
    const clean = [
      { role: 'system', content: 'Be brief.' },
      { role: 'user', content: 'Hi there' },
    ];

    await post(app, { model: MODEL, messages: clean });
    await post(app, {
      model: MODEL,
      messages: [...clean, { role: 'user', content: `I am ${PERSON}` }],
    });

    // No PII: forwarded exactly as sent, so the upstream prompt cache is unaffected.
    expect(forwarded(calls[0]).messages).toEqual(clean);
    const masked = forwarded(calls[1]).messages;
    expect(masked).toHaveLength(4);
    // Appended, never prepended: the original prefix is untouched.
    expect(masked.slice(0, 2)).toEqual(clean);
    expect(masked[3]).toEqual({ role: 'system', content: LLM_PRESERVATION_HINT });
    // Added after sanitization: the hint text itself is never scanned.
    expect(engine.sanitizeCalls).not.toContain(LLM_PRESERVATION_HINT);
  });

  it('lets no original value reach the upstream: canary in every scanned field', async () => {
    const { app, calls } = await setup(() =>
      json(completion({ role: 'assistant', content: 'ok' })),
    );
    const text = (value: string) => ({ type: 'text', text: value });

    const res = await post(app, {
      model: MODEL,
      messages: [
        { role: 'system', content: `Account owner: ${CANARY}` },
        { role: 'developer', content: [text(`Escalate to ${CANARY}`)] },
        { role: 'user', name: CANARY, content: [text(`I am ${CANARY}`)] },
        {
          role: 'assistant',
          content: [{ type: 'refusal', refusal: `Cannot email ${CANARY}` }],
          refusal: `Cannot email ${CANARY}`,
          tool_calls: [
            {
              id: 'call_1',
              type: 'function',
              function: { name: 'send', arguments: JSON.stringify({ to: [CANARY] }) },
            },
            { id: 'call_2', type: 'custom', custom: { name: 'shell', input: `mail ${CANARY}` } },
          ],
          function_call: { name: 'send', arguments: JSON.stringify({ to: CANARY }) },
        },
        { role: 'tool', tool_call_id: 'call_1', content: [text(`Delivered to ${CANARY}`)] },
        { role: 'function', name: 'lookup', content: `Owner ${CANARY}` },
      ],
      tools: [
        { type: 'function', function: { name: 'send', description: `Mail ${CANARY}` } },
        { type: 'custom', custom: { name: 'shell', description: `Runs as ${CANARY}` } },
      ],
      functions: [{ name: 'lookup', description: `Look up ${CANARY}` }],
      prediction: { type: 'content', content: `Dear ${CANARY},` },
    });

    expect(res.statusCode).toBe(200);
    expect(rawBody(calls[0])).not.toContain(CANARY);
    // The deprecated `function` role keeps its function name.
    expect(forwarded(calls[0]).messages[5]?.name).toBe('lookup');
  });

  it('rejects a body without a messages array before opening a session or calling upstream', async () => {
    const { app, calls, engine } = await setup(() => json(completion({ role: 'assistant' })));

    const res = await post(app, { model: MODEL, prompt: `Hi ${PERSON}` });

    expect(res.statusCode).toBe(400);
    expect(res.json()).toMatchObject({ error: { type: 'invalid_request_error' } });
    expect(calls).toHaveLength(0);
    expect(engine.created).toHaveLength(0);
  });
});

describe('openai · response restore', () => {
  it('restores content and tool-call arguments in a JSON response, keeping the JSON valid', async () => {
    const { app, engine } = await setup((call) => {
      const [email, address] = placeholders(forwarded(call).messages[0]?.content);
      return json(
        completion({
          role: 'assistant',
          content: `Writing to ${email}`,
          tool_calls: [
            {
              id: 'call_9',
              type: 'function',
              function: { name: 'send', arguments: JSON.stringify({ to: email, address }) },
            },
          ],
        }),
      );
    });

    const res = await post(app, {
      model: MODEL,
      messages: [{ role: 'user', content: `Mail ${EMAIL} at ${ADDRESS}` }],
    });

    expect(res.statusCode).toBe(200);
    const message = (res.json() as ChatCompletionResponse).choices[0]?.message;
    expect(message?.content).toBe(`Writing to ${EMAIL}`);
    const call = message?.tool_calls?.[0];
    expect(call?.id).toBe('call_9');
    expect(call?.function?.name).toBe('send');
    // The address holds quotes: restored inside the parsed JSON, re-escaped.
    expect(JSON.parse(call?.function?.arguments ?? '')).toEqual({ to: EMAIL, address: ADDRESS });
    expect(res.body).not.toContain('{{PII_');
    expect(engine.destroyed).toEqual(engine.created);
  });

  it('restores refusal, custom tool input and the deprecated function_call', async () => {
    const engine = buildEngine();
    const sessionId = engine.np.createSession();
    const sanitized = await sanitizeChatRequest(
      engine.np,
      { model: MODEL, messages: [{ role: 'user', content: `${PERSON} ${EMAIL}` }] },
      sessionId,
    );
    const [person, email] = placeholders(sanitized.body.messages[0]?.content);

    const restored = restoreChatResponse(
      engine.np,
      completion({
        role: 'assistant',
        content: null,
        refusal: `I will not contact ${person}`,
        tool_calls: [
          { id: 'call_1', type: 'custom', custom: { name: 'shell', input: `mail ${email}` } },
        ],
        function_call: { name: 'send', arguments: JSON.stringify({ to: email }) },
      }),
      sessionId,

      TEST_RESTORE_TOOLS,
    );

    const message = restored.body.choices[0]?.message;
    expect(message?.refusal).toBe(`I will not contact ${PERSON}`);
    expect(message?.tool_calls?.[0]?.custom?.input).toBe(`mail ${EMAIL}`);
    expect(JSON.parse(message?.function_call?.arguments ?? '')).toEqual({ to: EMAIL });
    expect(restored.replacements).toBe(3);
  });

  it('streams: restores placeholders split across content chunks and tool-call argument deltas', async () => {
    const { app, engine } = await setup((call) => {
      const [email, address] = placeholders(forwarded(call).messages[0]?.content);
      if (email === undefined) throw new Error('expected a placeholder');
      const args = JSON.stringify({ to: email, address });
      const cut = args.indexOf(email) + 10; // inside the email placeholder
      return sse([
        chunkFrame([{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null }]),
        chunkFrame([{ index: 0, delta: { content: `Writing to ${email.slice(0, 12)}` } }]),
        chunkFrame([{ index: 0, delta: { content: `${email.slice(12)}.` } }]),
        chunkFrame([
          {
            index: 0,
            delta: {
              tool_calls: [
                {
                  index: 0,
                  id: 'call_1',
                  type: 'function',
                  function: { name: 'send', arguments: '' },
                },
              ],
            },
          },
        ]),
        chunkFrame([
          {
            index: 0,
            delta: { tool_calls: [{ index: 0, function: { arguments: args.slice(0, cut) } }] },
          },
        ]),
        chunkFrame([
          {
            index: 0,
            delta: { tool_calls: [{ index: 0, function: { arguments: args.slice(cut) } }] },
          },
        ]),
        chunkFrame([{ index: 0, delta: {}, finish_reason: 'tool_calls' }]),
        DONE_FRAME,
      ]);
    });

    const res = await post(app, {
      model: MODEL,
      stream: true,
      messages: [{ role: 'user', content: `Mail ${EMAIL} at ${ADDRESS}` }],
    });

    expect(res.statusCode).toBe(200);
    expect(res.headers['content-type']).toContain('text/event-stream');
    expect(res.body).not.toContain('{{PII_');
    const out = reassemble(res.body);
    expect(out.content.get(0)).toBe(`Writing to ${EMAIL}.`);
    expect(out.names.get('0:0')).toBe('send');
    expect(JSON.parse(out.args.get('0:0') ?? '')).toEqual({ to: EMAIL, address: ADDRESS });
    expect(res.body.endsWith(DONE_FRAME)).toBe(true);
    // The session outlived the stream it restored, then was dropped.
    expect(engine.created).toHaveLength(1);
    expect(engine.destroyed).toEqual(engine.created);
  });
});

describe('openai · SSE relay', () => {
  function harness() {
    const vault = new PiiVault();
    const sessionId = vault.createSession();
    const np = { restore: (t: string, s: string) => vault.restore(t, s) } as unknown as NullPii;
    const bake = (value: string, label: SpanLabel): string =>
      vault.sanitize(
        value,
        [{ label, start: 0, end: value.length, text: value, score: 1 }],
        sessionId,
      ).sanitized;
    return { np, sessionId, bake };
  }

  async function* stream(chunks: string[]): AsyncIterable<Uint8Array> {
    const encoder = new TextEncoder();
    for (const c of chunks) yield encoder.encode(c);
  }

  async function relay(np: NullPii, sessionId: string, chunks: string[]) {
    const frames: string[] = [];
    const counters = await relayChatSseStream({
      restoreTools: TEST_RESTORE_TOOLS,
      np,
      sessionId,
      upstream: stream(chunks),
      write: (f) => frames.push(f),
    });
    return { body: frames.join(''), counters };
  }

  it('survives byte-by-byte upstream fragmentation', async () => {
    const { np, sessionId, bake } = harness();
    const ph = bake(PERSON, 'private_person');
    const full = [
      chunkFrame([{ index: 0, delta: { content: `Hi ${ph} there` } }]),
      chunkFrame([{ index: 0, delta: {}, finish_reason: 'stop' }]),
      DONE_FRAME,
    ].join('');

    const { body, counters } = await relay(np, sessionId, Array.from(full));

    expect(reassemble(body).content.get(0)).toBe(`Hi ${PERSON} there`);
    expect(body).not.toContain('{{PII_');
    expect(counters.replacements).toBe(1);
    expect(counters.replacementsByLabel.private_person).toBe(1);
  });

  it('keeps choices independent when n > 1 interleaves them', async () => {
    const { np, sessionId, bake } = harness();
    const a = bake(PERSON, 'private_person');
    const b = bake(EMAIL, 'private_email');

    const { body } = await relay(np, sessionId, [
      chunkFrame([{ index: 0, delta: { content: `A:${a.slice(0, 7)}` } }]),
      chunkFrame([{ index: 1, delta: { content: `B:${b.slice(0, 9)}` } }]),
      chunkFrame([{ index: 0, delta: { content: `${a.slice(7)} end` } }]),
      chunkFrame([{ index: 1, delta: { content: `${b.slice(9)} end` } }]),
      chunkFrame([
        { index: 0, delta: {}, finish_reason: 'stop' },
        { index: 1, delta: {}, finish_reason: 'stop' },
      ]),
      DONE_FRAME,
    ]);

    const out = reassemble(body);
    expect(out.content.get(0)).toBe(`A:${PERSON} end`);
    expect(out.content.get(1)).toBe(`B:${EMAIL} end`);
  });

  it('flushes held arguments in a synthesised chunk before [DONE] when no finish_reason arrives', async () => {
    const { np, sessionId, bake } = harness();
    const ph = bake(EMAIL, 'private_email');
    const start = { index: 0, id: 'call_1', type: 'function', function: { name: 'send' } };

    const { body } = await relay(np, sessionId, [
      chunkFrame([{ index: 0, delta: { tool_calls: [start] } }]),
      chunkFrame([
        {
          index: 0,
          delta: { tool_calls: [{ index: 0, function: { arguments: `{"to":"${ph}"}` } }] },
        },
      ]),
      DONE_FRAME,
    ]);

    expect(body).not.toContain('{{PII_');
    expect(JSON.parse(reassemble(body).args.get('0:0') ?? '')).toEqual({ to: EMAIL });
    expect(body.endsWith(DONE_FRAME)).toBe(true);
    // The synthesised chunk carries the stream's envelope.
    const frames = body.split('\n\n').filter((f) => f.length > 0);
    expect(frames.at(-2)).toContain('"id":"chatcmpl-1"');
    expect(frames.at(-2)).toContain('"object":"chat.completion.chunk"');
  });

  it('forwards chunks it does not change byte for byte', async () => {
    const { np, sessionId } = harness();
    const frames = [
      ': keep-alive\n\n',
      chunkFrame([{ index: 0, delta: { role: 'assistant', content: '' }, finish_reason: null }]),
      chunkFrame([{ index: 0, delta: { content: 'Plain reply.' }, logprobs: null }]),
      chunkFrame([{ index: 0, delta: {}, finish_reason: 'stop' }]),
      chunkFrame([], { usage: { prompt_tokens: 3, completion_tokens: 2, total_tokens: 5 } }),
      `data: ${JSON.stringify({ error: { message: 'late failure', type: 'server_error' } })}\n\n`,
      DONE_FRAME,
    ];

    const { body } = await relay(np, sessionId, frames);

    expect(body).toBe(frames.join(''));
  });
});

describe('openai · upstream errors and session lifecycle', () => {
  it.each([false, true])(
    'passes a 4xx through verbatim with its retry headers (stream: %s)',
    async (stream) => {
      const upstreamBody = JSON.stringify({
        error: { message: 'Rate limit reached', type: 'requests', code: 'rate_limit_exceeded' },
      });
      const { app, engine } = await setup(
        () =>
          new Response(upstreamBody, {
            status: 429,
            headers: {
              'content-type': 'application/json',
              'retry-after': '7',
              'x-ratelimit-remaining-requests': '0',
              'x-request-id': 'req_123',
              'set-cookie': 'upstream=1',
            },
          }),
      );

      const res = await post(app, {
        model: MODEL,
        stream,
        messages: [{ role: 'user', content: `Hi ${PERSON}` }],
      });

      expect(res.statusCode).toBe(429);
      expect(res.body).toBe(upstreamBody);
      expect(res.headers['retry-after']).toBe('7');
      expect(res.headers['x-ratelimit-remaining-requests']).toBe('0');
      expect(res.headers['x-request-id']).toBe('req_123');
      expect(res.headers['set-cookie']).toBeUndefined();
      expect(engine.destroyed).toEqual(engine.created);
    },
  );

  it.each([false, true])(
    'returns 502 with an OpenAI-style error and destroys the session when fetch fails (stream: %s)',
    async (stream) => {
      const { app, engine } = await setup(() => {
        throw new Error('ECONNREFUSED');
      });

      const res = await post(app, {
        model: MODEL,
        stream,
        messages: [{ role: 'user', content: `Hi ${PERSON}` }],
      });

      expect(res.statusCode).toBe(502);
      expect(res.json()).toEqual({
        error: { type: 'nullpii_upstream_error', message: 'ECONNREFUSED' },
      });
      expect(engine.created).toHaveLength(1);
      expect(engine.destroyed).toEqual(engine.created);
    },
  );

  it('returns 502 when the upstream answers 2xx with a body that is not JSON', async () => {
    const { app, engine } = await setup(
      () => new Response('<html>gateway</html>', { status: 200 }),
    );

    const res = await post(app, { model: MODEL, messages: [{ role: 'user', content: 'Hi' }] });

    expect(res.statusCode).toBe(502);
    expect(res.json()).toMatchObject({ error: { type: 'nullpii_upstream_error' } });
    expect(engine.destroyed).toEqual(engine.created);
  });
});
