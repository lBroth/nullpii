// SPDX-License-Identifier: Apache-2.0
//
// Backpressure on the streaming routes: a relay waits for each frame to be
// accepted before it reads more from the upstream, and a frame written to
// a full socket waits for 'drain', or fails once the client has gone.

import { EventEmitter } from 'node:events';
import type { ServerResponse } from 'node:http';
import { type NullPii, PiiVault } from 'nullpii';
import { describe, expect, it } from 'vitest';
import { relayChatSseStream } from '../src/openai-sse-relay.js';
import { writeFrame } from '../src/routes/common.js';
import { relaySseStream } from '../src/sse-relay.js';

const encoder = new TextEncoder();

function engine(): { np: NullPii; sessionId: string } {
  const vault = new PiiVault();
  const np = { restore: (t: string, s: string) => vault.restore(t, s) } as unknown as NullPii;
  return { np, sessionId: vault.createSession() };
}

/** Upstream that records how many chunks the relay has pulled. */
function upstream(frames: string[], pulled: { n: number }): AsyncIterable<Uint8Array> {
  return (async function* () {
    for (const frame of frames) {
      pulled.n += 1;
      yield encoder.encode(frame);
    }
  })();
}

/** A write whose frames are accepted only when `release()` is called. */
function slowWrite() {
  const written: string[] = [];
  let release: () => void = () => {};
  const write = (frame: string): Promise<void> => {
    written.push(frame);
    return new Promise<void>((resolve) => {
      release = resolve;
    });
  };
  return { written, write, release: () => release() };
}

const ANTHROPIC_FRAMES = [
  'event: ping\ndata: {"type":"ping"}\n\n',
  'event: message_stop\ndata: {"type":"message_stop"}\n\n',
];
const OPENAI_FRAMES = [
  'data: {"id":"c","object":"chat.completion.chunk","choices":[]}\n\n',
  'data: [DONE]\n\n',
];

describe('relays wait for each frame to be accepted', () => {
  it.each([
    ['anthropic', relaySseStream, ANTHROPIC_FRAMES],
    ['openai', relayChatSseStream, OPENAI_FRAMES],
  ] as const)('%s relay reads no further while a write is pending', async (_, relay, frames) => {
    const { np, sessionId } = engine();
    const pulled = { n: 0 };
    const out = slowWrite();
    const done = relay({ np, sessionId, upstream: upstream(frames, pulled), write: out.write });
    await new Promise((r) => setTimeout(r, 10));
    expect(out.written).toHaveLength(1);
    expect(pulled.n).toBe(1);
    out.release();
    await new Promise((r) => setTimeout(r, 10));
    out.release();
    await done;
    expect(out.written).toHaveLength(2);
  });
});

/** Minimal `ServerResponse` stand-in: `write` reports a full buffer. */
function fakeSocket(accepts: boolean) {
  const raw = new EventEmitter() as EventEmitter & {
    write: (s: string) => boolean;
    destroyed: boolean;
    writableEnded: boolean;
  };
  raw.write = () => accepts;
  raw.destroyed = false;
  raw.writableEnded = false;
  return raw;
}

describe('writeFrame', () => {
  it('returns at once when the socket accepts the frame', async () => {
    await expect(writeFrame(fakeSocket(true) as unknown as ServerResponse, 'x')).resolves.toBe(
      undefined,
    );
  });

  it("waits for 'drain' when the socket is full", async () => {
    const raw = fakeSocket(false);
    let settled = false;
    const p = writeFrame(raw as unknown as ServerResponse, 'x').then(() => {
      settled = true;
    });
    await new Promise((r) => setTimeout(r, 5));
    expect(settled).toBe(false);
    raw.emit('drain');
    await p;
    expect(settled).toBe(true);
    expect(raw.listenerCount('drain') + raw.listenerCount('close')).toBe(0);
  });

  it('fails when the client goes away while waiting, or is already gone', async () => {
    const raw = fakeSocket(false);
    const p = writeFrame(raw as unknown as ServerResponse, 'x');
    raw.emit('close');
    await expect(p).rejects.toThrow(/client closed/);
    const gone = fakeSocket(true);
    gone.destroyed = true;
    await expect(writeFrame(gone as unknown as ServerResponse, 'x')).rejects.toThrow(
      /client closed/,
    );
  });
});
