// SPDX-License-Identifier: Apache-2.0
//
// Unit tests for the SSE relay. Real PiiVault + handcrafted SSE
// frames. The relay must:
//
//   1. Hold open `{{...` placeholders across SSE-delta boundaries so
//      the downstream SDK never sees a leaked placeholder shape.
//   2. Forward non-text events (`message_start`, `ping`, `content_block_stop`,
//      `message_delta`, `message_stop`) byte-for-byte.
//   3. Synthesise a final `text_delta` before `content_block_stop`
//      to drain any residual restorer buffer.
//   4. Track per-block restorers independently — interleaved blocks
//      (tool_use + text) must not corrupt each other.

import { type NullPii, type PiiSpan, PiiVault } from 'nullpii';
import { describe, expect, it } from 'vitest';
import { relaySseStream } from '../src/sse-relay.js';

/** Build a minimal NullPii-shaped object backed by a real PiiVault.
 * We don't need detection here — the test pre-sanitises text via the
 * vault and emits placeholders directly into the SSE stream, then
 * checks the relay restores them. */
function buildHarness(): { np: NullPii; vault: PiiVault; sessionId: string } {
  const vault = new PiiVault();
  const sessionId = vault.createSession();
  const np = {
    restore: (text: string, sid: string) => vault.restore(text, sid),
    destroySession: (sid: string) => vault.destroySession(sid),
  } as unknown as NullPii;
  return { np, vault, sessionId };
}

function span(label: PiiSpan['label'], start: number, end: number, text: string): PiiSpan {
  return { label, start, end, text, score: 1 };
}

/** Bake a placeholder for `originalValue` into the vault and return it. */
function bake(
  vault: PiiVault,
  sessionId: string,
  originalValue: string,
  label: PiiSpan['label'],
): string {
  const r = vault.sanitize(
    originalValue,
    [span(label, 0, originalValue.length, originalValue)],
    sessionId,
  );
  return r.sanitized;
}

/** Produce an async iterable over the supplied UTF-8 chunks. */
async function* chunkStream(chunks: string[]): AsyncIterable<Uint8Array> {
  const enc = new TextEncoder();
  for (const c of chunks) yield enc.encode(c);
}

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

/** Reassemble per-block text by reading every `text_delta` event in
 * the relayed output and concatenating by `index`. Matches the
 * accumulation the Anthropic SDK performs on the consumer side. */
function reassembleBlocks(frames: string[]): Map<number, string> {
  const out = new Map<number, string>();
  for (const frame of frames) {
    const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
    if (dataLine === undefined) continue;
    let parsed: { type?: string; index?: number; delta?: { type?: string; text?: string } };
    try {
      parsed = JSON.parse(dataLine.slice('data:'.length).trim());
    } catch {
      continue;
    }
    if (
      parsed.type === 'content_block_delta' &&
      typeof parsed.index === 'number' &&
      parsed.delta?.type === 'text_delta' &&
      typeof parsed.delta.text === 'string'
    ) {
      out.set(parsed.index, (out.get(parsed.index) ?? '') + parsed.delta.text);
    }
  }
  return out;
}

describe('relaySseStream', () => {
  it('restores a placeholder that arrives in a single delta', async () => {
    const { np, vault, sessionId } = buildHarness();
    const placeholder = bake(vault, sessionId, 'Alice', 'private_person');
    const frames: string[] = [
      sseFrame('message_start', {
        type: 'message_start',
        message: { id: 'msg', type: 'message', role: 'assistant', content: [] },
      }),
      sseFrame('content_block_start', {
        type: 'content_block_start',
        index: 0,
        content_block: { type: 'text', text: '' },
      }),
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'text_delta', text: `Hi ${placeholder} there` },
      }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 0 }),
      sseFrame('message_stop', { type: 'message_stop' }),
    ];
    const out: string[] = [];
    const counters = await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(frames),
      write: (f) => out.push(f),
    });
    const joined = out.join('');
    expect(joined).toContain('Hi Alice there');
    expect(joined).not.toContain(placeholder); // placeholder text not leaked
    expect(counters.replacements).toBe(1);
    expect(counters.replacementsByLabel.private_person).toBe(1);
  });

  it('holds an open placeholder across delta boundaries', async () => {
    const { np, vault, sessionId } = buildHarness();
    const placeholder = bake(vault, sessionId, 'Bob', 'private_person');
    // Split the placeholder mid-token across TWO content_block_delta frames.
    const mid = Math.floor(placeholder.length / 2);
    const frames: string[] = [
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'text_delta', text: `Hi ${placeholder.slice(0, mid)}` },
      }),
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'text_delta', text: `${placeholder.slice(mid)} there` },
      }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 0 }),
    ];
    const out: string[] = [];
    await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(frames),
      write: (f) => out.push(f),
    });
    // The SDK consumer accumulates `text_delta.text` per block index;
    // the relay may split a single semantic message across multiple
    // emitted deltas (safe-prefix + post-close).
    const blocks = reassembleBlocks(out);
    expect(blocks.get(0)).toBe('Hi Bob there');
    expect(out.join('')).not.toContain('{{PII_'); // no partial placeholder leaked
  });

  it('survives byte-by-byte upstream fragmentation', async () => {
    const { np, vault, sessionId } = buildHarness();
    const placeholder = bake(vault, sessionId, 'charlie@x.io', 'private_email');
    const fullStream = [
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'text_delta', text: `Reach ${placeholder} now` },
      }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 0 }),
    ].join('');
    // Split EVERY byte boundary — the cruelest fragmentation.
    const chunks = Array.from(fullStream).map((c) => c);
    const out: string[] = [];
    await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(chunks),
      write: (f) => out.push(f),
    });
    const joined = out.join('');
    expect(joined).toContain('Reach charlie@x.io now');
    expect(joined).not.toContain('{{PII_');
  });

  it('forwards non-text events unchanged', async () => {
    const { np, sessionId } = buildHarness();
    const frames: string[] = [
      sseFrame('message_start', {
        type: 'message_start',
        message: { id: 'm', type: 'message', role: 'assistant', content: [] },
      }),
      sseFrame('ping', { type: 'ping' }),
      sseFrame('content_block_start', {
        type: 'content_block_start',
        index: 0,
        content_block: { type: 'text', text: '' },
      }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 0 }),
      sseFrame('message_delta', { type: 'message_delta', delta: { stop_reason: 'end_turn' } }),
      sseFrame('message_stop', { type: 'message_stop' }),
    ];
    const out: string[] = [];
    await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(frames),
      write: (f) => out.push(f),
    });
    const joined = out.join('');
    expect(joined).toContain('event: ping');
    expect(joined).toContain('"type":"message_start"');
    expect(joined).toContain('"stop_reason":"end_turn"');
    expect(joined).toContain('"type":"message_stop"');
  });

  it('restores placeholders inside tool_use input_json_delta, buffered until content_block_stop', async () => {
    const { np, vault, sessionId } = buildHarness();
    const ph = bake(vault, sessionId, 'IT60X0542811101000001023456', 'account_number');
    // Two partial-JSON shards split mid-placeholder, then a stop frame.
    const head = ph.slice(0, 8);
    const tail = ph.slice(8);
    const frames: string[] = [
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 1,
        delta: { type: 'input_json_delta', partial_json: `{"iban":"${head}` },
      }),
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 1,
        delta: { type: 'input_json_delta', partial_json: `${tail}"}` },
      }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 1 }),
    ];
    const out: string[] = [];
    await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(frames),
      write: (f) => out.push(f),
    });
    const joined = out.join('');
    // Original placeholder shards must NOT leak.
    expect(joined).not.toContain('{{PII_');
    // Restored JSON must arrive as one synthesised input_json_delta
    // before the stop frame.
    expect(joined).toContain('"partial_json":"{\\"iban\\":\\"IT60X0542811101000001023456\\"}"');
    // Stop frame still forwarded.
    expect(joined).toContain('"type":"content_block_stop"');
  });

  it('content_block_stop for a different index does not flush a buffered input_json_delta', async () => {
    // Regression: per-block jsonBuffers must be keyed by index. A stop
    // frame for block 9 should leave block 0's buffered JSON untouched
    // (drain it at end-of-stream instead, not cross-emit it inside a
    // block-9 envelope).
    const { np, vault, sessionId } = buildHarness();
    const ph = bake(vault, sessionId, 'bob@example.com', 'private_email');
    const frames: string[] = [
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'input_json_delta', partial_json: `{"to":"${ph}"}` },
      }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 9 }),
    ];
    const out: string[] = [];
    await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(frames),
      write: (f) => out.push(f),
    });
    const joined = out.join('');
    // Restored JSON must appear EXACTLY once (drained at end-of-stream,
    // not under the block-9 stop frame).
    const matches = joined.match(/"partial_json":"{\\"to\\":\\"bob@example.com\\"}"/g) ?? [];
    expect(matches).toHaveLength(1);
    // Block-9 stop frame still forwarded verbatim.
    expect(joined).toMatch(/"type":"content_block_stop"[\s\S]*"index":9/);
  });

  it('drains buffered input_json_delta at end-of-stream when content_block_stop never arrives', async () => {
    const { np, vault, sessionId } = buildHarness();
    const ph = bake(vault, sessionId, 'alice@example.com', 'private_email');
    const frames: string[] = [
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'input_json_delta', partial_json: `{"to":"${ph}"}` },
      }),
      // No content_block_stop, no message_stop — upstream truncated.
    ];
    const out: string[] = [];
    await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(frames),
      write: (f) => out.push(f),
    });
    const joined = out.join('');
    expect(joined).not.toContain('{{PII_');
    expect(joined).toContain('"partial_json":"{\\"to\\":\\"alice@example.com\\"}"');
  });

  it('keeps per-block restorers independent (block 0 + block 1 interleaved)', async () => {
    const { np, vault, sessionId } = buildHarness();
    const phA = bake(vault, sessionId, 'Dana', 'private_person');
    const phB = bake(vault, sessionId, 'Eve', 'private_person');
    // Alternate frames for two text blocks.
    const frames: string[] = [
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'text_delta', text: `A:${phA.slice(0, 5)}` },
      }),
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 1,
        delta: { type: 'text_delta', text: `B:${phB.slice(0, 6)}` },
      }),
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'text_delta', text: `${phA.slice(5)} end` },
      }),
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 1,
        delta: { type: 'text_delta', text: `${phB.slice(6)} end` },
      }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 0 }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 1 }),
    ];
    const out: string[] = [];
    await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(frames),
      write: (f) => out.push(f),
    });
    const blocks = reassembleBlocks(out);
    expect(blocks.get(0)).toBe('A:Dana end');
    expect(blocks.get(1)).toBe('B:Eve end');
    expect(out.join('')).not.toContain('{{PII_');
  });

  it('drains residual buffer at content_block_stop (open placeholder at end)', async () => {
    const { np, vault, sessionId } = buildHarness();
    const placeholder = bake(vault, sessionId, 'Frank', 'private_person');
    // Last delta ends with the placeholder open (no `}}` to close it).
    // The relay must flush on `content_block_stop` so the value reaches
    // the downstream SDK.
    const frames: string[] = [
      sseFrame('content_block_delta', {
        type: 'content_block_delta',
        index: 0,
        delta: { type: 'text_delta', text: `Hi ${placeholder}` },
      }),
      sseFrame('content_block_stop', { type: 'content_block_stop', index: 0 }),
    ];
    const out: string[] = [];
    await relaySseStream({
      np,
      sessionId,
      upstream: chunkStream(frames),
      write: (f) => out.push(f),
    });
    expect(out.join('')).toContain('Hi Frank');
  });
});
