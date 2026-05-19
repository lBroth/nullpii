// SPDX-License-Identifier: Apache-2.0

import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { NullPii } from 'nullpii';
import { printRequestSummary } from '../pretty-log.js';
import { restoreResponse, sanitizeRequest } from '../sanitizer.js';
import { relaySseStream } from '../sse-relay.js';
import { logInboundResponse, logInboundSseChunk, logOutboundRequest } from '../traffic-log.js';
import type { AnthropicRequest, AnthropicResponse } from '../types.js';
import { type Fetch, buildUpstreamHeaders, forwardToAnthropic } from '../upstream.js';

export interface AnthropicRouteOptions {
  readonly np: NullPii;
  readonly upstreamBaseUrl: string;
  readonly fetchImpl: Fetch;
  /** When true, dump sanitized request body + raw upstream response
   * (placeholder-bearing) to stdout. Never logs real PII. */
  readonly logTraffic: boolean;
}

/** Headers from Anthropic that diagnose rate-limit / quota failures.
 * Forwarded verbatim so the client sees `retry-after` + the full
 * `anthropic-ratelimit-*` family on 429 / 529 responses. */
const UPSTREAM_ERROR_HEADERS = [
  'content-type',
  'retry-after',
  'anthropic-ratelimit-requests-limit',
  'anthropic-ratelimit-requests-remaining',
  'anthropic-ratelimit-requests-reset',
  'anthropic-ratelimit-input-tokens-limit',
  'anthropic-ratelimit-input-tokens-remaining',
  'anthropic-ratelimit-input-tokens-reset',
  'anthropic-ratelimit-output-tokens-limit',
  'anthropic-ratelimit-output-tokens-remaining',
  'anthropic-ratelimit-output-tokens-reset',
];

function forwardUpstreamErrorHeaders(reply: FastifyReply, upstream: Headers): void {
  for (const name of UPSTREAM_ERROR_HEADERS) {
    const v = upstream.get(name);
    if (v !== null) reply.header(name, v);
  }
  if (upstream.get('content-type') === null) reply.header('content-type', 'application/json');
}

export async function registerAnthropicRoute(
  app: FastifyInstance,
  opts: AnthropicRouteOptions,
): Promise<void> {
  const { np, upstreamBaseUrl, fetchImpl, logTraffic } = opts;

  app.post('/v1/messages', async (req, reply) => {
    const body = req.body as AnthropicRequest;
    const isStream = (body as { stream?: unknown }).stream === true;

    if (isStream) {
      return handleStreaming(req, reply, body, np, upstreamBaseUrl, fetchImpl, logTraffic);
    }
    return handleNonStreaming(req, reply, body, np, upstreamBaseUrl, fetchImpl, logTraffic);
  });

  // `count_tokens` does NOT need restoration — the response is `{input_tokens: N}`,
  // no PII, no placeholders. But sanitising the request body still matters: a
  // count-tokens probe over PII-bearing text would leak the text to the upstream
  // if forwarded raw. Sanitise → forward → return upstream response verbatim.
  app.post('/v1/messages/count_tokens', async (req, reply) => {
    const body = req.body as AnthropicRequest;
    const sanitized = await sanitizeRequest(np, body);
    const headers = buildUpstreamHeaders(
      req.headers as Record<string, string | string[] | undefined>,
    );

    let upstream: Awaited<ReturnType<typeof forwardToAnthropic>>;
    try {
      upstream = await forwardToAnthropic(
        fetchImpl,
        upstreamBaseUrl,
        '/v1/messages/count_tokens',
        sanitized.body,
        headers,
      );
    } catch (err) {
      np.destroySession(sanitized.sessionId);
      const msg = err instanceof Error ? err.message : String(err);
      return reply.code(502).send({
        type: 'error',
        error: { type: 'nullpii_upstream_error', message: msg },
      });
    }
    np.destroySession(sanitized.sessionId);
    reply.code(upstream.status);
    reply.header('content-type', upstream.headers.get('content-type') ?? 'application/json');
    return upstream.text;
  });
}

async function handleNonStreaming(
  req: FastifyRequest,
  reply: FastifyReply,
  body: AnthropicRequest,
  np: NullPii,
  upstreamBaseUrl: string,
  fetchImpl: Fetch,
  logTraffic: boolean,
): Promise<unknown> {
  const sanitized = await sanitizeRequest(np, body);
  const reqId = typeof req.id === 'string' ? req.id : undefined;
  if (logTraffic) logOutboundRequest(sanitized.body, reqId);
  const headers = buildUpstreamHeaders(
    req.headers as Record<string, string | string[] | undefined>,
  );

  let upstream: Awaited<ReturnType<typeof forwardToAnthropic>>;
  try {
    upstream = await forwardToAnthropic(
      fetchImpl,
      upstreamBaseUrl,
      '/v1/messages',
      sanitized.body,
      headers,
    );
  } catch (err) {
    np.destroySession(sanitized.sessionId);
    const msg = err instanceof Error ? err.message : String(err);
    return reply.code(502).send({
      type: 'error',
      error: { type: 'nullpii_upstream_error', message: msg },
    });
  }

  if (upstream.status < 200 || upstream.status >= 300) {
    np.destroySession(sanitized.sessionId);
    reply.code(upstream.status);
    forwardUpstreamErrorHeaders(reply, upstream.headers);
    req.log.warn(
      {
        upstreamStatus: upstream.status,
        retryAfter: upstream.headers.get('retry-after') ?? undefined,
        rateLimitReset: upstream.headers.get('anthropic-ratelimit-requests-reset') ?? undefined,
        body: upstream.text.slice(0, 500),
      },
      'anthropic.upstream_error',
    );
    return upstream.text;
  }

  if (logTraffic) logInboundResponse(upstream.text, reqId);

  let parsed: AnthropicResponse;
  try {
    parsed = JSON.parse(upstream.text) as AnthropicResponse;
  } catch {
    np.destroySession(sanitized.sessionId);
    return reply.code(502).send({
      type: 'error',
      error: {
        type: 'nullpii_upstream_error',
        message: 'Upstream returned 2xx with a non-JSON body.',
      },
    });
  }

  const restored = restoreResponse(np, parsed, sanitized.sessionId);
  np.destroySession(sanitized.sessionId);

  req.log.info(
    {
      captured: sanitized.captured,
      capturedByLabel: sanitized.capturedByLabel,
      replacements: restored.replacements,
      replacementsByLabel: restored.replacementsByLabel,
      unknownPlaceholders: restored.unknownPlaceholders,
      foreignPlaceholders: restored.foreignPlaceholders,
    },
    'anthropic.messages.restored',
  );
  const summaryBase = {
    mode: 'JSON' as const,
    captured: sanitized.captured,
    capturedByLabel: sanitized.capturedByLabel,
    restored: restored.replacements,
    restoredByLabel: restored.replacementsByLabel,
    unknownPlaceholders: restored.unknownPlaceholders,
    foreignPlaceholders: restored.foreignPlaceholders,
  };
  printRequestSummary(reqId !== undefined ? { ...summaryBase, reqId } : summaryBase);

  return restored.body;
}

/**
 * Streaming path. Pipes the upstream SSE stream through `relaySseStream`
 * which buffers placeholders that straddle SSE-frame / delta boundaries
 * (`{{PII_PRIV` | next frame | `ATE_PERSON_0_…}}`) and emits restored
 * `content_block_delta` events downstream.
 *
 * The Fastify reply is hijacked so the route owns the response socket
 * for the full duration of the stream — Fastify's regular reply
 * machinery would buffer.
 */
async function handleStreaming(
  req: FastifyRequest,
  reply: FastifyReply,
  body: AnthropicRequest,
  np: NullPii,
  upstreamBaseUrl: string,
  fetchImpl: Fetch,
  logTraffic: boolean,
): Promise<unknown> {
  const sanitized = await sanitizeRequest(np, body);
  const reqId = typeof req.id === 'string' ? req.id : undefined;
  if (logTraffic) logOutboundRequest(sanitized.body, reqId);
  const headers = buildUpstreamHeaders(
    req.headers as Record<string, string | string[] | undefined>,
  );

  let upstreamResp: Response;
  try {
    upstreamResp = await fetchImpl(`${upstreamBaseUrl}/v1/messages`, {
      method: 'POST',
      headers,
      body: JSON.stringify(sanitized.body),
    });
  } catch (err) {
    np.destroySession(sanitized.sessionId);
    const msg = err instanceof Error ? err.message : String(err);
    return reply.code(502).send({
      type: 'error',
      error: { type: 'nullpii_upstream_error', message: msg },
    });
  }

  // Non-2xx upstream — passthrough the error body verbatim. Anthropic
  // streams errors as a JSON body (not SSE) under most failures.
  if (upstreamResp.status < 200 || upstreamResp.status >= 300) {
    np.destroySession(sanitized.sessionId);
    const text = await upstreamResp.text();
    reply.code(upstreamResp.status);
    forwardUpstreamErrorHeaders(reply, upstreamResp.headers);
    req.log.warn(
      {
        upstreamStatus: upstreamResp.status,
        retryAfter: upstreamResp.headers.get('retry-after') ?? undefined,
        rateLimitReset: upstreamResp.headers.get('anthropic-ratelimit-requests-reset') ?? undefined,
        body: text.slice(0, 500),
      },
      'anthropic.upstream_error',
    );
    return text;
  }

  if (upstreamResp.body === null) {
    np.destroySession(sanitized.sessionId);
    return reply.code(502).send({
      type: 'error',
      error: {
        type: 'nullpii_upstream_error',
        message: 'Upstream returned 2xx without a body.',
      },
    });
  }

  // SSE response. Surface the original upstream content-type
  // (`text/event-stream`) + standard streaming headers, then hijack
  // the socket and pipe events through.
  reply.raw.statusCode = 200;
  reply.raw.setHeader(
    'content-type',
    upstreamResp.headers.get('content-type') ?? 'text/event-stream',
  );
  reply.raw.setHeader('cache-control', 'no-cache');
  reply.raw.setHeader('connection', 'keep-alive');
  reply.hijack();

  try {
    const counters = await relaySseStream({
      np,
      sessionId: sanitized.sessionId,
      upstream: upstreamResp.body as unknown as AsyncIterable<Uint8Array>,
      write: (frame) => reply.raw.write(frame),
      ...(logTraffic ? { onUpstreamChunk: (c) => logInboundSseChunk(c, reqId) } : {}),
    });
    req.log.info(
      {
        captured: sanitized.captured,
        capturedByLabel: sanitized.capturedByLabel,
        replacements: counters.replacements,
        replacementsByLabel: counters.replacementsByLabel,
        unknownPlaceholders: counters.unknownPlaceholders,
        foreignPlaceholders: counters.foreignPlaceholders,
      },
      'anthropic.messages.streamed',
    );
    const sseSummary = {
      mode: 'SSE' as const,
      captured: sanitized.captured,
      capturedByLabel: sanitized.capturedByLabel,
      restored: counters.replacements,
      restoredByLabel: counters.replacementsByLabel,
      unknownPlaceholders: counters.unknownPlaceholders,
      foreignPlaceholders: counters.foreignPlaceholders,
    };
    printRequestSummary(reqId !== undefined ? { ...sseSummary, reqId } : sseSummary);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    req.log.error({ errMsg: msg }, 'anthropic.messages.stream_error');
  } finally {
    np.destroySession(sanitized.sessionId);
    reply.raw.end();
  }
  return reply;
}
