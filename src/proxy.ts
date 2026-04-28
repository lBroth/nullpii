// SPDX-License-Identifier: Apache-2.0
//
// HTTP proxy that sits between any Anthropic SDK client (including
// Claude Code) and `api.anthropic.com`. Rewrites every outgoing
// `messages.create` body so PII becomes vault placeholders before the
// request leaves the machine, then restores the originals in the
// response before handing it back to the client.
//
// Usage: point `ANTHROPIC_BASE_URL=http://localhost:<port>` at this
// proxy. The Anthropic SDK respects that env var verbatim, no code
// changes required.
//
// v1 caveat: streaming responses (`stream: true`) are forced to
// non-streaming. The SDK still returns a single Message; the client
// loses progressive token output but gets PII restoration. Streaming
// support that re-tokenises SSE chunks in-flight is on the roadmap.
import { type IncomingMessage, type ServerResponse, createServer as httpServer } from 'node:http';
import { request as httpsRequest } from 'node:https';
import { URL } from 'node:url';
import debug from 'debug';
import type { NullPii } from './nullpii.js';

const log = debug('nullpii:proxy');

const UPSTREAM_HOST = 'api.anthropic.com';
const UPSTREAM_PORT = 443;
const SANITIZE_PATHS = new Set(['/v1/messages']);

interface SanitizedConversation {
  readonly sessionId: string;
}

/** Start the proxy on the given port. Resolves once the listen call
 * succeeds. Caller is responsible for SIGTERM/SIGINT handling. */
export function startProxy(engine: NullPii, port: number): Promise<{ close: () => Promise<void> }> {
  return new Promise((resolve, reject) => {
    const server = httpServer((req, res) => {
      handleRequest(engine, req, res).catch((err) => {
        log('handler crashed: %o', err);
        if (!res.headersSent) {
          res.writeHead(500, { 'content-type': 'application/json' });
          res.end(JSON.stringify({ error: { message: `proxy crashed: ${asMessage(err)}` } }));
        }
      });
    });
    server.on('error', reject);
    server.listen(port, () => {
      process.stderr.write(`nullpii proxy listening on http://localhost:${port}\n`);
      resolve({
        close: () =>
          new Promise<void>((r) => {
            server.close(() => r());
          }),
      });
    });
  });
}

async function handleRequest(
  engine: NullPii,
  req: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  const method = req.method ?? 'GET';
  const url = new URL(req.url ?? '/', 'http://localhost');
  const sanitizable = method === 'POST' && SANITIZE_PATHS.has(url.pathname);

  const inboundBody = await readAll(req);
  let sanitizedBody = inboundBody;
  let convo: SanitizedConversation | undefined;

  if (sanitizable && inboundBody.length > 0) {
    try {
      const parsed = JSON.parse(inboundBody.toString('utf8'));
      const out = await sanitizeBody(engine, parsed);
      convo = out.convo;
      // Streaming is now supported — see handleSseStream below.
      sanitizedBody = Buffer.from(JSON.stringify(parsed));
    } catch (err) {
      log('inbound parse failed, forwarding as-is: %o', err);
      sanitizedBody = inboundBody;
    }
  }

  const upstreamHeaders = filterRequestHeaders(req.headers, sanitizedBody.length);
  const upReq = httpsRequest(
    {
      hostname: UPSTREAM_HOST,
      port: UPSTREAM_PORT,
      method,
      path: req.url,
      headers: upstreamHeaders,
    },
    (upRes) => {
      handleUpstreamResponse(engine, convo, upRes, res).catch((err) => {
        log('upstream handler crashed: %o', err);
        if (!res.headersSent) {
          res.writeHead(502, { 'content-type': 'application/json' });
          res.end(JSON.stringify({ error: { message: `proxy upstream: ${asMessage(err)}` } }));
        }
      });
    },
  );
  upReq.on('error', (err) => {
    log('upstream connect failed: %o', err);
    if (!res.headersSent) {
      res.writeHead(502, { 'content-type': 'application/json' });
      res.end(JSON.stringify({ error: { message: `proxy connect: ${err.message}` } }));
    }
  });
  upReq.write(sanitizedBody);
  upReq.end();
}

interface SanitizeBodyResult {
  readonly convo: SanitizedConversation | undefined;
}

async function sanitizeBody(
  engine: NullPii,
  body: { messages?: Array<{ content?: unknown }>; system?: unknown },
): Promise<SanitizeBodyResult> {
  let sessionId: string | undefined;
  const sanitizeOne = async (text: string): Promise<string> => {
    const result = await engine.sanitize(text, sessionId);
    sessionId = result.sessionId;
    return result.sanitized;
  };

  if (typeof body.system === 'string' && body.system.length > 0) {
    body.system = await sanitizeOne(body.system);
  } else if (Array.isArray(body.system)) {
    for (const block of body.system as Array<{ type?: string; text?: unknown }>) {
      if (block.type === 'text' && typeof block.text === 'string') {
        block.text = await sanitizeOne(block.text);
      }
    }
  }

  if (Array.isArray(body.messages)) {
    for (const msg of body.messages) {
      if (typeof msg.content === 'string') {
        msg.content = await sanitizeOne(msg.content);
      } else if (Array.isArray(msg.content)) {
        for (const block of msg.content as Array<{ type?: string; text?: unknown }>) {
          if (block.type === 'text' && typeof block.text === 'string') {
            block.text = await sanitizeOne(block.text);
          }
        }
      }
    }
  }
  return { convo: sessionId !== undefined ? { sessionId } : undefined };
}

async function handleUpstreamResponse(
  engine: NullPii,
  convo: SanitizedConversation | undefined,
  upRes: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  const contentType = String(upRes.headers['content-type'] ?? '');
  if (convo !== undefined && contentType.includes('text/event-stream')) {
    return handleSseStream(engine, convo.sessionId, upRes, res);
  }

  const buf = await readAll(upRes);
  const headers: Record<string, string | string[] | undefined> = {};
  for (const [k, v] of Object.entries(upRes.headers)) {
    const lower = k.toLowerCase();
    if (lower === 'content-length' || lower === 'transfer-encoding') continue;
    headers[k] = v;
  }

  if (convo === undefined) {
    res.writeHead(upRes.statusCode ?? 500, headers);
    res.end(buf);
    return;
  }

  const text = buf.toString('utf8');
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    // not JSON — pass through
    res.writeHead(upRes.statusCode ?? 500, headers);
    res.end(buf);
    return;
  }

  restoreBody(engine, parsed, convo.sessionId);
  const restored = Buffer.from(JSON.stringify(parsed));
  headers['content-length'] = String(restored.length);
  res.writeHead(upRes.statusCode ?? 500, headers);
  res.end(restored);
}

function restoreBody(engine: NullPii, body: unknown, sessionId: string): void {
  if (body === null || typeof body !== 'object') return;
  const obj = body as Record<string, unknown>;
  const content = obj.content;
  if (Array.isArray(content)) {
    for (const block of content as Array<Record<string, unknown>>) {
      if (block.type === 'text' && typeof block.text === 'string') {
        block.text = engine.restore(block.text, sessionId).restored;
      } else if (block.type === 'tool_use') {
        // Tool calls (Write/Edit/Bash/etc.) carry the file body /
        // command in `input`. The model only ever saw placeholders, so
        // we MUST restore the originals here or the tool runs against
        // the redacted text.
        if (typeof block.input === 'object' && block.input !== null) {
          restoreObject(engine, block.input as Record<string, unknown>, sessionId);
        }
      } else if (block.type === 'tool_result') {
        // Some tool results are reflected back into the conversation
        // before the final text reply — keep them readable too.
        const tcontent = block.content;
        if (typeof tcontent === 'string') {
          block.content = engine.restore(tcontent, sessionId).restored;
        } else if (Array.isArray(tcontent)) {
          for (const tb of tcontent as Array<Record<string, unknown>>) {
            if (tb.type === 'text' && typeof tb.text === 'string') {
              tb.text = engine.restore(tb.text, sessionId).restored;
            }
          }
        }
      }
    }
  }
}

function restoreObject(engine: NullPii, obj: Record<string, unknown>, sessionId: string): void {
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v === 'string') {
      obj[k] = engine.restore(v, sessionId).restored;
    } else if (typeof v === 'object' && v !== null) {
      restoreObject(engine, v as Record<string, unknown>, sessionId);
    }
  }
}

function readAll(stream: IncomingMessage): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    stream.on('data', (c: Buffer) => chunks.push(c));
    stream.on('end', () => resolve(Buffer.concat(chunks)));
    stream.on('error', reject);
  });
}

function filterRequestHeaders(
  headers: IncomingMessage['headers'],
  contentLength: number,
): Record<string, string | string[]> {
  const out: Record<string, string | string[]> = {};
  for (const [k, v] of Object.entries(headers)) {
    if (v === undefined) continue;
    const lower = k.toLowerCase();
    if (lower === 'host' || lower === 'content-length' || lower === 'connection') continue;
    out[k] = v;
  }
  out.host = UPSTREAM_HOST;
  out['content-length'] = String(contentLength);
  return out;
}

function asMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

// ─── SSE streaming ──────────────────────────────────────────────────
//
// Anthropic returns text/event-stream when the request body has
// `stream: true`. Each event is a `event: <name>\ndata: <json>\n\n`
// frame. For text content we restore placeholders in-flight (with a
// trailing buffer so a placeholder split across deltas isn't emitted
// half-restored). For tool_use input we accumulate `input_json_delta`
// per content_block_index, parse the assembled JSON at
// content_block_stop, restore strings inside, and emit a single
// replacement input_json_delta covering the rebuilt JSON.

interface BlockState {
  /** "text" | "tool_use" | other */
  readonly kind: string;
  /** Accumulated text/json that has not been emitted yet. */
  buffer: string;
  /** Full text accumulated so far (for placeholder restoration). */
  emittedSoFar: string;
}

// Maximum length of a partial-placeholder tail to keep buffered.
// `[[NULLPII:private_address:9999]]` ≈ 35 chars; pad generously.
const PLACEHOLDER_BUFFER_TAIL = 64;

function handleSseStream(
  engine: NullPii,
  sessionId: string,
  upRes: IncomingMessage,
  res: ServerResponse,
): Promise<void> {
  return new Promise((resolve) => {
    // Forward upstream headers (minus length/encoding).
    const headers: Record<string, string | string[] | undefined> = {};
    for (const [k, v] of Object.entries(upRes.headers)) {
      const lower = k.toLowerCase();
      if (lower === 'content-length' || lower === 'transfer-encoding') continue;
      headers[k] = v;
    }
    res.writeHead(upRes.statusCode ?? 500, headers);

    const blocks = new Map<number, BlockState>();
    let buffer = '';

    upRes.setEncoding('utf8');
    upRes.on('data', (chunk: string) => {
      buffer += chunk;
      // Frames are separated by \n\n.
      for (;;) {
        const idx = buffer.indexOf('\n\n');
        if (idx < 0) break;
        const frame = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const out = transformFrame(engine, sessionId, frame, blocks);
        if (out !== null) res.write(`${out}\n\n`);
      }
    });
    upRes.on('end', () => {
      if (buffer.trim().length > 0) {
        const out = transformFrame(engine, sessionId, buffer, blocks);
        if (out !== null) res.write(out);
      }
      res.end();
      resolve();
    });
    upRes.on('error', () => {
      res.end();
      resolve();
    });
  });
}

function transformFrame(
  engine: NullPii,
  sessionId: string,
  frame: string,
  blocks: Map<number, BlockState>,
): string | null {
  if (frame.length === 0) return null;
  let eventName = '';
  let dataLine = '';
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim();
    else if (line.startsWith('data:')) dataLine += line.slice(5).trim();
  }
  if (dataLine === '') return frame;

  let payload: Record<string, unknown>;
  try {
    payload = JSON.parse(dataLine) as Record<string, unknown>;
  } catch {
    return frame;
  }

  const eventType = (payload.type as string | undefined) ?? eventName;
  const index = typeof payload.index === 'number' ? payload.index : -1;

  switch (eventType) {
    case 'content_block_start': {
      const cb = payload.content_block as { type?: string } | undefined;
      const kind = cb?.type ?? 'unknown';
      blocks.set(index, { kind, buffer: '', emittedSoFar: '' });
      return frame;
    }
    case 'content_block_delta': {
      const block = blocks.get(index);
      if (block === undefined) return frame;
      const delta = payload.delta as Record<string, unknown> | undefined;
      if (delta === undefined) return frame;
      if (delta.type === 'text_delta' && typeof delta.text === 'string') {
        const restored = restoreStreamingText(engine, sessionId, block, delta.text);
        if (restored === null) return null; // hold buffer for next chunk
        delta.text = restored;
        return reserialize(eventName, payload);
      }
      if (delta.type === 'input_json_delta' && typeof delta.partial_json === 'string') {
        // Accumulate; emit nothing now. We rebuild at content_block_stop.
        block.buffer += delta.partial_json;
        return null;
      }
      return frame;
    }
    case 'content_block_stop': {
      const block = blocks.get(index);
      if (block === undefined) return frame;
      let prefix: string | null = null;
      if (block.kind === 'text' && block.buffer.length > 0) {
        // Flush any tail held in the placeholder buffer.
        const tail = engine.restore(block.buffer, sessionId).restored;
        block.emittedSoFar += tail;
        prefix = renderTextDelta(index, tail);
        block.buffer = '';
      } else if (block.kind === 'tool_use' && block.buffer.length > 0) {
        // Parse the assembled JSON, restore strings, re-emit.
        try {
          const obj = JSON.parse(block.buffer) as Record<string, unknown>;
          restoreObject(engine, obj, sessionId);
          const restoredJson = JSON.stringify(obj);
          prefix = renderInputJsonDelta(index, restoredJson);
        } catch {
          // partial / malformed — emit raw
          prefix = renderInputJsonDelta(index, block.buffer);
        }
        block.buffer = '';
      }
      blocks.delete(index);
      if (prefix !== null) return `${prefix}\n\n${frame}`;
      return frame;
    }
    default:
      return frame;
  }
}

function restoreStreamingText(
  engine: NullPii,
  sessionId: string,
  block: BlockState,
  delta: string,
): string | null {
  block.buffer += delta;
  const buf = block.buffer;
  // Find the safe split point: the buffer up to where any potential
  // open placeholder might still be incomplete. If the tail contains
  // `[[NULLPII` without a closing `]]`, hold it; otherwise emit all.
  const lastOpen = buf.lastIndexOf('[[');
  let safeEnd = buf.length;
  if (lastOpen >= 0) {
    const closing = buf.indexOf(']]', lastOpen);
    if (closing < 0) {
      // Open without close — keep tail buffered.
      safeEnd = lastOpen;
    }
  }
  // Cap the held tail so a malformed pattern can't grow forever.
  if (buf.length - safeEnd > PLACEHOLDER_BUFFER_TAIL) {
    safeEnd = buf.length;
  }
  if (safeEnd === 0) return null;
  const head = buf.slice(0, safeEnd);
  block.buffer = buf.slice(safeEnd);
  const restored = engine.restore(head, sessionId).restored;
  block.emittedSoFar += restored;
  return restored;
}

function renderTextDelta(index: number, text: string): string {
  return `event: content_block_delta\ndata: ${JSON.stringify({
    type: 'content_block_delta',
    index,
    delta: { type: 'text_delta', text },
  })}`;
}

function renderInputJsonDelta(index: number, partialJson: string): string {
  return `event: content_block_delta\ndata: ${JSON.stringify({
    type: 'content_block_delta',
    index,
    delta: { type: 'input_json_delta', partial_json: partialJson },
  })}`;
}

function reserialize(eventName: string, payload: Record<string, unknown>): string {
  const ev = eventName !== '' ? `event: ${eventName}\n` : '';
  return `${ev}data: ${JSON.stringify(payload)}`;
}
