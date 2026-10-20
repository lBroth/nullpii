// SPDX-License-Identifier: Apache-2.0

import { DEFAULT_RESTORE_TOOLS, type NullPiiFileConfig, resolveConfigFile } from 'nullpii';

/**
 * Gateway runtime config — built from environment variables. Every
 * field is typed; no `process.env` access lives outside this module.
 *
 * Defaults are conservative: `127.0.0.1` bind so the gateway is not
 * exposed accidentally, 30-minute vault TTL, Anthropic and OpenAI as
 * the upstreams.
 */
export interface GatewayConfig {
  /** Bind host for the Fastify server. */
  readonly host: string;
  /** Bind port. */
  readonly port: number;
  /** Upstream LLM provider base URL (no trailing slash). */
  readonly upstreamBaseUrl: string;
  /** Upstream for `POST /v1/chat/completions`: an OpenAI-compatible base
   * URL without the `/v1` segment, which the route appends
   * (`NULLPII_OPENAI_UPSTREAM`). */
  readonly openaiUpstreamBaseUrl: string;
  /** ms the vault keeps a session alive after the last access. */
  readonly vaultTtlMs: number;
  /** Path to the local GLiNER model dir. Forwarded to `NullPii`. */
  readonly modelDir?: string;
  /** Backend selection. Matches `BackendName` from the `nullpii` core. */
  readonly backend: 'cpu' | 'mps' | 'cuda' | 'auto';
  /** Fastify log level. */
  readonly logLevel: 'fatal' | 'error' | 'warn' | 'info' | 'debug' | 'trace';
  /** Request body size cap in bytes (Fastify default 1 MB raised to 10 MB). */
  readonly bodyLimitBytes: number;
  /** When true, dump sanitized request body + upstream response (still
   * carrying placeholders, never real PII) to stdout for debugging.
   * Enabled via `NULLPII_LOG_TRAFFIC=wire`. */
  readonly logTraffic: boolean;
  /** Bearer token for the `/v1/sidecar/*` routes (`NULLPII_SIDECAR_TOKEN`,
   * at least 32 characters). Unset: the sidecar routes are not
   * registered at all. Generate one per launch, for example with
   * `openssl rand -hex 32`. */
  readonly sidecarToken?: string;
  /** Cap on concurrent sidecar sessions. Creating one more fails with 429
   * instead of evicting a live session, whose placeholders would then no
   * longer restore. */
  readonly sidecarMaxSessions: number;
  /** The masking policy shared with the CLI, the mod and the MCP server:
   * the file at `NULLPII_CONFIG`, else `~/.config/nullpii/config.json`
   * if present, else none (`{}`). */
  readonly policy: NullPiiFileConfig;
  /** Tools whose arguments get real values back: the policy's
   * `restoreTools`, else `DEFAULT_RESTORE_TOOLS`. */
  readonly restoreTools: ReadonlySet<string>;
  /** Append `LLM_PRESERVATION_HINT` to requests that had PII masked;
   * `NULLPII_DISABLE_HINT=1` turns it off. */
  readonly appendHint: boolean;
}

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8787;
const DEFAULT_UPSTREAM = 'https://api.anthropic.com';
const DEFAULT_OPENAI_UPSTREAM = 'https://api.openai.com';
/** The OpenAI route appends `/v1/chat/completions` itself. */
const API_VERSION_SUFFIX = /\/v1$/;
const TRAILING_SLASHES = /\/+$/;
const DEFAULT_VAULT_TTL_MS = 30 * 60 * 1000;
const DEFAULT_BACKEND = 'cpu' as const;
const DEFAULT_LOG_LEVEL = 'info' as const;
const DEFAULT_BODY_LIMIT = 10 * 1024 * 1024;
const DEFAULT_SIDECAR_MAX_SESSIONS = 64;
const MIN_SIDECAR_TOKEN_LENGTH = 32;

const VALID_BACKENDS = new Set(['cpu', 'mps', 'cuda', 'auto']);
const VALID_LOG_LEVELS = new Set(['fatal', 'error', 'warn', 'info', 'debug', 'trace']);
const VALID_LOG_TRAFFIC = new Set(['wire', 'off']);

/** An environment variable's value, `undefined` when unset or empty. */
function readString(name: string): string | undefined {
  const raw = process.env[name];
  return raw === undefined || raw === '' ? undefined : raw;
}

function readInt(name: string, fallback: number): number {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  const n = Number.parseInt(raw, 10);
  if (!Number.isFinite(n) || n < 0) {
    throw new Error(`${name} must be a non-negative integer, got: ${raw}`);
  }
  return n;
}

function readEnum<T extends string>(name: string, allowed: Set<string>, fallback: T): T {
  const raw = process.env[name];
  if (raw === undefined || raw === '') return fallback;
  if (!allowed.has(raw)) {
    throw new Error(`${name} must be one of ${[...allowed].join('|')}, got: ${raw}`);
  }
  return raw as T;
}

/** A base URL with trailing slashes stripped; unset or empty → `fallback`. */
function readBaseUrl(name: string, fallback: string): string {
  const raw = process.env[name];
  return (raw === undefined || raw === '' ? fallback : raw).replace(TRAILING_SLASHES, '');
}

function readOpenAiUpstream(): string {
  const url = readBaseUrl('NULLPII_OPENAI_UPSTREAM', DEFAULT_OPENAI_UPSTREAM);
  if (API_VERSION_SUFFIX.test(url)) {
    throw new Error(
      `NULLPII_OPENAI_UPSTREAM must not end with /v1 (the gateway appends /v1/chat/completions), got: ${url}`,
    );
  }
  return url;
}

function readSidecarToken(): string | undefined {
  const raw = process.env.NULLPII_SIDECAR_TOKEN;
  if (raw === undefined || raw === '') return undefined;
  if (raw.length < MIN_SIDECAR_TOKEN_LENGTH) {
    throw new Error(
      `NULLPII_SIDECAR_TOKEN must be at least ${MIN_SIDECAR_TOKEN_LENGTH} characters`,
    );
  }
  return raw;
}

export function loadConfig(): GatewayConfig {
  const modelDir = readString('NULLPII_MODEL_DIR');
  const sidecarToken = readSidecarToken();
  const policy = resolveConfigFile() ?? {};
  return {
    host: readString('NULLPII_HOST') ?? DEFAULT_HOST,
    port: readInt('NULLPII_PORT', DEFAULT_PORT),
    upstreamBaseUrl: readBaseUrl('NULLPII_UPSTREAM', DEFAULT_UPSTREAM),
    openaiUpstreamBaseUrl: readOpenAiUpstream(),
    vaultTtlMs: readInt('NULLPII_VAULT_TTL_MS', DEFAULT_VAULT_TTL_MS),
    ...(modelDir !== undefined && { modelDir }),
    backend: readEnum('NULLPII_BACKEND', VALID_BACKENDS, DEFAULT_BACKEND),
    logLevel: readEnum('NULLPII_LOG_LEVEL', VALID_LOG_LEVELS, DEFAULT_LOG_LEVEL),
    bodyLimitBytes: readInt('NULLPII_BODY_LIMIT_BYTES', DEFAULT_BODY_LIMIT),
    logTraffic:
      readEnum<'wire' | 'off'>('NULLPII_LOG_TRAFFIC', VALID_LOG_TRAFFIC, 'off') === 'wire',
    ...(sidecarToken !== undefined && { sidecarToken }),
    sidecarMaxSessions: readInt('NULLPII_SIDECAR_MAX_SESSIONS', DEFAULT_SIDECAR_MAX_SESSIONS),
    policy,
    restoreTools: new Set(policy.restoreTools ?? DEFAULT_RESTORE_TOOLS),
    appendHint: readString('NULLPII_DISABLE_HINT') !== '1',
  };
}
