// SPDX-License-Identifier: Apache-2.0

import {
  DEFAULT_RESTORE_TOOLS,
  type NullPiiFileConfig,
  configFilePath,
  defaultConfigPath,
  loadConfigFile,
} from 'nullpii';

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
  /** The policy file that was loaded, else the default location one would
   * be read from at the next start. The sidecar's status reports it, so a
   * client can show the user which file to edit. */
  readonly policyFile: string;
  /** Whether `policyFile` existed and was loaded. */
  readonly policyLoaded: boolean;
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

/** The range an integer variable must fall in. */
interface IntRange {
  readonly min: number;
  readonly max: number;
}
const PORT_RANGE: IntRange = { min: 1, max: 65_535 };
/** A TTL under a second would expire a sidecar session between two calls. */
const VAULT_TTL_RANGE: IntRange = { min: 1_000, max: Number.MAX_SAFE_INTEGER };
const AT_LEAST_ONE: IntRange = { min: 1, max: Number.MAX_SAFE_INTEGER };
/** Digits only: no sign, unit, exponent or decimal point. */
const DIGITS = /^\d+$/;

const VALID_BACKENDS = new Set(['cpu', 'mps', 'cuda', 'auto']);
const VALID_LOG_LEVELS = new Set(['fatal', 'error', 'warn', 'info', 'debug', 'trace']);
const VALID_LOG_TRAFFIC = new Set(['wire', 'off']);

/** An environment variable's value, `undefined` when unset or empty. */
function readString(name: string): string | undefined {
  const raw = process.env[name];
  return raw === undefined || raw === '' ? undefined : raw;
}

/** An integer variable, parsed whole (`30m` and `1e6` are errors, not
 * 30 and 1), within `range`; unset or empty means `fallback`. */
function readInt(name: string, fallback: number, range: IntRange): number {
  const raw = readString(name);
  if (raw === undefined) return fallback;
  const n = DIGITS.test(raw) ? Number(raw) : Number.NaN;
  if (Number.isSafeInteger(n) && n >= range.min && n <= range.max) return n;
  const allowed =
    range.max === Number.MAX_SAFE_INTEGER
      ? `of at least ${range.min}`
      : `from ${range.min} to ${range.max}`;
  throw new Error(`${name} must be an integer ${allowed}, got: ${raw}`);
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
  const loadedFile = configFilePath();
  const policy = loadedFile === null ? {} : loadConfigFile(loadedFile);
  return {
    host: readString('NULLPII_HOST') ?? DEFAULT_HOST,
    port: readInt('NULLPII_PORT', DEFAULT_PORT, PORT_RANGE),
    upstreamBaseUrl: readBaseUrl('NULLPII_UPSTREAM', DEFAULT_UPSTREAM),
    openaiUpstreamBaseUrl: readOpenAiUpstream(),
    vaultTtlMs: readInt('NULLPII_VAULT_TTL_MS', DEFAULT_VAULT_TTL_MS, VAULT_TTL_RANGE),
    ...(modelDir !== undefined && { modelDir }),
    backend: readEnum('NULLPII_BACKEND', VALID_BACKENDS, DEFAULT_BACKEND),
    logLevel: readEnum('NULLPII_LOG_LEVEL', VALID_LOG_LEVELS, DEFAULT_LOG_LEVEL),
    bodyLimitBytes: readInt('NULLPII_BODY_LIMIT_BYTES', DEFAULT_BODY_LIMIT, AT_LEAST_ONE),
    logTraffic:
      readEnum<'wire' | 'off'>('NULLPII_LOG_TRAFFIC', VALID_LOG_TRAFFIC, 'off') === 'wire',
    ...(sidecarToken !== undefined && { sidecarToken }),
    sidecarMaxSessions: readInt(
      'NULLPII_SIDECAR_MAX_SESSIONS',
      DEFAULT_SIDECAR_MAX_SESSIONS,
      AT_LEAST_ONE,
    ),
    policy,
    policyFile: loadedFile ?? defaultConfigPath(),
    policyLoaded: loadedFile !== null,
    restoreTools: new Set(policy.restoreTools ?? DEFAULT_RESTORE_TOOLS),
    appendHint: readString('NULLPII_DISABLE_HINT') !== '1',
  };
}
