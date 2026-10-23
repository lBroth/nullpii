// SPDX-License-Identifier: Apache-2.0

import { mkdirSync, renameSync, writeFileSync } from 'node:fs';
import { dirname } from 'node:path';
import {
  type CategoryMode,
  DEFAULT_RESTORE_TOOLS,
  type EnginePolicy,
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
    const parsed = parseConfig(text, 'the policy sent to the sidecar');
    writeAtomically(this.file, text);
    np.updatePolicy(enginePolicy(parsed));
    this.current = parsed;
    this.wasLoaded = true;
    this.tools.clear();
    for (const tool of parsed.restoreTools ?? DEFAULT_RESTORE_TOOLS) this.tools.add(tool);
    return parsed;
  }
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
