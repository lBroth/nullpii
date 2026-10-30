// SPDX-License-Identifier: Apache-2.0
//
// The Anthropic Messages proxy (`POST /v1/messages`) on the real GLiNER
// model, in front of a fake upstream that records what it receives and
// echoes the placeholders back: the request must leave masked, and the
// reply must come back with the real values where the gateway's rules put
// them, as a JSON message and as an SSE stream whose placeholders arrive
// cut across deltas and network chunks. Gated like the core real-ONNX
// suite (see `helpers.ts`); skipped in the default unit run.

import type { FastifyInstance } from 'fastify';
import { LLM_PRESERVATION_HINT, type NullPii, PLACEHOLDER_TEMPLATE } from 'nullpii';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../../src/config.js';
import { buildServer } from '../../src/server.js';
import type {
  AnthropicContentBlock,
  AnthropicRequest,
  AnthropicResponse,
} from '../../src/types.js';
import {
  type FakeUpstream,
  type StreamEvent,
  type UpstreamCall,
  fakeUpstream,
  jsonAnswer,
  onlyCall,
  sseAnswer,
  sseEvents,
  sseFrame,
} from './fake-upstream.js';
import {
  ALL_PII,
  E2E_CONFIG,
  PII,
  PROMPT,
  SKIP,
  TEST_TIMEOUT_MS,
  TOOL_RESULT_TEXT,
  WARMUP_TIMEOUT_MS,
  distinctPlaceholders,
  leaked,
  splitBetweenOpeningBraces,
  splitInsideFirstPlaceholder,
  startRealEngine,
} from './helpers.js';

const OK = 200;
const MESSAGES_PATH = '/v1/messages';
const COUNT_TOKENS_PATH = '/v1/messages/count_tokens';
const CLIENT_HEADERS = {
  'content-type': 'application/json',
  'anthropic-version': '2023-06-01',
  'x-api-key': 'sk-ant-e2e-test',
};
const MODEL = 'claude-test';
const MAX_TOKENS = 512;
const SYSTEM_PROMPT = 'You are a billing assistant.';
const LOOKUP_ID = 'toolu_lookup';
const REPLY_PREFIX = 'Here is your request back: ';
const NOTES_FILE = '/repo/docs/NOTES';
/** A shell tool: kept masked whatever `restoreTools` says. */
const SHELL_TOOL = 'Bash';
const CRM_URL = 'https://crm.example/lookup';
const INPUT_TOKENS = 321;
/** Small enough that frames, and placeholders in them, arrive cut. */
const SSE_CHUNK_BYTES = 61;
/** A placeholder no session of this suite minted: it must stay literal. */
const FOREIGN = PLACEHOLDER_TEMPLATE('private_person', 0, '0123456789abcdef');

/** A turn of a billing agent: the user's prompt (person, email), the
 * history's tool call (email) and its result (person, IBAN, AWS key), and
 * `metadata.user_id` (email). */
function messagesRequest(stream: boolean): AnthropicRequest {
  return {
    model: MODEL,
    max_tokens: MAX_TOKENS,
    stream,
    system: SYSTEM_PROMPT,
    metadata: { user_id: PII.email },
    messages: [
      { role: 'user', content: PROMPT },
      {
        role: 'assistant',
        content: [
          { type: 'tool_use', id: LOOKUP_ID, name: 'lookup_customer', input: { email: PII.email } },
        ],
      },
      {
        role: 'user',
        content: [{ type: 'tool_result', tool_use_id: LOOKUP_ID, content: TOOL_RESULT_TEXT }],
      },
    ],
  };
}

/** What the gateway forwarded in place of the prompt and the tool result. */
interface Forwarded {
  readonly prompt: string;
  readonly toolResult: string;
}

function forwardedTexts(request: AnthropicRequest): Forwarded {
  const prompt = request.messages[0]?.content;
  const results = request.messages[2]?.content;
  const result = Array.isArray(results) ? results[0] : undefined;
  const toolResult = result?.type === 'tool_result' ? result.content : undefined;
  if (typeof prompt !== 'string' || typeof toolResult !== 'string') {
    throw new Error('the forwarded request lost its prompt or its tool result');
  }
  return { prompt, toolResult };
}

/** The tool inputs an upstream model would write from the masked turn. */
function writeInput(f: Forwarded): Record<string, string> {
  return { file_path: NOTES_FILE, content: f.toolResult };
}

function fetchInput(f: Forwarded): Record<string, string> {
  return { url: CRM_URL, prompt: f.prompt };
}

function bashInput(f: Forwarded): Record<string, string> {
  return { command: `echo '${f.toolResult}' >> notes.txt` };
}

function toolUse(id: string, name: string, input: unknown): AnthropicContentBlock {
  return { type: 'tool_use', id, name, input };
}

/** An upstream reply that echoes the masked prompt in its text and the
 * masked values in a Write, a WebFetch and a Bash call. */
function echoMessage(f: Forwarded): AnthropicResponse {
  return {
    id: 'msg_e2e',
    type: 'message',
    role: 'assistant',
    content: [
      { type: 'text', text: `${REPLY_PREFIX}${f.prompt} ${FOREIGN}` },
      toolUse('toolu_write', 'Write', writeInput(f)),
      toolUse('toolu_fetch', 'WebFetch', fetchInput(f)),
      toolUse('toolu_bash', SHELL_TOOL, bashInput(f)),
    ],
  };
}

function textDelta(index: number, text: string): StreamEvent {
  return { type: 'content_block_delta', index, delta: { type: 'text_delta', text } };
}

function jsonDelta(index: number, partial: string): StreamEvent {
  return {
    type: 'content_block_delta',
    index,
    delta: { type: 'input_json_delta', partial_json: partial },
  };
}

function blockStart(index: number, block: Record<string, unknown>): StreamEvent {
  return { type: 'content_block_start', index, content_block: block };
}

/** The frames of `echoMessage` as a stream, its text and its Write input
 * each sent in two deltas cut in a placeholder: the text between its two
 * opening braces, the Write input in its middle. */
function echoFrames(f: Forwarded): string[] {
  const [textHead, textTail] = splitBetweenOpeningBraces(`${REPLY_PREFIX}${f.prompt}`);
  const [writeHead, writeTail] = splitInsideFirstPlaceholder(JSON.stringify(writeInput(f)));
  const events: StreamEvent[] = [
    {
      type: 'message_start',
      message: { id: 'msg_e2e', type: 'message', role: 'assistant', content: [] },
    },
    blockStart(0, { type: 'text', text: '' }),
    textDelta(0, textHead),
    textDelta(0, textTail),
    { type: 'content_block_stop', index: 0 },
    blockStart(1, { type: 'tool_use', id: 'toolu_write', name: 'Write', input: {} }),
    jsonDelta(1, writeHead),
    jsonDelta(1, writeTail),
    { type: 'content_block_stop', index: 1 },
    blockStart(2, { type: 'tool_use', id: 'toolu_fetch', name: 'WebFetch', input: {} }),
    jsonDelta(2, JSON.stringify(fetchInput(f))),
    { type: 'content_block_stop', index: 2 },
    blockStart(3, { type: 'tool_use', id: 'toolu_bash', name: SHELL_TOOL, input: {} }),
    jsonDelta(3, JSON.stringify(bashInput(f))),
    { type: 'content_block_stop', index: 3 },
    { type: 'message_delta', delta: { stop_reason: 'tool_use' } },
    { type: 'message_stop' },
  ];
  return events.map(sseFrame);
}

/** A streamed reply put back together as a client SDK does: the text and
 * the tool input of each block, by index. */
interface Reassembled {
  readonly text: Map<number, string>;
  readonly input: Map<number, string>;
}

function appendTo(parts: Map<number, string>, index: number, piece: string): void {
  parts.set(index, (parts.get(index) ?? '') + piece);
}

function reassemble(events: readonly StreamEvent[]): Reassembled {
  const out: Reassembled = { text: new Map(), input: new Map() };
  for (const event of events) {
    if (event.type !== 'content_block_delta' || typeof event.index !== 'number') continue;
    const delta = event.delta as { type?: unknown; text?: unknown; partial_json?: unknown };
    if (delta.type === 'text_delta' && typeof delta.text === 'string') {
      appendTo(out.text, event.index, delta.text);
    }
    if (delta.type === 'input_json_delta' && typeof delta.partial_json === 'string') {
      appendTo(out.input, event.index, delta.partial_json);
    }
  }
  return out;
}

/** The forwarded request carries no fixture value anywhere, one
 * placeholder at least per value, and the preservation hint. */
function expectMaskedUpstream(call: UpstreamCall, path: string): void {
  expect(call.url).toBe(`${E2E_CONFIG.upstreamBaseUrl}${path}`);
  expect(leaked(call.body), call.body).toEqual([]);
  expect(distinctPlaceholders(call.body).length).toBeGreaterThanOrEqual(ALL_PII.length);
  expect(call.request.system).toBe(`${SYSTEM_PROMPT}\n\n${LLM_PRESERVATION_HINT}`);
}

describe.skipIf(SKIP)('gateway e2e · Messages proxy on the real model', () => {
  let np: NullPii;
  const apps: FastifyInstance[] = [];

  beforeAll(async () => {
    np = await startRealEngine();
  }, WARMUP_TIMEOUT_MS);

  afterEach(async () => {
    await Promise.all(apps.map((app) => app.close()));
    apps.length = 0;
  });

  afterAll(async () => {
    if (np !== undefined) await np.dispose();
  });

  /** A gateway on the shared engine whose upstream is `upstream`. */
  async function proxyTo(
    upstream: FakeUpstream,
    config: GatewayConfig = E2E_CONFIG,
  ): Promise<FastifyInstance> {
    const app = await buildServer({ config, np, fetchImpl: upstream.fetchImpl });
    apps.push(app);
    return app;
  }

  function post(app: FastifyInstance, url: string, payload: AnthropicRequest) {
    return app.inject({ method: 'POST', url, headers: CLIENT_HEADERS, payload });
  }

  it(
    'masks the request before it leaves, and restores the echoed placeholders in a JSON reply',
    async () => {
      const upstream = fakeUpstream((request) => jsonAnswer(echoMessage(forwardedTexts(request))));
      const app = await proxyTo(upstream);

      const res = await post(app, MESSAGES_PATH, messagesRequest(false));

      expect(res.statusCode).toBe(OK);
      const call = onlyCall(upstream);
      expectMaskedUpstream(call, MESSAGES_PATH);
      const forwarded = forwardedTexts(call.request);
      expect(res.json<AnthropicResponse>().content).toEqual([
        // The reply text gets every value back; a placeholder no session
        // minted stays as it came.
        { type: 'text', text: `${REPLY_PREFIX}${PROMPT} ${FOREIGN}` },
        toolUse('toolu_write', 'Write', { file_path: NOTES_FILE, content: TOOL_RESULT_TEXT }),
        // Tools outside restoreTools keep them masked (the shell rule on
        // its own, with the shell in restoreTools, is tested below).
        toolUse('toolu_fetch', 'WebFetch', fetchInput(forwarded)),
        toolUse('toolu_bash', SHELL_TOOL, bashInput(forwarded)),
      ]);
      expect(leaked(JSON.stringify([fetchInput(forwarded), bashInput(forwarded)]))).toEqual([]);
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'restores a streamed reply whose placeholders arrive cut across deltas and network chunks',
    async () => {
      const upstream = fakeUpstream((request) =>
        sseAnswer(echoFrames(forwardedTexts(request)), SSE_CHUNK_BYTES),
      );
      const app = await proxyTo(upstream);

      const res = await post(app, MESSAGES_PATH, messagesRequest(true));

      expect(res.statusCode).toBe(OK);
      expect(res.headers['content-type']).toContain('text/event-stream');
      const call = onlyCall(upstream);
      expectMaskedUpstream(call, MESSAGES_PATH);
      const forwarded = forwardedTexts(call.request);
      const events = sseEvents(res.body);
      const blocks = reassemble(events);
      expect(blocks.text.get(0)).toBe(`${REPLY_PREFIX}${PROMPT}`);
      expect(JSON.parse(blocks.input.get(1) ?? '')).toEqual({
        file_path: NOTES_FILE,
        content: TOOL_RESULT_TEXT,
      });
      const held = blocks.input.get(2) ?? '';
      expect(JSON.parse(held)).toEqual(fetchInput(forwarded));
      expect(leaked(held)).toEqual([]);
      expect(JSON.parse(blocks.input.get(3) ?? '')).toEqual(bashInput(forwarded));
      expect(events.at(-1)?.type).toBe('message_stop');
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'keeps a shell call masked even when restoreTools names the shell, in a JSON and a streamed reply',
    async () => {
      const config: GatewayConfig = {
        ...E2E_CONFIG,
        restoreTools: new Set([...E2E_CONFIG.restoreTools, SHELL_TOOL]),
      };
      for (const stream of [false, true]) {
        const upstream = fakeUpstream((request) =>
          stream
            ? sseAnswer(echoFrames(forwardedTexts(request)), SSE_CHUNK_BYTES)
            : jsonAnswer(echoMessage(forwardedTexts(request))),
        );
        const app = await proxyTo(upstream, config);

        const res = await post(app, MESSAGES_PATH, messagesRequest(stream));

        expect(res.statusCode).toBe(OK);
        const forwarded = forwardedTexts(onlyCall(upstream).request);
        const bash = stream
          ? (reassemble(sseEvents(res.body)).input.get(3) ?? '')
          : JSON.stringify(
              res
                .json<AnthropicResponse>()
                .content.find((b) => b.type === 'tool_use' && b.name === SHELL_TOOL)?.input,
            );
        expect({ stream, input: JSON.parse(bash) }).toEqual({
          stream,
          input: bashInput(forwarded),
        });
        expect(leaked(bash)).toEqual([]);
      }
    },
    TEST_TIMEOUT_MS,
  );

  it(
    'masks a count_tokens request too, and passes its answer through',
    async () => {
      const upstream = fakeUpstream(() => jsonAnswer({ input_tokens: INPUT_TOKENS }));
      const app = await proxyTo(upstream);

      const res = await post(app, COUNT_TOKENS_PATH, messagesRequest(false));

      expect(res.statusCode).toBe(OK);
      expect(res.json()).toEqual({ input_tokens: INPUT_TOKENS });
      expectMaskedUpstream(onlyCall(upstream), COUNT_TOKENS_PATH);
    },
    TEST_TIMEOUT_MS,
  );
});
