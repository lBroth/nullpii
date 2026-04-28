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
      // v1: force non-streaming so we can restore the response body.
      if (parsed.stream === true) {
        parsed.stream = false;
      }
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
      }
    }
  }
  // Tool inputs / outputs may also carry text — keep restore-friendly.
  const toolUses = obj.tool_uses;
  if (Array.isArray(toolUses)) {
    for (const tu of toolUses as Array<Record<string, unknown>>) {
      if (typeof tu.input === 'object' && tu.input !== null) {
        restoreObject(engine, tu.input as Record<string, unknown>, sessionId);
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
