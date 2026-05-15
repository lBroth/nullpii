// SPDX-License-Identifier: Apache-2.0

import type { FastifyInstance } from 'fastify';
import type { NullPii } from 'nullpii';
import { restoreResponse, sanitizeRequest } from '../sanitizer.js';
import type { AnthropicRequest, AnthropicResponse } from '../types.js';
import { type Fetch, buildUpstreamHeaders, forwardToAnthropic } from '../upstream.js';

export interface AnthropicRouteOptions {
  readonly np: NullPii;
  readonly upstreamBaseUrl: string;
  readonly fetchImpl: Fetch;
}

export async function registerAnthropicRoute(
  app: FastifyInstance,
  opts: AnthropicRouteOptions,
): Promise<void> {
  const { np, upstreamBaseUrl, fetchImpl } = opts;

  app.post('/v1/messages', async (req, reply) => {
    const body = req.body as AnthropicRequest;

    // Streaming is wired in a follow-up PR. Refuse here so a client that
    // sets `stream: true` gets a clear gateway-side error rather than a
    // silent buffer-and-restore that breaks the SSE contract.
    if ((body as { stream?: unknown }).stream === true) {
      return reply.code(501).send({
        type: 'error',
        error: {
          type: 'nullpii_gateway_error',
          message:
            'Streaming (`stream: true`) is not yet implemented in the gateway. Use non-streaming for now.',
        },
      });
    }

    const sanitized = await sanitizeRequest(np, body);
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

    // Non-2xx upstream → passthrough unchanged. The Anthropic SDK is
    // already set up to parse the upstream error shape; wrapping it
    // would break SDK retry/backoff heuristics.
    if (upstream.status < 200 || upstream.status >= 300) {
      np.destroySession(sanitized.sessionId);
      reply.code(upstream.status);
      const contentType = upstream.headers.get('content-type') ?? 'application/json';
      reply.header('content-type', contentType);
      return upstream.text;
    }

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

    // Telemetry only — counts, never values. PII never reaches the
    // structured-log layer (LogFields type-level allowlist enforces
    // this contract on the nullpii core).
    req.log.info(
      {
        replacements: restored.replacements,
        replacementsByLabel: restored.replacementsByLabel,
        unknownPlaceholders: restored.unknownPlaceholders,
        foreignPlaceholders: restored.foreignPlaceholders,
      },
      'anthropic.messages.restored',
    );

    return restored.body;
  });
}
