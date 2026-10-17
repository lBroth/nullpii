// SPDX-License-Identifier: Apache-2.0

import { createHash, timingSafeEqual } from 'node:crypto';
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import { type NullPii, TextTooLongError } from 'nullpii';
import { restoreValue, sanitizeValue } from '../sanitizer.js';
import { SidecarSessions, isValidSessionKey } from '../sidecar-sessions.js';

/**
 * Session-scoped sanitize/restore API for local callers such as a Claude
 * Code mod, which keeps one vault session per conversation across turns.
 *
 * Every route needs `Authorization: Bearer <NULLPII_SIDECAR_TOKEN>`. A
 * request whose `Host` is not a loopback name, or that carries an
 * `Origin` header (browsers always send one on these methods), is
 * refused before the token is checked: a web page reaching the port
 * through DNS rebinding never gets as far as guessing the token.
 *
 * Responses carry counts, never the values that were masked. Requests
 * and responses are capped at 4 MiB, the per-call limit of a mod's
 * `$.http.fetch`.
 */
export interface SidecarRouteOptions {
  readonly np: NullPii;
  readonly token: string;
  readonly ttlMs: number;
  readonly maxSessions: number;
  /** Clock, injectable for tests. */
  readonly now?: () => number;
}

export const SIDECAR_MAX_BYTES = 4 * 1024 * 1024;
const SWEEP_INTERVAL_MIN_MS = 1_000;
const SWEEP_INTERVAL_MAX_MS = 60_000;
const MAX_RESTORE_FIELDS = 64;
const LOOPBACK_HOSTNAMES: ReadonlySet<string> = new Set(['127.0.0.1', 'localhost', '[::1]']);

const SESSION_PARAMS = {
  type: 'object',
  required: ['key'],
  properties: { key: { type: 'string' } },
} as const;

const SANITIZE_BODY = {
  type: 'object',
  required: ['value'],
  additionalProperties: false,
  properties: { value: {} },
} as const;

const RESTORE_BODY = {
  type: 'object',
  required: ['value'],
  additionalProperties: false,
  properties: {
    value: {},
    fields: { type: 'array', maxItems: MAX_RESTORE_FIELDS, items: { type: 'string' } },
  },
} as const;

interface SessionRequest {
  Params: { key: string };
}

interface SanitizeRequest extends SessionRequest {
  Body: { value: unknown };
}

interface RestoreRequest extends SessionRequest {
  Body: { value: unknown; fields?: string[] };
}

function sha256(value: string): Buffer {
  return createHash('sha256').update(value).digest();
}

function hostnameOf(host: string): string {
  if (host.startsWith('[')) return host.slice(0, host.indexOf(']') + 1);
  const colon = host.indexOf(':');
  return colon === -1 ? host : host.slice(0, colon);
}

/** `null` when the request may proceed, else the status and error code. */
function rejectReason(
  req: FastifyRequest,
  tokenDigest: Buffer,
): { status: number; error: string } | null {
  if (!LOOPBACK_HOSTNAMES.has(hostnameOf(req.headers.host ?? ''))) {
    return { status: 403, error: 'host_not_allowed' };
  }
  if (req.headers.origin !== undefined) return { status: 403, error: 'origin_not_allowed' };
  const auth = req.headers.authorization ?? '';
  const presented = auth.startsWith('Bearer ') ? auth.slice('Bearer '.length) : '';
  if (!timingSafeEqual(sha256(presented), tokenDigest)) {
    return { status: 401, error: 'unauthorized' };
  }
  return null;
}

/** Send `payload`, or 413 when it is over the caller's response limit:
 * placeholders are longer than most values they replace, so a request
 * under the limit can produce a response over it. */
function sendCapped(reply: FastifyReply, payload: Record<string, unknown>): FastifyReply {
  const body = JSON.stringify(payload);
  if (Buffer.byteLength(body) > SIDECAR_MAX_BYTES) {
    return reply.code(413).send({ error: 'response_too_large' });
  }
  return reply.type('application/json').send(body);
}

export async function registerSidecarRoutes(
  app: FastifyInstance,
  opts: SidecarRouteOptions,
): Promise<void> {
  const { np } = opts;
  const tokenDigest = sha256(opts.token);
  const sessions = new SidecarSessions(np, {
    ttlMs: opts.ttlMs,
    maxSessions: opts.maxSessions,
    ...(opts.now !== undefined && { now: opts.now }),
  });
  // Idle sessions are also dropped between requests, so real values do
  // not sit in memory past the TTL when no caller comes back.
  const sweepEveryMs = Math.min(Math.max(opts.ttlMs, SWEEP_INTERVAL_MIN_MS), SWEEP_INTERVAL_MAX_MS);
  const sweeper = setInterval(() => sessions.sweep(), sweepEveryMs);
  sweeper.unref();
  app.addHook('onClose', async () => {
    clearInterval(sweeper);
    sessions.closeAll();
  });

  await app.register(async (scope) => {
    // One string leaf over the engine's per-call cap: the caller has to
    // split it. Every other error stays a 500.
    scope.setErrorHandler((err, _req, reply) => {
      if (err instanceof TextTooLongError) return reply.code(413).send({ error: 'text_too_long' });
      return reply.send(err);
    });
    scope.addHook('onRequest', async (req, reply) => {
      const rejected = rejectReason(req, tokenDigest);
      if (rejected !== null) return reply.code(rejected.status).send({ error: rejected.error });
      return undefined;
    });

    scope.get('/v1/sidecar/status', async () => ({ status: 'ok', sessions: sessions.size }));

    scope.put<SessionRequest>(
      '/v1/sidecar/sessions/:key',
      { schema: { params: SESSION_PARAMS } },
      async (req, reply) => {
        if (!isValidSessionKey(req.params.key)) {
          return reply.code(400).send({ error: 'invalid_session_key' });
        }
        const opened = sessions.open(req.params.key);
        if (opened === 'full') return reply.code(429).send({ error: 'too_many_sessions' });
        return reply.code(opened === 'created' ? 201 : 200).send({ status: opened });
      },
    );

    scope.delete<SessionRequest>(
      '/v1/sidecar/sessions/:key',
      { schema: { params: SESSION_PARAMS } },
      async (req, reply) => {
        if (!sessions.close(req.params.key)) {
          return reply.code(404).send({ error: 'session_not_found' });
        }
        return reply.code(204).send();
      },
    );

    scope.post<SanitizeRequest>(
      '/v1/sidecar/sessions/:key/sanitize',
      { bodyLimit: SIDECAR_MAX_BYTES, schema: { params: SESSION_PARAMS, body: SANITIZE_BODY } },
      async (req, reply) => {
        const vaultId = sessions.use(req.params.key);
        if (vaultId === undefined) return reply.code(404).send({ error: 'session_not_found' });
        const r = await sanitizeValue(np, req.body.value, vaultId);
        req.log.info({ captured: r.captured, byLabel: r.capturedByLabel }, 'sidecar.sanitize');
        return sendCapped(reply, {
          value: r.value,
          captured: r.captured,
          capturedByLabel: r.capturedByLabel,
        });
      },
    );

    scope.post<RestoreRequest>(
      '/v1/sidecar/sessions/:key/restore',
      { bodyLimit: SIDECAR_MAX_BYTES, schema: { params: SESSION_PARAMS, body: RESTORE_BODY } },
      async (req, reply) => {
        const vaultId = sessions.use(req.params.key);
        if (vaultId === undefined) return reply.code(404).send({ error: 'session_not_found' });
        const { value, fields } = req.body;
        const isObject = value !== null && typeof value === 'object' && !Array.isArray(value);
        if (fields !== undefined && !isObject) {
          return reply.code(400).send({ error: 'fields_require_object_value' });
        }
        const r = restoreValue(np, value, vaultId, fields);
        req.log.info(
          {
            replacements: r.replacements,
            unknown: r.unknownPlaceholders,
            foreign: r.foreignPlaceholders,
          },
          'sidecar.restore',
        );
        return sendCapped(reply, {
          value: r.value,
          replacements: r.replacements,
          replacementsByLabel: r.replacementsByLabel,
          unknownPlaceholders: r.unknownPlaceholders,
          foreignPlaceholders: r.foreignPlaceholders,
        });
      },
    );
  });
}
