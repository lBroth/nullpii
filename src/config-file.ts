// SPDX-License-Identifier: Apache-2.0

import { readFileSync, statSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { NULLPII_CONFIG, XDG_CONFIG_HOME, readEnvVar } from './config.js';
import { CONFIG_DIR_NAME, CONFIG_FILE_NAME, MAX_CONFIG_FILE_BYTES } from './defaults.js';
import { InvalidConfigError } from './errors.js';
import type { NullPiiConfig, PiiCategory, UrlAllowlistConfig } from './types/index.js';
import { PII_LABELS } from './types/labels.js';
import { urlPolicy } from './url-filter.js';

/**
 * The masking policy one JSON file holds for every nullpii surface: the
 * library (`toEngineConfig`), the CLI (`--config`), the gateway and the
 * Claude Code mod it serves, and the MCP server. Every key is optional;
 * an unknown key is an error, so a typo never silently changes nothing.
 */
export interface NullPiiFileConfig {
  /** As `NullPiiConfig.disabledCategories`. */
  readonly disabledCategories?: readonly PiiCategory[];
  /** As `NullPiiConfig.categoryThresholds`, each in `[0, 1]`. */
  readonly categoryThresholds?: Readonly<Partial<Record<PiiCategory, number>>>;
  /** As `NullPiiConfig.threshold`, in `[0, 1]`. */
  readonly threshold?: number;
  /** As `NullPiiConfig.urlAllowlist`. */
  readonly urlAllowlist?: 'none' | UrlAllowlistConfig;
  /** Tools whose arguments get real values back (gateway and mod).
   * Default: `DEFAULT_RESTORE_TOOLS`, the tools that run on this machine. */
  readonly restoreTools?: readonly string[];
}

const KEYS: ReadonlySet<string> = new Set([
  'disabledCategories',
  'categoryThresholds',
  'threshold',
  'urlAllowlist',
  'restoreTools',
]);
const URL_ALLOWLIST_KEYS: ReadonlySet<string> = new Set(['hosts', 'replaceDefaults']);
const CATEGORIES: ReadonlySet<string> = new Set(PII_LABELS.filter((l) => l !== 'O'));
/** A Claude Code or MCP tool name (`Bash`, `mcp__server__tool`). */
const TOOL_NAME = /^[A-Za-z0-9_.:-]{1,128}$/;

/** `$XDG_CONFIG_HOME/nullpii/config.json`, else `~/.config/nullpii/config.json`. */
export function defaultConfigPath(): string {
  const base = readEnvVar(XDG_CONFIG_HOME) ?? join(homedir(), '.config');
  return join(base, CONFIG_DIR_NAME, CONFIG_FILE_NAME);
}

/**
 * The config every surface uses: the file at `explicitPath` (a CLI flag),
 * else at `NULLPII_CONFIG`, else at {@link defaultConfigPath} if it
 * exists. An explicit or environment path that does not exist is an
 * error; a missing default file means no config (`null`).
 */
export function resolveConfigFile(explicitPath?: string): NullPiiFileConfig | null {
  const chosen = explicitPath ?? readEnvVar(NULLPII_CONFIG);
  if (chosen !== undefined) return loadConfigFile(chosen);
  const fallback = defaultConfigPath();
  return isFile(fallback) ? loadConfigFile(fallback) : null;
}

/** Read and validate the config file at `path`. Throws
 * {@link InvalidConfigError} when it is missing, not a regular file,
 * larger than `MAX_CONFIG_FILE_BYTES`, not JSON, or invalid. */
export function loadConfigFile(path: string): NullPiiFileConfig {
  let size: number;
  try {
    const st = statSync(path);
    if (!st.isFile()) throw new InvalidConfigError(`${path} is not a regular file`);
    size = st.size;
  } catch (err) {
    if (err instanceof InvalidConfigError) throw err;
    throw new InvalidConfigError(`cannot read ${path}`, { cause: err });
  }
  if (size > MAX_CONFIG_FILE_BYTES) {
    throw new InvalidConfigError(
      `${path} is ${size} bytes, over the ${MAX_CONFIG_FILE_BYTES}-byte limit`,
    );
  }
  return parseConfig(readFileSync(path, 'utf8'), path);
}

/** Validate config file contents; `source` names it in errors. */
export function parseConfig(text: string, source: string): NullPiiFileConfig {
  let value: unknown;
  try {
    value = JSON.parse(text);
  } catch (err) {
    throw new InvalidConfigError(`${source} is not valid JSON`, { cause: err });
  }
  if (!isRecord(value)) throw new InvalidConfigError(`${source} must hold a JSON object`);
  for (const key of Object.keys(value)) {
    if (!KEYS.has(key))
      throw new InvalidConfigError(`${source}: unknown key ${JSON.stringify(key)}`);
  }
  const out: { -readonly [K in keyof NullPiiFileConfig]: NullPiiFileConfig[K] } = {};
  if (value.disabledCategories !== undefined) {
    out.disabledCategories = categoryList(
      value.disabledCategories,
      `${source}: disabledCategories`,
    );
  }
  if (value.categoryThresholds !== undefined) {
    out.categoryThresholds = thresholds(value.categoryThresholds, `${source}: categoryThresholds`);
  }
  if (value.threshold !== undefined)
    out.threshold = unitScore(value.threshold, `${source}: threshold`);
  if (value.urlAllowlist !== undefined)
    out.urlAllowlist = urlAllowlist(value.urlAllowlist, `${source}: urlAllowlist`);
  if (value.restoreTools !== undefined)
    out.restoreTools = toolList(value.restoreTools, `${source}: restoreTools`);
  return out;
}

/** The engine settings of a file config (everything but `restoreTools`). */
export function toEngineConfig(file: NullPiiFileConfig): NullPiiConfig {
  const { restoreTools: _restoreTools, ...engine } = file;
  return engine;
}

function categoryList(value: unknown, where: string): PiiCategory[] {
  if (!Array.isArray(value)) throw new InvalidConfigError(`${where} must be an array`);
  for (const v of value) {
    if (typeof v !== 'string' || !CATEGORIES.has(v)) {
      throw new InvalidConfigError(`${where}: unknown category ${JSON.stringify(v)}`);
    }
  }
  return value as PiiCategory[];
}

function thresholds(value: unknown, where: string): Partial<Record<PiiCategory, number>> {
  if (!isRecord(value)) throw new InvalidConfigError(`${where} must be an object`);
  const out: Partial<Record<PiiCategory, number>> = {};
  for (const [key, score] of Object.entries(value)) {
    if (!CATEGORIES.has(key))
      throw new InvalidConfigError(`${where}: unknown category ${JSON.stringify(key)}`);
    out[key as PiiCategory] = unitScore(score, `${where}.${key}`);
  }
  return out;
}

function unitScore(value: unknown, where: string): number {
  if (typeof value !== 'number' || !(value >= 0 && value <= 1)) {
    throw new InvalidConfigError(`${where} must be a number in [0, 1]`);
  }
  return value;
}

function urlAllowlist(value: unknown, where: string): 'none' | UrlAllowlistConfig {
  if (value === 'none') return value;
  if (!isRecord(value)) throw new InvalidConfigError(`${where} must be "none" or an object`);
  for (const key of Object.keys(value)) {
    if (!URL_ALLOWLIST_KEYS.has(key))
      throw new InvalidConfigError(`${where}: unknown key ${JSON.stringify(key)}`);
  }
  if (value.hosts !== undefined && !isRecord(value.hosts))
    throw new InvalidConfigError(`${where}.hosts must be an object`);
  if (value.replaceDefaults !== undefined && typeof value.replaceDefaults !== 'boolean') {
    throw new InvalidConfigError(`${where}.replaceDefaults must be true or false`);
  }
  const config = value as UrlAllowlistConfig;
  // Validates every host and release, with the engine's own messages.
  urlPolicy(config);
  return config;
}

function toolList(value: unknown, where: string): string[] {
  if (!Array.isArray(value)) throw new InvalidConfigError(`${where} must be an array`);
  for (const v of value) {
    if (typeof v !== 'string' || !TOOL_NAME.test(v)) {
      throw new InvalidConfigError(`${where}: invalid tool name ${JSON.stringify(v)}`);
    }
  }
  return value as string[];
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Whether the default config file exists. Only a missing file means
 * "no config"; any other error (permissions, a directory) is raised. */
function isFile(path: string): boolean {
  try {
    statSync(path);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw new InvalidConfigError(`cannot read ${path}`, { cause: err });
  }
  return true;
}
