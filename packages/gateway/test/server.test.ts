// SPDX-License-Identifier: Apache-2.0
//
// Gateway unit tests. The ML engine (`NullPii`) and the upstream
// `fetch` are both mocked — this suite verifies routing, walk-and-
// rewrite logic, error propagation, and request lifecycle. The real
// model + real Anthropic round-trip lives in an E2E suite gated on
// `NULLPII_GATEWAY_E2E=1` (not in this PR).

import type { NullPii } from 'nullpii';
import { PiiVault } from 'nullpii';
import { afterEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import { buildServer } from '../src/server.js';
import type { AnthropicResponse } from '../src/types.js';

const TEST_CONFIG: GatewayConfig = {
  host: '127.0.0.1',
  port: 0,
  upstreamBaseUrl: 'https://upstream.test',
  vaultTtlMs: 60_000,
  backend: 'cpu',
  logLevel: 'fatal',
  bodyLimitBytes: 10 * 1024 * 1024,
  logTraffic: false,
};

/**
 * Mock NullPii: a real PiiVault for placeholder bookkeeping + a
 * deterministic "detect" pass that flags every occurrence of `John` and
 * `john@acme.io` in the input. Lets the gateway test prove the walk
 * touched every text block without depending on ONNX.
 */
function buildMockNullPii(): { np: NullPii; sanitizeCalls: string[]; restoreCalls: string[] } {
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

  return { np: mock as unknown as NullPii, sanitizeCalls, restoreCalls };
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
