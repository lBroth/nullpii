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
  /** Upstream for `POST /v1/messages`: an Anthropic-compatible base URL
   * without the `/v1` segment, which the route appends (`NULLPII_UPSTREAM`). */
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
  /** When true, dump to stdout, for debugging, the request as forwarded
   * and the upstream response before restore (`NULLPII_LOG_TRAFFIC=wire`).
   * Not free of personal data: they hold whatever nullpii did not mask. */
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
  /** Whether the sidecar offers `POST /v1/sidecar/shutdown`
   * (`NULLPII_SIDECAR_SHUTDOWN=on`). Off by default: only the mod sets it,
   * on the sidecar it starts, so a gateway started any other way (Docker,
   * by hand, inside an app) cannot be stopped by a caller with the token. */
  readonly sidecarShutdown: boolean;
  /** The masking policy shared with the library, the CLI and the mod:
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
   * `NULLPII_DISABLE_HINT=1` turns it off, `0` (the default) leaves it on. */
  readonly appendHint: boolean;
}

const DEFAULT_HOST = '127.0.0.1';
const DEFAULT_PORT = 8787;
const DEFAULT_UPSTREAM = 'https://api.anthropic.com';
const DEFAULT_OPENAI_UPSTREAM = 'https://api.openai.com';
/** Both routes append their `/v1/…` path to the upstream base URL. */
const API_VERSION_SUFFIX = /\/v1$/;
const TRAILING_SLASHES = /\/+$/;
const UPSTREAM_PROTOCOLS: ReadonlySet<string> = new Set(['http:', 'https:']);
const PLAIN_HTTP = 'http:';
/** Hosts a plain `http:` upstream may name: the request carries the API
 * key and the masked conversation, so it crosses no network unencrypted. */
const LOOPBACK_HOSTS: ReadonlySet<string> = new Set(['127.0.0.1', '[::1]']);

/** The environment variables the gateway reads. */
export const NULLPII_HOST = 'NULLPII_HOST';
export const NULLPII_PORT = 'NULLPII_PORT';
export const NULLPII_UPSTREAM = 'NULLPII_UPSTREAM';
export const NULLPII_OPENAI_UPSTREAM = 'NULLPII_OPENAI_UPSTREAM';
export const NULLPII_VAULT_TTL_MS = 'NULLPII_VAULT_TTL_MS';
export const NULLPII_MODEL_DIR = 'NULLPII_MODEL_DIR';
export const NULLPII_BACKEND = 'NULLPII_BACKEND';
export const NULLPII_LOG_LEVEL = 'NULLPII_LOG_LEVEL';
export const NULLPII_BODY_LIMIT_BYTES = 'NULLPII_BODY_LIMIT_BYTES';
export const NULLPII_LOG_TRAFFIC = 'NULLPII_LOG_TRAFFIC';
export const NULLPII_SIDECAR_TOKEN = 'NULLPII_SIDECAR_TOKEN';
export const NULLPII_SIDECAR_MAX_SESSIONS = 'NULLPII_SIDECAR_MAX_SESSIONS';
export const NULLPII_SIDECAR_SHUTDOWN = 'NULLPII_SIDECAR_SHUTDOWN';
export const NULLPII_DISABLE_HINT = 'NULLPII_DISABLE_HINT';

/** An upstream variable and the path its route appends to it. */
interface UpstreamVar {
  readonly name: string;
  readonly fallback: string;
  readonly appendedPath: string;
}
const ANTHROPIC_UPSTREAM: UpstreamVar = {
  name: NULLPII_UPSTREAM,
  fallback: DEFAULT_UPSTREAM,
  appendedPath: '/v1/messages',
};
const OPENAI_UPSTREAM: UpstreamVar = {
  name: NULLPII_OPENAI_UPSTREAM,
  fallback: DEFAULT_OPENAI_UPSTREAM,
  appendedPath: '/v1/chat/completions',
};
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
const VALID_ON_OFF = new Set(['on', 'off']);
/** `NULLPII_DISABLE_HINT` values: `1` turns the hint off, `0` leaves it on. */
const HINT_OFF = '1';
const HINT_ON = '0';
const VALID_DISABLE_HINT = new Set([HINT_OFF, HINT_ON]);

/** An environment variable's value, `undefined` when unset or empty: the
 * gateway's one read of `process.env`. */
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
  const raw = readString(name);
  if (raw === undefined) return fallback;
  if (!allowed.has(raw)) {
    throw new Error(`${name} must be one of ${[...allowed].join('|')}, got: ${raw}`);
  }
  return raw as T;
}

/**
 * An upstream base URL, as `origin` plus path without trailing slashes;
 * unset or empty means `fallback`. It must be an `http:` or `https:` URL
 * with no credentials, query or fragment (the route appends its path, and
 * the URL is printed in the startup banner), and must not end with `/v1`,
 * which the route appends itself. An error never echoes a value that
 * could hold a secret: only the protocol, or the URL once it is known to
 * carry no credentials and no query.
 */
function readUpstreamUrl(v: UpstreamVar): string {
  const raw = readString(v.name) ?? v.fallback;
  if (!URL.canParse(raw)) throw new Error(`${v.name} must be an http: or https: URL`);
  const url = new URL(raw);
  if (!UPSTREAM_PROTOCOLS.has(url.protocol)) {
    throw new Error(`${v.name} must be an http: or https: URL, got protocol: ${url.protocol}`);
  }
  if (url.protocol === PLAIN_HTTP && !LOOPBACK_HOSTS.has(url.hostname)) {
    throw new Error(
      `${v.name} must use https: unless it is on this machine (the literal 127.0.0.1 or [::1]; localhost can resolve to the other one): the API key and the conversation would cross the network unencrypted`,
    );
  }
  if (url.username !== '' || url.password !== '') {
    throw new Error(
      `${v.name} must not embed credentials (user:password@); the client's own auth headers are forwarded`,
    );
  }
  if (url.search !== '' || url.hash !== '') {
    throw new Error(`${v.name} must be a base URL, without a query string or a fragment`);
  }
  const base = `${url.origin}${url.pathname}`.replace(TRAILING_SLASHES, '');
  if (API_VERSION_SUFFIX.test(base)) {
    throw new Error(
      `${v.name} must not end with /v1 (the gateway appends ${v.appendedPath}), got: ${base}`,
    );
  }
  return base;
}

function readSidecarToken(): string | undefined {
  const raw = readString(NULLPII_SIDECAR_TOKEN);
  if (raw === undefined) return undefined;
  if (raw.length < MIN_SIDECAR_TOKEN_LENGTH) {
    throw new Error(
      `${NULLPII_SIDECAR_TOKEN} must be at least ${MIN_SIDECAR_TOKEN_LENGTH} characters`,
    );
  }
  return raw;
}

/**
 * Read the gateway's configuration from the environment and the shared
 * policy file (`configFilePath()`). Fails loud, naming the variable or the
 * file, on any value it cannot use, rather than falling back silently.
 */
export function loadConfig(): GatewayConfig {
  const modelDir = readString(NULLPII_MODEL_DIR);
  const sidecarToken = readSidecarToken();
  const loadedFile = configFilePath();
  const policy = loadedFile === null ? {} : loadConfigFile(loadedFile);
  return {
    host: readString(NULLPII_HOST) ?? DEFAULT_HOST,
    port: readInt(NULLPII_PORT, DEFAULT_PORT, PORT_RANGE),
    upstreamBaseUrl: readUpstreamUrl(ANTHROPIC_UPSTREAM),
    openaiUpstreamBaseUrl: readUpstreamUrl(OPENAI_UPSTREAM),
    vaultTtlMs: readInt(NULLPII_VAULT_TTL_MS, DEFAULT_VAULT_TTL_MS, VAULT_TTL_RANGE),
    ...(modelDir !== undefined && { modelDir }),
    backend: readEnum(NULLPII_BACKEND, VALID_BACKENDS, DEFAULT_BACKEND),
    logLevel: readEnum(NULLPII_LOG_LEVEL, VALID_LOG_LEVELS, DEFAULT_LOG_LEVEL),
    bodyLimitBytes: readInt(NULLPII_BODY_LIMIT_BYTES, DEFAULT_BODY_LIMIT, AT_LEAST_ONE),
    logTraffic: readEnum<'wire' | 'off'>(NULLPII_LOG_TRAFFIC, VALID_LOG_TRAFFIC, 'off') === 'wire',
    ...(sidecarToken !== undefined && { sidecarToken }),
    sidecarMaxSessions: readInt(
      NULLPII_SIDECAR_MAX_SESSIONS,
      DEFAULT_SIDECAR_MAX_SESSIONS,
      AT_LEAST_ONE,
    ),
    sidecarShutdown: readEnum<'on' | 'off'>(NULLPII_SIDECAR_SHUTDOWN, VALID_ON_OFF, 'off') === 'on',
    policy,
    policyFile: loadedFile ?? defaultConfigPath(),
    policyLoaded: loadedFile !== null,
    restoreTools: new Set(policy.restoreTools ?? DEFAULT_RESTORE_TOOLS),
    appendHint:
      readEnum<typeof HINT_OFF | typeof HINT_ON>(
        NULLPII_DISABLE_HINT,
        VALID_DISABLE_HINT,
        HINT_ON,
      ) !== HINT_OFF,
  };
}
