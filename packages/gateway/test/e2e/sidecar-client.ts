// SPDX-License-Identifier: Apache-2.0
//
// A small client of the sidecar routes over `app.inject`, for the
// gateway's real-ONNX suite: open a session with its secret, sanitize,
// restore, and read or replace the policy.

import { randomUUID } from 'node:crypto';
import type { FastifyInstance, LightMyRequestResponse } from 'fastify';
import { expect } from 'vitest';
import { POLICY_VERSION_HEADER, SESSION_SECRET_HEADER } from '../../src/routes/sidecar.js';
import { distinctPlaceholders } from './helpers.js';

const TOKEN_LENGTH = 64;
/** The bearer token the e2e servers are built with. */
export const SIDECAR_TOKEN = 'e'.repeat(TOKEN_LENGTH);
const AUTH: Readonly<Record<string, string>> = { authorization: `Bearer ${SIDECAR_TOKEN}` };
/** `hit` when a sanitize answer came from the session's cache. */
export const CACHE_HEADER = 'x-nullpii-cache';
const SESSIONS_PATH = '/v1/sidecar/sessions';
const STATUS_PATH = '/v1/sidecar/status';
const POLICY_PATH = '/v1/sidecar/policy';
const CREATED = 201;
const OK = 200;

/** A session this client opened: its key and the secret it was given. */
export interface SidecarSession {
  readonly key: string;
  readonly secret: string;
}

/** `POST …/sanitize` answer. */
export interface SanitizeAnswer {
  readonly value: unknown;
  readonly captured: number;
  readonly capturedByLabel: Record<string, number>;
  readonly modelUnscannedWords: number;
}

/** `POST …/restore` answer. */
export interface RestoreAnswer {
  readonly value: unknown;
  readonly replacements: number;
  readonly replacementsByLabel: Record<string, number>;
  readonly unknownPlaceholders: number;
  readonly foreignPlaceholders: number;
  readonly shellKeptMasked?: string[];
  readonly heldForTool?: number;
}

/** `policy` of the status and policy answers. */
export interface PolicyView {
  readonly version: string;
  readonly config: unknown;
  readonly disabledCategories: string[];
  readonly restoreTools: string[];
}

/** `POST …/restore` body. */
export interface RestoreBody {
  readonly value: unknown;
  readonly tool?: string;
  readonly fields?: string[];
}

/** The bearer token alone: enough for status and policy, not a session. */
export function bearerOnly(): Record<string, string> {
  return { ...AUTH };
}

/** The headers of a call on `session`, optionally naming the policy
 * version the caller last saw. */
export function sessionHeaders(
  session: SidecarSession,
  policyVersion?: string,
): Record<string, string> {
  return {
    ...AUTH,
    [SESSION_SECRET_HEADER]: session.secret,
    ...(policyVersion !== undefined && { [POLICY_VERSION_HEADER]: policyVersion }),
  };
}

/** The path of a session, or of one of its routes. */
export function sessionPath(key: string, route?: 'sanitize' | 'restore'): string {
  return route === undefined ? `${SESSIONS_PATH}/${key}` : `${SESSIONS_PATH}/${key}/${route}`;
}

/** Open a new session under a random key; fails the test unless created. */
export async function openSession(app: FastifyInstance): Promise<SidecarSession> {
  const key = `e2e-${randomUUID()}`;
  const res = await app.inject({ method: 'PUT', url: sessionPath(key), headers: bearerOnly() });
  expect(res.statusCode).toBe(CREATED);
  const body = res.json<{ status: string; secret: string }>();
  expect(body.status).toBe('created');
  return { key, secret: body.secret };
}

/** `POST …/sanitize` of `value` in `session`, as sent. */
export function sanitizeIn(
  app: FastifyInstance,
  session: SidecarSession,
  value: unknown,
  policyVersion?: string,
): Promise<LightMyRequestResponse> {
  return app.inject({
    method: 'POST',
    url: sessionPath(session.key, 'sanitize'),
    headers: sessionHeaders(session, policyVersion),
    payload: { value },
  });
}

/** Sanitize `value` in `session`; fails the test unless it answers 200. */
export async function maskIn(
  app: FastifyInstance,
  session: SidecarSession,
  value: unknown,
): Promise<SanitizeAnswer> {
  const res = await sanitizeIn(app, session, value);
  expect(res.statusCode).toBe(OK);
  return res.json<SanitizeAnswer>();
}

/** `POST …/restore` in `session`, as sent. */
export function restoreIn(
  app: FastifyInstance,
  session: SidecarSession,
  body: RestoreBody,
): Promise<LightMyRequestResponse> {
  return app.inject({
    method: 'POST',
    url: sessionPath(session.key, 'restore'),
    headers: sessionHeaders(session),
    payload: body,
  });
}

/** Restore `body` in `session`; fails the test unless it answers 200. */
export async function unmaskIn(
  app: FastifyInstance,
  session: SidecarSession,
  body: RestoreBody,
): Promise<RestoreAnswer> {
  const res = await restoreIn(app, session, body);
  expect(res.statusCode).toBe(OK);
  return res.json<RestoreAnswer>();
}

/** The placeholder of `masked` that restores, in `session`, to `original`.
 * Found through the restore route, so no test depends on placeholder ids
 * or on the label the model chose. */
export async function placeholderOf(
  app: FastifyInstance,
  session: SidecarSession,
  masked: string,
  original: string,
): Promise<string> {
  for (const placeholder of distinctPlaceholders(masked)) {
    const back = await unmaskIn(app, session, { value: placeholder });
    if (back.value === original) return placeholder;
  }
  throw new Error('no placeholder of the masked text restores to the value');
}

/** The policy in effect, as the status route reports it. */
export async function policyNow(app: FastifyInstance): Promise<PolicyView> {
  const res = await app.inject({ method: 'GET', url: STATUS_PATH, headers: bearerOnly() });
  expect(res.statusCode).toBe(OK);
  return res.json<{ policy: PolicyView }>().policy;
}

/** `PUT /v1/sidecar/policy` with `config`, optionally naming the version
 * the caller last saw. */
export function putPolicy(
  app: FastifyInstance,
  config: unknown,
  seenVersion?: string,
): Promise<LightMyRequestResponse> {
  return app.inject({
    method: 'PUT',
    url: POLICY_PATH,
    headers: {
      ...AUTH,
      ...(seenVersion !== undefined && { [POLICY_VERSION_HEADER]: seenVersion }),
    },
    payload: { config },
  });
}
