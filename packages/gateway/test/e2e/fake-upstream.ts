// SPDX-License-Identifier: Apache-2.0
//
// A fake Anthropic upstream for the gateway's real-ONNX suite. It records
// every request the gateway forwards, exactly as sent, and answers with
// what the test builds from that request: a JSON message, or an SSE stream
// cut into small network chunks.

import type { AnthropicRequest } from '../../src/types.js';
import type { Fetch } from '../../src/upstream.js';

/** One request the gateway sent upstream. */
export interface UpstreamCall {
  readonly url: string;
  /** The body as it went over the wire. */
  readonly body: string;
  readonly request: AnthropicRequest;
}

/** The `fetch` to build the gateway with, and what it received. */
export interface FakeUpstream {
  readonly fetchImpl: Fetch;
  readonly calls: readonly UpstreamCall[];
}

/** One Anthropic stream event: its `type` and its fields. */
export interface StreamEvent {
  readonly type: string;
  readonly [field: string]: unknown;
}

const OK = 200;
const SSE_FRAME_END = '\n\n';
const DATA_FIELD = 'data:';

/** An upstream that records each request and answers it with `answer`. */
export function fakeUpstream(answer: (request: AnthropicRequest) => Response): FakeUpstream {
  const calls: UpstreamCall[] = [];
  const fetchImpl: Fetch = async (url, init) => {
    if (typeof init.body !== 'string') throw new Error('the gateway sent a body that is not text');
    const request = JSON.parse(init.body) as AnthropicRequest;
    calls.push({ url, body: init.body, request });
    return answer(request);
  };
  return { fetchImpl, calls };
}

/** The only request an upstream received; fails loud on none or several. */
export function onlyCall(upstream: FakeUpstream): UpstreamCall {
  const [call, ...more] = upstream.calls;
  if (call === undefined || more.length > 0) {
    throw new Error(`expected one upstream call, got ${upstream.calls.length}`);
  }
  return call;
}

/** A 200 JSON answer. */
export function jsonAnswer(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: OK,
    headers: { 'content-type': 'application/json' },
  });
}

/** One SSE frame for `event`, named by its type as Anthropic names it. */
export function sseFrame(event: StreamEvent): string {
  return `event: ${event.type}\n${DATA_FIELD} ${JSON.stringify(event)}${SSE_FRAME_END}`;
}

/** A 200 SSE answer that sends `frames` in network chunks of `chunkBytes`,
 * so frames, and the placeholders in them, arrive cut at any byte. */
export function sseAnswer(frames: readonly string[], chunkBytes: number): Response {
  const bytes = new TextEncoder().encode(frames.join(''));
  const body = new ReadableStream<Uint8Array>({
    start(controller) {
      for (let at = 0; at < bytes.length; at += chunkBytes) {
        controller.enqueue(bytes.slice(at, at + chunkBytes));
      }
      controller.close();
    },
  });
  return new Response(body, { status: OK, headers: { 'content-type': 'text/event-stream' } });
}

/** The events of an SSE body as a client reads them: each frame's `data`
 * lines, joined and parsed. Frames without data are skipped. */
export function sseEvents(body: string): StreamEvent[] {
  return body
    .split(SSE_FRAME_END)
    .map(frameData)
    .filter((data): data is string => data !== null)
    .map((data) => JSON.parse(data) as StreamEvent);
}

function frameData(frame: string): string | null {
  const lines = frame
    .split('\n')
    .filter((line) => line.startsWith(DATA_FIELD))
    .map((line) => line.slice(DATA_FIELD.length).trimStart());
  return lines.length === 0 ? null : lines.join('\n');
}
