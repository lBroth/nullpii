// SPDX-License-Identifier: Apache-2.0
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import type { NullPiiConfig } from 'nullpii';

const SETTINGS_FILE = '.claude/settings.json';

export interface PluginSettings {
  readonly backend?: NullPiiConfig['backend'];
  readonly variant?: NullPiiConfig['variant'];
  readonly modelDir?: string;
  readonly threshold?: number;
  readonly labels?: ReadonlyArray<string>;
  /** Regex source patterns; prompts whose first line matches any of them
   * (e.g. `^/git\b`) are forwarded to Claude unchanged. */
  readonly skip?: ReadonlyArray<string>;
}

/** Read `.claude/settings.json` (under `projectRoot`) and pluck the
 * `nullpii` block. Missing file or missing block → return empty settings.
 * Malformed JSON → also return empty settings (best-effort, never throw). */
export function readPluginSettings(projectRoot: string = process.cwd()): PluginSettings {
  try {
    const raw = readFileSync(join(projectRoot, SETTINGS_FILE), 'utf-8');
    const parsed = JSON.parse(raw) as { nullpii?: PluginSettings };
    return parsed.nullpii ?? {};
  } catch {
    return {};
  }
}

export function toNullPiiConfig(settings: PluginSettings): NullPiiConfig {
  const out: { -readonly [K in keyof NullPiiConfig]: NullPiiConfig[K] } = {};
  if (settings.backend !== undefined) out.backend = settings.backend;
  if (settings.variant !== undefined) out.variant = settings.variant;
  if (settings.modelDir !== undefined) out.modelDir = settings.modelDir;
  if (settings.threshold !== undefined) out.threshold = settings.threshold;
  return out;
}
