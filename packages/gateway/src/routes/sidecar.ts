// SPDX-License-Identifier: Apache-2.0

import { createHash, createHmac, timingSafeEqual } from 'node:crypto';
import type { FastifyInstance, FastifyReply, FastifyRequest } from 'fastify';
import { InvalidConfigError, type NullPii, TextTooLongError } from 'nullpii';
import type { LivePolicy } from '../live-policy.js';
import type { SidecarRuntimeInfo } from '../runtime-info.js';
import { SanitizeCache } from '../sanitize-cache.js';
import { restoreValue, sanitizeValue } from '../sanitizer.js';
import { countPlaceholders, isShellTool } from '../shell-tools.js';
import {
  type SessionRefusal,
  SidecarSessions,
  isUnderBase,
  isValidSessionKey,
} from '../sidecar-sessions.js';
import type { StartupTracker } from '../startup.js';

/** What the sidecar routes need: the engine, the bearer token, session
 * limits, and the masking policy. */
export interface SidecarRouteOptions {
  readonly np: NullPii;
  readonly token: string;
  readonly ttlMs: number;
  readonly maxSessions: number;
  /** The masking policy in effect: its file, its restore tools (the tools
   * a `restore` with `tool` may put real values into), which
   * `PUT /v1/sidecar/policy` replaces. */
  readonly policy: LivePolicy;
  /** Package versions, actual backend and model pin status. */
  readonly runtime: () => SidecarRuntimeInfo;
  /** The engine's first start-up, which the status route reports as a
   * `startup` field. Absent when the server was built with a pre-built
   * engine. */
  readonly startup?: StartupTracker;
  /** Stops the process, for `POST /v1/sidecar/shutdown`. The route exists
   * only when it is given (the binary gives it; tests do not). */
  readonly shutdown?: () => void;
  /** Clock, injectable for tests. */
  readonly now?: () => number;
}

export const SIDECAR_MAX_BYTES = 4 * 1024 * 1024;
const SWEEP_INTERVAL_MIN_MS = 1_000;
const SWEEP_INTERVAL_MAX_MS = 60_000;
const MAX_RESTORE_FIELDS = 64;
/** Longest tool name `restore` accepts (`mcp__<server>__<tool>`). */
const MAX_TOOL_NAME_LENGTH = 128;
/** `hit` when a sanitize response came from the session's cache. */
const CACHE_HEADER = 'x-nullpii-cache';
/** The header a caller proves it owns a session with (lower case, as
 * Node presents header names). */
export const SESSION_SECRET_HEADER = 'x-nullpii-session-secret';
/** The policy version a caller last saw (`LivePolicy.version`). When it is
 * sent and the policy has changed since, `sanitize`, `restore` and
 * `PUT /v1/sidecar/policy` answer 412 and do nothing, so the caller learns
 * of a change it did not make before it masks, restores or overwrites
 * under it. */
export const POLICY_VERSION_HEADER = 'x-nullpii-policy-version';
/** On `PUT /v1/sidecar/sessions/:key`: the base the key is under (the key
 * itself, or the key is `<base>.<suffix>`). The caller says it left the
 * other keys under that base, whose secrets it lost (a reload): once the
 * session is created, they are not remembered as unclosed when their idle
 * TTL ends them. A live one stays open and usable by its owner, whose next
 * call undoes this. */
export const SUPERSEDES_HEADER = 'x-nullpii-supersedes';
const POLICY_CHANGED = 412;
/** A shutdown was accepted: until the process ends, new sessions are
 * refused, since one opened now would die with it. */
const SIDECAR_CLOSING = 503;
/** A shutdown refused, for one of `shutdownRefusal`'s reasons. */
const SHUTDOWN_REFUSED = 409;
const REFUSAL_REPLIES: Readonly<Record<SessionRefusal, { status: number; error: string }>> = {
  not_found: { status: 404, error: 'session_not_found' },
  forbidden: { status: 403, error: 'bad_session_secret' },
};
const LOOPBACK_HOSTNAMES: ReadonlySet<string> = new Set(['127.0.0.1', 'localhost', '[::1]']);
/** The `Authorization` value that carries the token; the scheme name is
 * case-insensitive (RFC 9110, section 11.1). The token holds no blank, so
 * the pattern is linear: blanks and token cannot trade characters. */
const BEARER = /^bearer[ \t]+([^ \t]*)$/i;
/** The route a caller checks the sidecar knows the token on, before it
 * sends the token or any text. */
export const CHALLENGE_PATH = '/v1/sidecar/challenge';
/** Prefixed to the nonce before it is signed, so a proof answers this
 * challenge and nothing else the token could be asked to sign. */
export const CHALLENGE_CONTEXT = 'nullpii-sidecar-challenge-v1\n';

const CHALLENGE_BODY = {
  type: 'object',
  required: ['nonce'],
  additionalProperties: false,
  properties: { nonce: { type: 'string', pattern: '^[0-9a-f]{64}$' } },
} as const;

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
    tool: { type: 'string', minLength: 1, maxLength: MAX_TOOL_NAME_LENGTH },
  },
} as const;

/** A policy file's contents, validated by `parseConfig` in the route. */
const POLICY_BODY = {
  type: 'object',
  required: ['config'],
  additionalProperties: false,
  properties: { config: { type: 'object' } },
} as const;

interface ChallengeRequest {
  Body: { nonce: string };
}

interface SessionRequest {
  Params: { key: string };
}

interface SanitizeRequest extends SessionRequest {
  Body: { value: unknown };
}

interface RestoreRequest extends SessionRequest {
  /** `tool`: the value is that tool's input. A tool outside the policy's
   * `restoreTools` gets nothing back, and neither does a shell tool, whose
   * placeholders are listed (`shell-tools.ts`). */
  Body: { value: unknown; fields?: string[]; tool?: string };
}

function sha256(value: string): Buffer {
  return createHash('sha256').update(value).digest();
}

/** The session secret the request presents; a repeated header counts as
 * none. */
function presentedSecret(req: FastifyRequest): string | undefined {
  const value = req.headers[SESSION_SECRET_HEADER];
  return typeof value === 'string' ? value : undefined;
}

/** The supersedes base the request names: undefined when it names none,
 * `invalid` when it is repeated, not a session key, or not a base the
 * session key is under. */
function presentedSupersedes(req: FastifyRequest, key: string): string | 'invalid' | undefined {
  const value = req.headers[SUPERSEDES_HEADER];
  if (value === undefined) return undefined;
  if (typeof value !== 'string' || !isValidSessionKey(value)) return 'invalid';
  return isUnderBase(key, value) ? value : 'invalid';
}

/** Whether the request names a policy version other than `current`. */
function staleVersion(req: FastifyRequest, current: string): boolean {
  const seen = req.headers[POLICY_VERSION_HEADER];
  if (seen === undefined) return false;
  return typeof seen !== 'string' || seen !== current;
}

function sendPolicyChanged(reply: FastifyReply, version: string): FastifyReply {
  return reply.code(POLICY_CHANGED).send({ error: 'policy_changed', version });
}

function sendRefusal(reply: FastifyReply, refusal: SessionRefusal): FastifyReply {
  const { status, error } = REFUSAL_REPLIES[refusal];
  return reply.code(status).send({ error });
}

function hostnameOf(host: string): string {
  if (host.startsWith('[')) return host.slice(0, host.indexOf(']') + 1);
  const colon = host.indexOf(':');
  return colon === -1 ? host : host.slice(0, colon);
}

/** The proof that the sidecar holds `token`, for a caller's `nonce`:
 * HMAC-SHA256 keyed by the token, in lower-case hex. */
function challengeProof(token: string, nonce: string): string {
  return createHmac('sha256', token)
    .update(CHALLENGE_CONTEXT + nonce)
    .digest('hex');
}

/** `null` when the request may proceed, else the status and error code.
 * The challenge needs no token: it is how a caller checks the sidecar
 * before sending the token. */
function rejectReason(
  req: FastifyRequest,
  tokenDigest: Buffer,
): { status: number; error: string } | null {
  if (!LOOPBACK_HOSTNAMES.has(hostnameOf(req.headers.host ?? ''))) {
    return { status: 403, error: 'host_not_allowed' };
  }
  if (req.headers.origin !== undefined) return { status: 403, error: 'origin_not_allowed' };
  if (req.url === CHALLENGE_PATH) return null;
  const auth = req.headers.authorization ?? '';
  const presented = BEARER.exec(auth)?.[1] ?? '';
  if (!timingSafeEqual(sha256(presented), tokenDigest)) {
    return { status: 401, error: 'unauthorized' };
  }
  return null;
}

/** Send `payload`, or 413 when it is over the caller's response limit:
 * placeholders are longer than most values they replace, so a request
 * under the limit can produce a response over it. */
function sendCapped(reply: FastifyReply, payload: Record<string, unknown>): FastifyReply {
  const body = cappedBody(payload);
  if (body === undefined) return reply.code(413).send({ error: 'response_too_large' });
  return reply.type('application/json').send(body);
}

/** The answer for a tool outside the policy's `restoreTools`: the value
 * as sent, with its placeholders counted in `heldForTool`. */
function sendHeld(req: FastifyRequest, reply: FastifyReply, value: unknown): FastifyReply {
  const heldForTool = countPlaceholders(JSON.stringify(value));
  req.log.info({ heldForTool }, 'sidecar.restore');
  return sendCapped(reply, {
    value,
    replacements: 0,
    replacementsByLabel: {},
    unknownPlaceholders: 0,
    foreignPlaceholders: 0,
    heldForTool,
  });
}

function cappedBody(payload: Record<string, unknown>): string | undefined {
  const body = JSON.stringify(payload);
  return Buffer.byteLength(body) > SIDECAR_MAX_BYTES ? undefined : body;
}

/**
 * Session-scoped sanitize/restore API for local callers such as a Claude
 * Code mod, which keeps one vault session per conversation across turns.
 *
 * A caller first checks that the sidecar holds the token, without
 * sending it: `POST /v1/sidecar/challenge` with a random `nonce` answers
 * `proof`, the HMAC-SHA256 of the nonce keyed by the token
 * (`challengeProof`). A process that took the port while the gateway was
 * down cannot answer it, so it gets neither the token nor any text.
 *
 * Every other route needs `Authorization: Bearer <NULLPII_SIDECAR_TOKEN>`. A
 * request whose `Host` is not a loopback name, or that carries an
 * `Origin` header (browsers always send one on these methods), is
 * refused before the token is checked: a web page reaching the port
 * through DNS rebinding never gets as far as guessing the token.
 *
 * Creating a session returns its secret, once. Every other call on that
 * session (`sanitize`, `restore`, `DELETE`, and opening it again) must
 * send it in `x-nullpii-session-secret`: the bearer token alone, which
 * every command started from the caller's shell may inherit, does not
 * reach another caller's real values.
 *
 * The policy has a version (`GET /v1/sidecar/status`). A caller that sends
 * the version it last saw in `x-nullpii-policy-version` is answered 412,
 * with nothing done, once the policy has changed since: the token alone can
 * replace the policy, so a caller holding real values (the mod) checks that
 * every change was one it made or accepted.
 *
 * Responses carry counts, never the values that were masked. Requests
 * and responses are capped at 4 MiB, the per-call limit of a mod's
 * `$.http.fetch`.
 */
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
  // Set once a shutdown call was accepted: the process is on its way out,
  // so no session may open in the time the 202 and the exit are apart.
  let closing = false;

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

    scope.post<ChallengeRequest>(
      CHALLENGE_PATH,
      { schema: { body: CHALLENGE_BODY } },
      async (req) => ({
        proof: challengeProof(opts.token, req.body.nonce),
      }),
    );

    const policyView = () => {
      const modes = opts.policy.modes();
      return {
        version: opts.policy.version,
        file: opts.policy.file,
        loaded: opts.policy.loaded,
        config: opts.policy.config,
        categories: modes,
        disabledCategories: Object.keys(modes).filter(
          (c) => modes[c as keyof typeof modes] === 'off',
        ),
        restoreTools: [...opts.policy.restoreTools],
      };
    };

    scope.get('/v1/sidecar/status', async () => ({
      status: 'ok',
      sessions: sessions.size,
      ...opts.runtime(),
      // What this sidecar can do that an older one could not: a caller
      // asks before using it, as an older sidecar has no such route.
      features: { shutdown: opts.shutdown !== undefined },
      policy: policyView(),
      ...(opts.startup !== undefined && { startup: opts.startup.current }),
    }));

    // Replace the policy: validated, written to the policy file, applied
    // to the engine and the restore tools at once. Cached sanitize
    // responses were masked under the old policy, so they go (and the
    // cache key holds the version, for a sanitize still running).
    scope.put<{ Body: { config: unknown } }>(
      '/v1/sidecar/policy',
      { schema: { body: POLICY_BODY } },
      async (req, reply) => {
        if (staleVersion(req, opts.policy.version)) {
          return sendPolicyChanged(reply, opts.policy.version);
        }
        try {
          opts.policy.replace(np, req.body.config);
        } catch (err) {
          if (err instanceof InvalidConfigError) {
            return reply.code(400).send({ error: 'invalid_policy', message: err.message });
          }
          throw err;
        }
        sessions.clearCaches();
        req.log.info('sidecar.policy');
        return { status: 'ok', policy: policyView() };
      },
    );

    scope.put<SessionRequest>(
      '/v1/sidecar/sessions/:key',
      { schema: { params: SESSION_PARAMS } },
      async (req, reply) => {
        // A sidecar that answered 202 is going away: a session opened now
        // would die with the process, so it is refused.
        if (closing) return reply.code(SIDECAR_CLOSING).send({ error: 'sidecar_closing' });
        if (!isValidSessionKey(req.params.key)) {
          return reply.code(400).send({ error: 'invalid_session_key' });
        }
        const supersedes = presentedSupersedes(req, req.params.key);
        if (supersedes === 'invalid') return reply.code(400).send({ error: 'invalid_supersedes' });
        const opened = sessions.open(req.params.key, presentedSecret(req), supersedes);
        switch (opened.kind) {
          case 'created':
            return reply.code(201).send({ status: 'created', secret: opened.secret });
          case 'exists':
            return reply.code(200).send({ status: 'exists' });
          case 'conflict':
            return reply.code(409).send({ error: 'session_exists' });
          case 'full':
            return reply.code(429).send({ error: 'too_many_sessions' });
        }
      },
    );

    scope.delete<SessionRequest>(
      '/v1/sidecar/sessions/:key',
      { schema: { params: SESSION_PARAMS } },
      async (req, reply) => {
        const closed = sessions.close(req.params.key, presentedSecret(req));
        if (closed !== 'closed') return sendRefusal(reply, closed);
        return reply.code(204).send();
      },
    );

    // Lets a newer mod replace this sidecar with its own release. Only a
    // sidecar no one may still count on goes (`shutdownRefusal`).
    if (opts.shutdown !== undefined) {
      const shutdown = opts.shutdown;
      scope.post('/v1/sidecar/shutdown', async (_req, reply) => {
        // A session past its idle TTL counts as ended by it, not as open.
        sessions.sweep();
        // Once closing, a second call is told the same, and stops nothing twice.
        const refusal = closing ? undefined : shutdownRefusal(sessions, opts.startup);
        if (refusal !== undefined) return reply.code(SHUTDOWN_REFUSED).send(refusal);
        if (!closing) {
          closing = true;
          setImmediate(shutdown);
        }
        return reply.code(202).send({ status: 'closing' });
      });
    }

    scope.post<SanitizeRequest>(
      '/v1/sidecar/sessions/:key/sanitize',
      { bodyLimit: SIDECAR_MAX_BYTES, schema: { params: SESSION_PARAMS, body: SANITIZE_BODY } },
      async (req, reply) => {
        const session = sessions.use(req.params.key, presentedSecret(req));
        if (typeof session === 'string') return sendRefusal(reply, session);
        // The version at the start: an answer masked under it is cached
        // under it, so a policy change while this runs cannot leave an old
        // answer where the new policy's requests look.
        const version = opts.policy.version;
        if (staleVersion(req, version)) return sendPolicyChanged(reply, version);
        const generation = opts.policy.generation;
        const cacheKey = SanitizeCache.keyOf(`${version}\n${JSON.stringify(req.body.value)}`);
        const cached = session.cache.get(cacheKey);
        if (cached !== undefined) {
          req.log.info({ cache: 'hit' }, 'sidecar.sanitize');
          return reply.header(CACHE_HEADER, 'hit').type('application/json').send(cached);
        }
        const r = await sanitizeValue(np, req.body.value, session.vaultId);
        // The engine reads the policy as it goes, so an answer that ran
        // across a change (even one put back since) was masked under a mix:
        // a caller that named its version gets 412, and nothing is cached.
        const changed = opts.policy.generation !== generation;
        if (changed && req.headers[POLICY_VERSION_HEADER] !== undefined) {
          return sendPolicyChanged(reply, opts.policy.version);
        }
        req.log.info(
          {
            captured: r.captured,
            byLabel: r.capturedByLabel,
            modelUnscannedWords: r.modelUnscannedWords,
          },
          'sidecar.sanitize',
        );
        const body = cappedBody({
          value: r.value,
          captured: r.captured,
          capturedByLabel: r.capturedByLabel,
          modelUnscannedWords: r.modelUnscannedWords,
        });
        if (body === undefined) return reply.code(413).send({ error: 'response_too_large' });
        if (!changed) session.cache.set(cacheKey, body);
        return reply.header(CACHE_HEADER, 'miss').type('application/json').send(body);
      },
    );

    scope.post<RestoreRequest>(
      '/v1/sidecar/sessions/:key/restore',
      { bodyLimit: SIDECAR_MAX_BYTES, schema: { params: SESSION_PARAMS, body: RESTORE_BODY } },
      async (req, reply) => {
        const session = sessions.use(req.params.key, presentedSecret(req));
        if (typeof session === 'string') return sendRefusal(reply, session);
        if (staleVersion(req, opts.policy.version)) {
          return sendPolicyChanged(reply, opts.policy.version);
        }
        const { value, fields, tool } = req.body;
        const isObject = value !== null && typeof value === 'object' && !Array.isArray(value);
        if (fields !== undefined && !isObject) {
          return reply.code(400).send({ error: 'fields_require_object_value' });
        }
        if (tool !== undefined && !isObject) {
          return reply.code(400).send({ error: 'tool_requires_object_value' });
        }
        // A shell tool's input never gets a value: every placeholder is
        // listed back so the caller can refuse the call.
        const shell = isShellTool(tool);
        if (tool !== undefined && !shell && !opts.policy.restoreTools.has(tool)) {
          return sendHeld(req, reply, value);
        }
        const r = restoreValue(np, value, session.vaultId, fields, shell);
        req.log.info(
          {
            replacements: r.replacements,
            unknown: r.unknownPlaceholders,
            foreign: r.foreignPlaceholders,
            ...(r.shellKeptMasked !== undefined && { unsafeShell: r.shellKeptMasked.length }),
          },
          'sidecar.restore',
        );
        return sendCapped(reply, {
          value: r.value,
          replacements: r.replacements,
          replacementsByLabel: r.replacementsByLabel,
          unknownPlaceholders: r.unknownPlaceholders,
          foreignPlaceholders: r.foreignPlaceholders,
          ...(r.shellKeptMasked !== undefined && { shellKeptMasked: r.shellKeptMasked }),
        });
      },
    );
  });
}

/** Why this sidecar may not stop now, or undefined when it may. A window
 * that uses it, or waits for it, would lose masking with it, and only the
 * window that started it can start another one: so it stops only once every
 * session that opened here was closed by its caller, and its model is not
 * still coming up for the window that started it.
 * - `sessions_active`: a session is open.
 * - `starting`: the model is still downloading or loading.
 * - `not_used_yet`: no session has opened yet, so the window that started
 *   it has not got to it (unless the start failed: then no one can).
 * - `sessions_unclosed`: a session ended by its idle TTL, and its caller has
 *   not closed it since: a window left idle looks just like that, and would
 *   find the sidecar gone at its next prompt. */
export function shutdownRefusal(
  sessions: Pick<SidecarSessions, 'size' | 'everOpened' | 'unclosed'>,
  startup: StartupTracker | undefined,
): { readonly error: string; readonly sessions?: number } | undefined {
  if (sessions.size > 0) return { error: 'sessions_active', sessions: sessions.size };
  const phase = startup?.current.phase;
  if (phase === 'downloading' || phase === 'loading') return { error: 'starting' };
  if (!sessions.everOpened && phase !== 'failed') return { error: 'not_used_yet' };
  if (sessions.unclosed) return { error: 'sessions_unclosed' };
  return undefined;
}
