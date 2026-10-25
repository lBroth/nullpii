// SPDX-License-Identifier: Apache-2.0

import { createHash } from 'node:crypto';
import { mkdirSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import {
  type CategoryMode,
  DEFAULT_RESTORE_TOOLS,
  type EnginePolicy,
  InvalidConfigError,
  MAX_CONFIG_FILE_BYTES,
  type NullPii,
  type NullPiiFileConfig,
  type PiiCategory,
  categoryModes,
  parseConfig,
  toEngineConfig,
} from 'nullpii';

/** The policy directory and file belong to the user alone. */
const DIR_MODE = 0o700;
const FILE_MODE = 0o600;
/** Hex characters of the SHA-256 kept as the policy's version. */
const VERSION_CHARS = 32;

/**
 * The masking policy a running gateway applies, which the sidecar's
 * `PUT /v1/sidecar/policy` can replace: the policy file's contents, its
 * path, and the tools that get real values back. `restoreTools` is one
 * set for the gateway's life, updated in place, so every route holding it
 * sees a change at once.
 */
export class LivePolicy {
  private current: NullPiiFileConfig;
  private wasLoaded: boolean;
  private readonly tools: Set<string>;
  private stamp: string;

  /** @param restoreTools - the tools in effect at start (the gateway's
   *   config, which already resolved the policy's list or the default). */
  constructor(
    config: NullPiiFileConfig,
    readonly file: string,
    loaded: boolean,
    restoreTools: Iterable<string>,
  ) {
    this.current = config;
    this.wasLoaded = loaded;
    this.tools = new Set(restoreTools);
    this.stamp = versionOf(config, this.tools);
  }

  /** The policy's version: a digest of its contents and restore tools,
   * the same across gateway restarts for the same policy. A caller sends
   * the version it last saw, and is refused when the policy has changed
   * since (`routes/sidecar.ts`). */
  get version(): string {
    return this.stamp;
  }

  /** The policy file's contents now in effect. */
  get config(): NullPiiFileConfig {
    return this.current;
  }

  /** Whether the policy comes from a file (loaded at start, or written). */
  get loaded(): boolean {
    return this.wasLoaded;
  }

  /** The tools whose arguments get real values back. */
  get restoreTools(): ReadonlySet<string> {
    return this.tools;
  }

  /** The mode of every category under the policy in effect. */
  modes(): Readonly<Record<PiiCategory, CategoryMode>> {
    return categoryModes(this.current);
  }

  /**
   * Validate `config` as a policy file, write it to the policy file
   * (atomically, readable by the user only), and apply it: to `np`, whose
   * categories, thresholds and URL allowlist change for every later
   * request, and to the restore tools. Throws `InvalidConfigError` and
   * changes nothing when `config` is not a valid policy.
   */
  replace(np: NullPii, config: unknown): NullPiiFileConfig {
    const text = `${JSON.stringify(config, null, 2)}\n`;
    // The file must load at the next start, which refuses a larger one.
    if (Buffer.byteLength(text) > MAX_CONFIG_FILE_BYTES) {
      throw new InvalidConfigError(
        `the policy sent to the sidecar is over the ${MAX_CONFIG_FILE_BYTES}-byte limit`,
      );
    }
    const parsed = parseConfig(text, 'the policy sent to the sidecar');
    writeAtomically(this.file, text);
    np.updatePolicy(enginePolicy(parsed));
    this.current = parsed;
    this.wasLoaded = true;
    this.tools.clear();
    for (const tool of parsed.restoreTools ?? DEFAULT_RESTORE_TOOLS) this.tools.add(tool);
    this.stamp = versionOf(parsed, this.tools);
    return parsed;
  }
}

/** A digest of `config` and the restore tools, in a fixed order. */
function versionOf(config: NullPiiFileConfig, tools: ReadonlySet<string>): string {
  const text = JSON.stringify({ config: sortedKeys(config), restoreTools: [...tools].sort() });
  return createHash('sha256').update(text).digest('hex').slice(0, VERSION_CHARS);
}

/** `value` with every object's keys sorted, for a stable digest. */
function sortedKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortedKeys);
  if (value === null || typeof value !== 'object') return value;
  const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
    a < b ? -1 : a > b ? 1 : 0,
  );
  return Object.fromEntries(entries.map(([k, v]) => [k, sortedKeys(v)]));
}

/** The settings of `file` a running engine takes (`NullPii.updatePolicy`). */
function enginePolicy(file: NullPiiFileConfig): EnginePolicy {
  const engine = toEngineConfig(file);
  return {
    ...(engine.disabledCategories !== undefined && {
      disabledCategories: engine.disabledCategories,
    }),
    ...(engine.categoryThresholds !== undefined && {
      categoryThresholds: engine.categoryThresholds,
    }),
    ...(engine.threshold !== undefined && { threshold: engine.threshold }),
    ...(engine.urlAllowlist !== undefined && { urlAllowlist: engine.urlAllowlist }),
  };
}

/** Write `text` to `path` through a temporary file in the same directory,
 * so a reader never sees half a policy. */
function writeAtomically(path: string, text: string): void {
  mkdirSync(dirname(path), { recursive: true, mode: DIR_MODE });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, text, { mode: FILE_MODE });
  renameSync(temporary, path);
}
