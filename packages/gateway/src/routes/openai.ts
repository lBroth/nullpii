// SPDX-License-Identifier: Apache-2.0

import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import type { NullPii } from 'nullpii';
import {
  isRecord,
  parseJson,
  restoreChatResponse,
  sanitizeChatRequest,
} from '../openai-sanitizer.js';
import { relayChatSseStream } from '../openai-sse-relay.js';
import type { ChatCompletionRequest, ChatCompletionResponse } from '../openai-types.js';
import { printRequestSummary } from '../pretty-log.js';
import type { RestoredResponse, SanitizedRequest } from '../sanitizer.js';
import {
  logInboundResponse,
  logInboundSseChunk,
  logOutboundHeaders,
  logOutboundRequest,
} from '../traffic-log.js';
import {
  type Fetch,
  OPENAI_HEADER_POLICY,
  type UpstreamCall,
  buildUpstreamHeaders,
  extractQuery,
  forwardToUpstream,
} from '../upstream.js';

/**
 * `POST /v1/chat/completions`: the OpenAI Chat Completions wire format, so
 * OpenAI SDKs and OpenAI-compatible clients can point their base URL at
 * the gateway. Same lifecycle as the Anthropic route: sanitize the request
 * into a fresh vault session, forward it, restore the placeholders in the
 * JSON response or the SSE stream, destroy the session.
 */
export interface OpenAiRouteOptions {
  readonly np: NullPii;
  /** OpenAI-compatible base URL, without `/v1`. */
  readonly upstreamBaseUrl: string;
  readonly fetchImpl: Fetch;
  /** When true, dump the sanitized request body + raw upstream response
   * (placeholder-bearing) to stdout. Never logs real PII. */
  readonly logTraffic: boolean;
}

const CHAT_COMPLETIONS_PATH = '/v1/chat/completions';
const UPSTREAM_ERROR_TYPE = 'nullpii_upstream_error';
const INVALID_REQUEST_TYPE = 'invalid_request_error';
const TRAFFIC_TARGET = 'openai';
const JSON_CONTENT_TYPE = 'application/json';
const SSE_CONTENT_TYPE = 'text/event-stream';

/** Upstream headers forwarded with a non-2xx response, so the client's
 * retry logic sees them: the OpenAI SDKs honour `retry-after`,
 * `retry-after-ms` and `x-should-retry`. */
const UPSTREAM_ERROR_HEADERS: ReadonlySet<string> = new Set([
  'content-type',
  'x-request-id',
  'retry-after',
  'retry-after-ms',
  'x-should-retry',
]);
/** `x-ratelimit-{limit,remaining,reset}-{requests,tokens}`. */
const UPSTREAM_ERROR_HEADER_PREFIXES = ['x-ratelimit-'];

/** An upstream error `type` / `code` is logged only when it looks like an
 * identifier (`rate_limit_exceeded`), so no free text ever reaches a log. */
const LOGGABLE_ERROR_FIELD = /^[\w.-]{1,64}$/;

type RestoreCounts = Pick<
  RestoredResponse,
  'replacements' | 'replacementsByLabel' | 'unknownPlaceholders' | 'foreignPlaceholders'
>;

/** Everything one proxied call needs once its request is sanitized. */
interface ChatCall {
  readonly req: FastifyRequest;
  readonly reply: FastifyReply;
  readonly opts: OpenAiRouteOptions;
  readonly sanitized: SanitizedRequest<ChatCompletionRequest>;
  /** Path plus the client's query string. */
  readonly path: string;
  readonly headers: Record<string, string>;
  readonly reqId: string | undefined;
}

/**
 * Register `POST /v1/chat/completions` on `app`.
 *
 * @param app - the Fastify instance (see `buildServer`).
 * @param opts - engine, upstream base URL, `fetch`, traffic dump switch.
 */
export async function registerOpenAiRoute(
  app: FastifyInstance,
  opts: OpenAiRouteOptions,
): Promise<void> {
  app.post(CHAT_COMPLETIONS_PATH, async (req, reply) => {
    const body = req.body;
    if (!isChatRequest(body)) {
      return reply.code(400).send(errorBody(INVALID_REQUEST_TYPE, '`messages` must be an array.'));
    }
    const { np } = opts;
    const sessionId = np.createSession();
    try {
      const sanitized = await sanitizeChatRequest(np, body, sessionId);
      const call = prepareCall(req, reply, opts, sanitized);
      return body.stream === true ? await handleStreaming(call) : await handleNonStreaming(call);
    } finally {
      // One vault session per request, dropped on every path: restored,
      // upstream error, fetch failure, failed sanitize, client gone.
      np.destroySession(sessionId);
    }
  });
}

function prepareCall(
  req: FastifyRequest,
  reply: FastifyReply,
  opts: OpenAiRouteOptions,
  sanitized: SanitizedRequest<ChatCompletionRequest>,
): ChatCall {
  const reqId = typeof req.id === 'string' ? req.id : undefined;
  const headers = buildUpstreamHeaders(
    req.headers as Record<string, string | string[] | undefined>,
    OPENAI_HEADER_POLICY,
  );
  if (opts.logTraffic) {
    logOutboundRequest(sanitized.body, reqId, TRAFFIC_TARGET);
    logOutboundHeaders(headers, reqId, TRAFFIC_TARGET);
  }
  const path = `${CHAT_COMPLETIONS_PATH}${extractQuery(req.url)}`;
  return { req, reply, opts, sanitized, path, headers, reqId };
}

async function handleNonStreaming(call: ChatCall): Promise<unknown> {
  const { reply, opts, sanitized } = call;
  let upstream: UpstreamCall;
  try {
    upstream = await forwardToUpstream(
      opts.fetchImpl,
      opts.upstreamBaseUrl,
      call.path,
      sanitized.body,
      call.headers,
    );
  } catch (err) {
    return sendUpstreamFailure(reply, errorMessage(err));
  }
  if (!isSuccess(upstream.status)) {
    return passThroughError(call, upstream.status, upstream.headers, upstream.text);
  }
  if (opts.logTraffic) logInboundResponse(upstream.text, call.reqId, TRAFFIC_TARGET);
  const parsed = parseJson(upstream.text);
  if (parsed === undefined || !isRecord(parsed.value)) {
    return sendUpstreamFailure(reply, 'Upstream returned 2xx with a non-JSON body.');
  }
  const response = parsed.value as ChatCompletionResponse;
  const restored = restoreChatResponse(opts.np, response, sanitized.sessionId);
  logRoundTrip(call, 'JSON', restored);
  return restored.body;
}

/**
 * Streaming path: pipe the upstream SSE stream through
 * `relayChatSseStream`, which holds placeholders split across chunks and
 * re-emits restored deltas. The reply is hijacked so the route owns the
 * socket for the whole stream.
 */
async function handleStreaming(call: ChatCall): Promise<unknown> {
  // A client that goes away cancels the upstream call, which stops the
  // upstream generating (and billing) tokens nobody reads. The signal is
  // `reply.raw` closing: on Node 16+ `req.raw` emits 'close' as soon as
  // the request body has been read, before this handler runs.
  const abort = new AbortController();
  const onClientClose = (): void => abort.abort();
  call.reply.raw.once('close', onClientClose);
  try {
    return await streamFromUpstream(call, abort);
  } finally {
    call.reply.raw.off('close', onClientClose);
  }
}

async function streamFromUpstream(call: ChatCall, abort: AbortController): Promise<unknown> {
  const { req, reply, opts, sanitized } = call;
  let upstream: Response;
  try {
    upstream = await opts.fetchImpl(`${opts.upstreamBaseUrl}${call.path}`, {
      method: 'POST',
      headers: call.headers,
      body: JSON.stringify(sanitized.body),
      signal: abort.signal,
    });
  } catch (err) {
    return sendUpstreamFailure(reply, errorMessage(err));
  }
  // Errors come back as a JSON body, not as an SSE stream.
  if (!isSuccess(upstream.status)) {
    return passThroughError(call, upstream.status, upstream.headers, await upstream.text());
  }
  if (upstream.body === null) {
    return sendUpstreamFailure(reply, 'Upstream returned 2xx without a body.');
  }

  reply.raw.statusCode = 200;
  reply.raw.setHeader('content-type', upstream.headers.get('content-type') ?? SSE_CONTENT_TYPE);
  reply.raw.setHeader('cache-control', 'no-cache');
  reply.raw.setHeader('connection', 'keep-alive');
  reply.hijack();
  try {
    const counters = await relayChatSseStream({
      np: opts.np,
      sessionId: sanitized.sessionId,
      upstream: upstream.body as unknown as AsyncIterable<Uint8Array>,
      write: (frame) => reply.raw.write(frame),
      ...(opts.logTraffic
        ? { onUpstreamChunk: (c: string) => logInboundSseChunk(c, call.reqId) }
        : {}),
    });
    logRoundTrip(call, 'SSE', counters);
  } catch (err) {
    // The client went away or the upstream broke off. Stop the upstream
    // call either way; only the error message is logged, never content.
    const clientGone = abort.signal.aborted;
    abort.abort();
    req.log.error({ errMsg: errorMessage(err), clientGone }, 'openai.chat.stream_error');
  } finally {
    reply.raw.end();
  }
  return reply;
}

/**
 * Non-2xx upstream: status and body are passed through verbatim, as the
 * Anthropic route does, so the client SDK's own error handling and retry
 * logic apply.
 */
function passThroughError(call: ChatCall, status: number, headers: Headers, text: string): string {
  const { req, reply } = call;
  reply.code(status);
  headers.forEach((value, name) => {
    const forwarded =
      UPSTREAM_ERROR_HEADERS.has(name) ||
      UPSTREAM_ERROR_HEADER_PREFIXES.some((prefix) => name.startsWith(prefix));
    if (forwarded) reply.header(name, value);
  });
  if (headers.get('content-type') === null) reply.header('content-type', JSON_CONTENT_TYPE);
  // Unlike the Anthropic route, the body itself is not logged: an OpenAI
  // error can quote request content the gateway forwards without
  // scanning, such as an image URL. Its `type` and `code` are enough to
  // tell a rate limit from a bad request.
  req.log.warn(
    {
      upstreamStatus: status,
      retryAfter: headers.get('retry-after') ?? undefined,
      ...upstreamErrorKind(text),
    },
    'openai.upstream_error',
  );
  return text;
}

function upstreamErrorKind(text: string): { errorType: string | null; errorCode: string | null } {
  const parsed = parseJson(text);
  const root = parsed !== undefined && isRecord(parsed.value) ? parsed.value : {};
  const error = isRecord(root.error) ? root.error : {};
  return { errorType: loggableField(error.type), errorCode: loggableField(error.code) };
}

function loggableField(value: unknown): string | null {
  return typeof value === 'string' && LOGGABLE_ERROR_FIELD.test(value) ? value : null;
}

function logRoundTrip(call: ChatCall, mode: 'JSON' | 'SSE', counts: RestoreCounts): void {
  const { sanitized } = call;
  // Counts and labels only. `counts` may be a whole `RestoredResponse`,
  // whose `body` holds the real values, so its fields are picked one by
  // one and never spread.
  call.req.log.info(
    {
      captured: sanitized.captured,
      capturedByLabel: sanitized.capturedByLabel,
      unscanned: sanitized.unscanned,
      replacements: counts.replacements,
      replacementsByLabel: counts.replacementsByLabel,
      unknownPlaceholders: counts.unknownPlaceholders,
      foreignPlaceholders: counts.foreignPlaceholders,
    },
    mode === 'JSON' ? 'openai.chat.restored' : 'openai.chat.streamed',
  );
  const summary = {
    mode,
    captured: sanitized.captured,
    capturedByLabel: sanitized.capturedByLabel,
    unscanned: sanitized.unscanned,
    restored: counts.replacements,
    restoredByLabel: counts.replacementsByLabel,
    unknownPlaceholders: counts.unknownPlaceholders,
    foreignPlaceholders: counts.foreignPlaceholders,
  };
  printRequestSummary(call.reqId !== undefined ? { ...summary, reqId: call.reqId } : summary);
}

function isChatRequest(body: unknown): body is ChatCompletionRequest {
  return isRecord(body) && Array.isArray(body.messages);
}

function isSuccess(status: number): boolean {
  return status >= 200 && status < 300;
}

function sendUpstreamFailure(reply: FastifyReply, message: string): FastifyReply {
  return reply.code(502).send(errorBody(UPSTREAM_ERROR_TYPE, message));
}

/** OpenAI-style error envelope. */
function errorBody(type: string, message: string): { error: { type: string; message: string } } {
  return { error: { type, message } };
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}
