// SPDX-License-Identifier: Apache-2.0

/**
 * Gateway runtime config — built from environment variables. Every
 * field is typed; no `process.env` access lives outside this module.
 *
 * Defaults are conservative: `127.0.0.1` bind so the gateway is not
 * exposed accidentally, 30-minute vault TTL, Anthropic as the
 * upstream.
 */
export interface GatewayConfig {
  /** Bind host for the Fastify server. */
  readonly host: string;
  /** Bind port. */
  readonly port: number;
  /** Upstream LLM provider base URL (no trailing slash). */
  readonly upstreamBaseUrl: string;
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
}

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8787;
const DEFAULT_UPSTREAM = 'https://api.anthropic.com';
const DEFAULT_VAULT_TTL_MS = 30 * 60 * 1000;
const DEFAULT_BACKEND = 'cpu' as const;
const DEFAULT_LOG_LEVEL = 'info' as const;
const DEFAULT_BODY_LIMIT = 10 * 1024 * 1024;

const VALID_BACKENDS = new Set(['cpu', 'mps', 'cuda', 'auto']);
const VALID_LOG_LEVELS = new Set(['fatal', 'error', 'warn', 'info', 'debug', 'trace']);

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

export function loadConfig(): GatewayConfig {
  const modelDir = process.env.NULLPII_MODEL_DIR;
  return {
    host: process.env.NULLPII_HOST ?? DEFAULT_HOST,
    port: readInt('NULLPII_PORT', DEFAULT_PORT),
    upstreamBaseUrl: (process.env.NULLPII_UPSTREAM ?? DEFAULT_UPSTREAM).replace(/\/+$/, ''),
    vaultTtlMs: readInt('NULLPII_VAULT_TTL_MS', DEFAULT_VAULT_TTL_MS),
    ...(modelDir !== undefined && modelDir !== '' ? { modelDir } : {}),
    backend: readEnum('NULLPII_BACKEND', VALID_BACKENDS, DEFAULT_BACKEND),
    logLevel: readEnum('NULLPII_LOG_LEVEL', VALID_LOG_LEVELS, DEFAULT_LOG_LEVEL),
    bodyLimitBytes: readInt('NULLPII_BODY_LIMIT_BYTES', DEFAULT_BODY_LIMIT),
    logTraffic: (process.env.NULLPII_LOG_TRAFFIC ?? '').toLowerCase() === 'wire',
  };
}
