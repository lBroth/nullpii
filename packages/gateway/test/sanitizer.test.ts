// SPDX-License-Identifier: Apache-2.0
//
// Leak tests for the request walk: every Anthropic content block that can
// carry user text must reach the upstream sanitized, including block types
// the gateway does not model explicitly. A canary value planted in each
// place must never survive `sanitizeRequest`.
import type { NullPii } from 'nullpii';
import { PiiVault } from 'nullpii';
import { describe, expect, it } from 'vitest';
import { sanitizeRequest } from '../src/sanitizer.js';
import type { AnthropicRequest } from '../src/types.js';

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
