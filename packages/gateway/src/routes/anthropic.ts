// SPDX-License-Identifier: Apache-2.0

import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { NullPii } from 'nullpii';
import {
  type SanitizedRequest,
  isRecord,
  parseJson,
  restoreResponse,
  sanitizeRequest,
} from '../sanitizer.js';
import { relaySseStream } from '../sse-relay.js';
import {
  logInboundResponse,
  logInboundSseChunk,
  logOutboundHeaders,
  logOutboundRequest,
} from '../traffic-log.js';
import type { AnthropicRequest, AnthropicResponse } from '../types.js';
import {
  type Fetch,
  type UpstreamCall,
  buildUpstreamHeaders,
  extractQuery,
  forwardToUpstream,
} from '../upstream.js';
import {
  UPSTREAM_ERROR_TYPE,
  UPSTREAM_FAILURE_STATUS,
  errorMessage,
  isSuccess,
  logRoundTrip,
  openSseReply,
  upstreamErrorLogFields,
  watchClientClose,
  writeFrame,
} from './common.js';

export interface AnthropicRouteOptions {
  readonly np: NullPii;
  readonly upstreamBaseUrl: string;
  readonly fetchImpl: Fetch;
  /** When true, dump the request as forwarded and the raw upstream
   * response to stdout (`traffic-log.ts`). Not free of personal data:
   * they hold whatever nullpii did not mask. */
  readonly logTraffic: boolean;
  /** Tools whose arguments get real values back; default
   * `DEFAULT_RESTORE_TOOLS`. Any other tool keeps its placeholders. */
  readonly restoreTools?: ReadonlySet<string>;
  /** Append `LLM_PRESERVATION_HINT` when something was masked. Default true. */
  readonly appendHint?: boolean;
}

const MESSAGES_PATH = '/v1/messages';
const COUNT_TOKENS_PATH = '/v1/messages/count_tokens';
const JSON_CONTENT_TYPE = 'application/json';

/** Headers from Anthropic that diagnose rate-limit / quota failures.
 * Forwarded verbatim so the client sees `retry-after` + the full
 * `anthropic-ratelimit-*` family on 429 / 529 responses. */
const UPSTREAM_ERROR_HEADERS = [
  'content-type',
  'request-id',
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

/** Everything one proxied call needs once its request is sanitized. */
interface MessagesCall {
  readonly req: FastifyRequest;
  readonly reply: FastifyReply;
  readonly opts: AnthropicRouteOptions;
  readonly sanitized: SanitizedRequest;
  /** Upstream path plus the client's query string. */
  readonly path: string;
  readonly headers: Record<string, string>;
  readonly reqId: string | undefined;
}

/**
 * Register the Anthropic Messages routes on `app`: `POST /v1/messages`
 * (JSON and SSE) and `POST /v1/messages/count_tokens`. Each request is
 * sanitized into its own vault session, forwarded to `upstreamBaseUrl`,
 * restored (Messages only: a token count carries no text) and its session
 * destroyed on every path.
 *
 * @param app - the Fastify instance (see `buildServer`).
 * @param opts - engine, upstream, `fetch`, traffic dump, restore policy.
 */
export async function registerAnthropicRoute(
  app: FastifyInstance,
  opts: AnthropicRouteOptions,
): Promise<void> {
  const { np } = opts;

  app.post(MESSAGES_PATH, async (req, reply) => {
    const body = req.body as AnthropicRequest;
    // One vault session per request. `sanitizeRequest` drops it itself if
    // it throws; from here on this `finally` drops it on every path:
    // restored, upstream error, fetch failure, stream end or abort.
    const sanitized = await sanitizeRequest(np, body, opts.appendHint);
    try {
      const call = prepareCall(req, reply, opts, sanitized, MESSAGES_PATH);
      logOutbound(call);
      return body.stream === true ? await handleStreaming(call) : await handleNonStreaming(call);
    } finally {
      np.destroySession(sanitized.sessionId);
    }
  });

  // `count_tokens` does NOT need restoration — the response is
  // `{input_tokens: N}`, no PII, no placeholders. But sanitising the
  // request body still matters: a count-tokens probe over PII-bearing text
  // would leak the text to the upstream if forwarded raw.
  app.post(COUNT_TOKENS_PATH, async (req, reply) => {
    const sanitized = await sanitizeRequest(np, req.body as AnthropicRequest, opts.appendHint);
    try {
      return await forwardCountTokens(prepareCall(req, reply, opts, sanitized, COUNT_TOKENS_PATH));
    } finally {
      np.destroySession(sanitized.sessionId);
    }
  });
}

function prepareCall(
  req: FastifyRequest,
  reply: FastifyReply,
  opts: AnthropicRouteOptions,
  sanitized: SanitizedRequest,
  path: string,
): MessagesCall {
  const headers = buildUpstreamHeaders(
    req.headers as Record<string, string | string[] | undefined>,
  );
  // Preserve the original query string (`?beta=true`, etc). Anthropic
  // routes feature-gates + subscription scopes off the query, so dropping
  // it makes the upstream see a different request shape than the client
  // sent and silently downgrades / rate-limits.
  const fullPath = `${path}${extractQuery(req.url)}`;
  const reqId = typeof req.id === 'string' ? req.id : undefined;
  return { req, reply, opts, sanitized, path: fullPath, headers, reqId };
}

function logOutbound(call: MessagesCall): void {
  if (!call.opts.logTraffic) return;
  logOutboundRequest(call.sanitized.body, call.reqId);
  logOutboundHeaders(call.headers, call.reqId);
}

/** Forward the sanitized body as JSON; `undefined` when the upstream
 * could not be reached, after replying 502. */
async function forwardJson(call: MessagesCall): Promise<UpstreamCall | undefined> {
  const { opts } = call;
  try {
    return await forwardToUpstream(
      opts.fetchImpl,
      opts.upstreamBaseUrl,
      call.path,
      call.sanitized.body,
      call.headers,
    );
  } catch (err) {
    sendUpstreamFailure(call.reply, errorMessage(err));
    return undefined;
  }
}

async function forwardCountTokens(call: MessagesCall): Promise<unknown> {
  const upstream = await forwardJson(call);
  if (upstream === undefined) return call.reply;
  call.reply.code(upstream.status);
  call.reply.header('content-type', upstream.headers.get('content-type') ?? JSON_CONTENT_TYPE);
  return upstream.text;
}

async function handleNonStreaming(call: MessagesCall): Promise<unknown> {
  const { opts, sanitized } = call;
  const upstream = await forwardJson(call);
  if (upstream === undefined) return call.reply;
  if (!isSuccess(upstream.status)) {
    return passThroughError(call, upstream.status, upstream.headers, upstream.text);
  }
  if (opts.logTraffic) logInboundResponse(upstream.text, call.reqId);
  const parsed = parseJson(upstream.text);
  if (parsed === undefined || !isRecord(parsed.value)) {
    return sendUpstreamFailure(call.reply, 'Upstream returned 2xx with a non-JSON body.');
  }
  const response = parsed.value as unknown as AnthropicResponse;
  const restored = restoreResponse(opts.np, response, sanitized.sessionId, opts.restoreTools);
  logRoundTrip({
    req: call.req,
    reqId: call.reqId,
    sanitized,
    mode: 'JSON',
    event: 'anthropic.messages.restored',
    counts: restored,
  });
  return restored.body;
}

/**
 * Streaming path: the upstream SSE stream goes through `relaySseStream`,
 * which holds placeholders split across deltas and frames
 * (`{{PII_PRIV` | next frame | `ATE_PERSON_0_…}}`) and emits restored
 * deltas. The reply is hijacked so the route owns the socket for the
 * whole stream; a client that disconnects cancels the upstream call.
 */
async function handleStreaming(call: MessagesCall): Promise<unknown> {
  const client = watchClientClose(call.reply);
  try {
    return await streamFromUpstream(call, client.abort);
  } finally {
    client.release();
  }
}

async function streamFromUpstream(call: MessagesCall, abort: AbortController): Promise<unknown> {
  const { reply, opts } = call;
  let upstream: Response;
  try {
    upstream = await opts.fetchImpl(`${opts.upstreamBaseUrl}${call.path}`, {
      method: 'POST',
      headers: call.headers,
      body: JSON.stringify(call.sanitized.body),
      signal: abort.signal,
    });
  } catch (err) {
    return sendUpstreamFailure(reply, errorMessage(err));
  }
  // Anthropic streams most errors as a JSON body, not as SSE.
  if (!isSuccess(upstream.status)) {
    return passThroughError(call, upstream.status, upstream.headers, await upstream.text());
  }
  if (upstream.body === null) {
    return sendUpstreamFailure(reply, 'Upstream returned 2xx without a body.');
  }
  openSseReply(reply, upstream.headers.get('content-type'));
  await relayToClient(call, upstream.body as unknown as AsyncIterable<Uint8Array>, abort);
  return reply;
}

async function relayToClient(
  call: MessagesCall,
  upstream: AsyncIterable<Uint8Array>,
  abort: AbortController,
): Promise<void> {
  const { req, reply, opts, sanitized } = call;
  try {
    const counters = await relaySseStream({
      np: opts.np,
      sessionId: sanitized.sessionId,
      upstream,
      write: (frame) => writeFrame(reply.raw, frame),
      ...(opts.restoreTools !== undefined && { restoreTools: opts.restoreTools }),
      ...(opts.logTraffic ? { onUpstreamChunk: (c) => logInboundSseChunk(c, call.reqId) } : {}),
    });
    logRoundTrip({
      req,
      reqId: call.reqId,
      sanitized,
      mode: 'SSE',
      event: 'anthropic.messages.streamed',
      counts: counters,
    });
  } catch (err) {
    // Stop the upstream call whatever broke the stream (client gone,
    // write error, upstream cut off): aborting the fetch releases its
    // socket. A normal end needs nothing, the body is already drained.
    const clientGone = abort.signal.aborted;
    abort.abort();
    req.log.error(
      { errMsg: errorMessage(err), aborted: clientGone },
      'anthropic.messages.stream_error',
    );
  } finally {
    reply.raw.end();
  }
}

/** Non-2xx upstream: status, diagnostic headers and body are passed
 * through, so the client SDK's own error handling and retries apply. */
function passThroughError(
  call: MessagesCall,
  status: number,
  headers: Headers,
  text: string,
): string {
  const { req, reply } = call;
  reply.code(status);
  for (const name of UPSTREAM_ERROR_HEADERS) {
    const value = headers.get(name);
    if (value !== null) reply.header(name, value);
  }
  if (headers.get('content-type') === null) reply.header('content-type', JSON_CONTENT_TYPE);
  // The body is not logged (see `upstreamErrorLogFields`): an error can
  // quote the request, and what the gateway forwards is not free of
  // personal data (unscanned fields, detector misses). Its length and
  // `error.type` are enough to tell an overload from a bad request.
  req.log.warn(
    {
      upstreamStatus: status,
      retryAfter: headers.get('retry-after') ?? undefined,
      rateLimitReset: headers.get('anthropic-ratelimit-requests-reset') ?? undefined,
      ...upstreamErrorLogFields(text),
    },
    'anthropic.upstream_error',
  );
  return text;
}

/** The gateway's own 502, in Anthropic's error envelope. */
function sendUpstreamFailure(reply: FastifyReply, message: string): FastifyReply {
  return reply
    .code(UPSTREAM_FAILURE_STATUS)
    .send({ type: 'error', error: { type: UPSTREAM_ERROR_TYPE, message } });
}
