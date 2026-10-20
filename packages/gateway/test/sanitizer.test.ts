// SPDX-License-Identifier: Apache-2.0
//
// Leak tests for the request walk: every Anthropic content block that can
// carry user text must reach the upstream sanitized, including block types
// the gateway does not model explicitly. A canary value planted in each
// place must never survive `sanitizeRequest`.
import type { NullPii } from 'nullpii';
import { PiiVault } from 'nullpii';
import { describe, expect, it } from 'vitest';
import { restoreResponse, sanitizeRequest } from '../src/sanitizer.js';
import type { AnthropicRequest, AnthropicResponse } from '../src/types.js';

const CANARY = 'canary.person@example.com';
const BASE64_BODY = 'JVBERi0xLjQKJcfsj6IK';
const THINKING_SIGNATURE = 'EqQBCkYIBxgCKkA-signature';

function mockNullPii(): NullPii {
  const vault = new PiiVault();
  const mock = {
    async sanitize(text: string, sessionId?: string) {
      const id = sessionId ?? vault.createSession();
      const spans = [...text.matchAll(/canary\.person@example\.com/g)].map((m) => ({
        label: 'private_email' as const,
        start: m.index ?? 0,
        end: (m.index ?? 0) + m[0].length,
        text: m[0],
        score: 1,
      }));
      const r = vault.sanitize(text, spans, id);
      return { sessionId: id, sanitized: r.sanitized, spans };
    },
    restore: (text: string, sessionId: string) => vault.restore(text, sessionId),
    createSession: () => vault.createSession(),
    destroySession: (sessionId: string) => vault.destroySession(sessionId),
  };
  return mock as unknown as NullPii;
}

function request(content: unknown[]): AnthropicRequest {
  return {
    model: 'claude-test',
    messages: [
      { role: 'user', content: content as AnthropicRequest['messages'][number]['content'] },
    ],
  } as AnthropicRequest;
}

async function walk(content: unknown[]) {
  const out = await sanitizeRequest(mockNullPii(), request(content));
  return { json: JSON.stringify(out.body), out };
}

describe('sanitizeRequest: no user text reaches the upstream unscanned', () => {
  it('scrubs a plain-text document source and its title', async () => {
    const { json } = await walk([
      {
        type: 'document',
        title: `Notes for ${CANARY}`,
        source: { type: 'text', media_type: 'text/plain', data: `Contact ${CANARY}` },
      },
    ]);
    expect(json).not.toContain(CANARY);
  });

  it('scrubs a document built from content blocks', async () => {
    const { json } = await walk([
      {
        type: 'document',
        source: { type: 'content', content: [{ type: 'text', text: `mail ${CANARY}` }] },
      },
    ]);
    expect(json).not.toContain(CANARY);
  });

  it('scrubs search results, including inside a tool result', async () => {
    const searchResult = {
      type: 'search_result',
      source: 'https://kb.example.com/a',
      title: `Profile of ${CANARY}`,
      content: [{ type: 'text', text: `reach ${CANARY}` }],
    };
    const { json } = await walk([
      searchResult,
      { type: 'tool_result', tool_use_id: 'toolu_1', content: [searchResult] },
    ]);
    expect(json).not.toContain(CANARY);
  });

  it('scrubs quoted text in citations', async () => {
    const { json } = await walk([
      {
        type: 'text',
        text: 'See the record.',
        citations: [{ type: 'char_location', cited_text: `owner ${CANARY}`, document_index: 0 }],
      },
    ]);
    expect(json).not.toContain(CANARY);
  });

  it('scrubs a block type it does not know', async () => {
    const { json } = await walk([{ type: 'future_block', payload: { note: `ping ${CANARY}` } }]);
    expect(json).not.toContain(CANARY);
  });

  it('scrubs MCP tool calls and results like local ones', async () => {
    const { json } = await walk([
      { type: 'mcp_tool_use', id: 'mcptoolu_1', name: 'crm', input: { email: CANARY } },
      {
        type: 'mcp_tool_result',
        tool_use_id: 'mcptoolu_1',
        content: [{ type: 'text', text: CANARY }],
      },
    ]);
    expect(json).not.toContain(CANARY);
  });
});

describe('sanitizeRequest: protocol structure stays intact', () => {
  it('forwards binary sources untouched and counts them as unscanned', async () => {
    const { json, out } = await walk([
      { type: 'image', source: { type: 'base64', media_type: 'image/png', data: BASE64_BODY } },
      {
        type: 'document',
        source: { type: 'base64', media_type: 'application/pdf', data: BASE64_BODY },
      },
      { type: 'document', source: { type: 'file', file_id: 'file_011' } },
    ]);
    expect(json.split(BASE64_BODY)).toHaveLength(3);
    expect(json).toContain('file_011');
    expect(out.unscanned).toBe(3);
  });

  it('leaves thinking blocks and their signature byte-identical', async () => {
    const thinking = { type: 'thinking', thinking: 'plan the edit', signature: THINKING_SIGNATURE };
    const { out } = await walk([thinking, { type: 'text', text: 'ok' }]);
    const content = out.body.messages[0]?.content as unknown[];
    expect(content[0]).toEqual(thinking);
  });

  it('keeps ids, tool names and media types', async () => {
    const { json } = await walk([
      { type: 'tool_use', id: 'toolu_9', name: 'Read', input: { path: 'a.ts' } },
      { type: 'tool_result', tool_use_id: 'toolu_9', content: `owner ${CANARY}` },
    ]);
    expect(json).toContain('"id":"toolu_9"');
    expect(json).toContain('"name":"Read"');
    expect(json).toContain('"tool_use_id":"toolu_9"');
    expect(json).not.toContain(CANARY);
  });
});

describe('sanitizeRequest: request fields outside messages', () => {
  it('scrubs metadata and stop sequences', async () => {
    const body = {
      ...request([{ type: 'text', text: 'hi' }]),
      metadata: { user_id: CANARY },
      stop_sequences: [`END ${CANARY}`],
    } as AnthropicRequest;
    const out = await sanitizeRequest(mockNullPii(), body);
    expect(JSON.stringify(out.body)).not.toContain(CANARY);
    expect(Object.keys(out.body.metadata as object)).toEqual(['user_id']);
  });

  it("scrubs a tool's input_schema text and data, keeping names and keywords", async () => {
    const schema = {
      type: 'object',
      title: `Lookup for ${CANARY}`,
      properties: {
        recipient: {
          type: 'string',
          description: `who, e.g. ${CANARY}`,
          enum: [CANARY, 'nobody'],
          default: CANARY,
          examples: [{ to: CANARY }],
        },
        nested: { type: 'array', items: { type: 'string', const: CANARY } },
      },
      $defs: { addr: { type: 'string', description: `like ${CANARY}` } },
      required: ['recipient'],
    };
    const body = {
      ...request([{ type: 'text', text: 'hi' }]),
      tools: [{ name: 'send', description: 'Send mail', input_schema: schema }],
    } as AnthropicRequest;
    const out = await sanitizeRequest(mockNullPii(), body);
    const sent = out.body.tools?.[0]?.input_schema as {
      properties: Record<string, { type: string; enum?: string[]; examples?: object[] }>;
      required: string[];
      $defs: object;
    };
    expect(JSON.stringify(sent)).not.toContain(CANARY);
    expect(Object.keys(sent.properties)).toEqual(['recipient', 'nested']);
    const recipient = sent.properties.recipient;
    expect(recipient?.type).toBe('string');
    expect(recipient?.enum?.[1]).toBe('nobody');
    expect(Object.keys(recipient?.examples?.[0] ?? {})).toEqual(['to']);
    expect(sent.required).toEqual(['recipient']);
    expect(Object.keys(sent.$defs)).toEqual(['addr']);
  });

  it('scrubs object keys inside tool_use input, each distinct key once', async () => {
    let calls = 0;
    const np = mockNullPii();
    const sanitize = np.sanitize.bind(np);
    (np as unknown as { sanitize: typeof sanitize }).sanitize = (text, sessionId) => {
      calls += 1;
      return sanitize(text, sessionId);
    };
    const toolUses = Array.from({ length: 20 }, (_, i) => ({
      type: 'tool_use',
      id: `t${i}`,
      name: 'lookup',
      input: { [CANARY]: 'owner', command: 'ls' },
    }));
    const { body } = await sanitizeRequest(np, {
      model: 'claude-test',
      messages: [{ role: 'assistant', content: toolUses }],
    } as AnthropicRequest);
    expect(JSON.stringify(body)).not.toContain(CANARY);
    // 2 distinct keys + 40 values ('owner' and 'ls' twenty times each).
    expect(calls).toBe(2 + 40);
  });
});

describe('restoreResponse: object keys', () => {
  it('puts the real value back into a masked key of a local tool call', async () => {
    const np = mockNullPii();
    const { body, sessionId } = await sanitizeRequest(
      np,
      request([{ type: 'text', text: CANARY }]),
    );
    const placeholder = (body.messages[0]?.content as Array<{ text: string }>)[0]?.text ?? '';
    const response = {
      id: 'msg_1',
      type: 'message',
      role: 'assistant',
      content: [{ type: 'tool_use', id: 't1', name: 'Write', input: { [placeholder]: 'owner' } }],
    } as AnthropicResponse;

    const out = restoreResponse(np, response, sessionId);

    expect(out.body.content[0]?.input).toEqual({ [CANARY]: 'owner' });
    expect(out.replacements).toBe(1);
  });
});
