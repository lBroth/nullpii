// SPDX-License-Identifier: Apache-2.0

import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { xdgCacheHome } from './config.js';
import {
  CACHE_DIR_NAME,
  CACHE_MODELS_SUBDIR,
  DEFAULT_MODEL_REPO,
  DEFAULT_MODEL_REVISION,
} from './defaults.js';
import { InvalidPathError } from './errors.js';
import { ensureFile } from './hf-hub.js';
import { logf } from './log.js';
import { resolveSafePath } from './paths.js';
import { MODEL_DOWNLOAD_TIMEOUT_MS, type ModelVariant } from './types/index.js';

const LOG_SCOPE = 'nullpii:model-manager';

/** Files required at runtime — unified single-ONNX manifest. The HF repo
 * (`lBroth/nullpii` by default) bundles one merged GLiNER ONNX plus its
 * tokenizer.
 *
 * Total artifact size: ~1.16 GB FP32 (~349 MB int8 if/when shipped).
 * First-call download is one-shot; subsequent calls hit the local cache.
 */
const UNIFIED_FILES: readonly string[] = [
  'model.onnx',
  'tokenizer.json',
  'gliner_config.json',
  'tokenizer_config.json',
];

/** Identifies which model artifact set to fetch. Pluggable so callers can
 * swap to a fork or alternative model without forking the library. */
export interface ModelRef {
  /** HuggingFace `<org>/<repo>` (or compatible mirror). */
  readonly repo: string;
  /** Pinned commit SHA. Use `'main'` ONLY for development. */
  readonly revision: string;
}

export const DEFAULT_MODEL: ModelRef = {
  repo: DEFAULT_MODEL_REPO,
  revision: DEFAULT_MODEL_REVISION,
};

/** XDG-style default cache: `$XDG_CACHE_HOME/nullpii/models/` if set,
 * else `~/.cache/nullpii/models/`. Shared across projects on the same host. */
export function defaultCacheDir(): string {
  const root = xdgCacheHome() ?? join(homedir(), '.cache');
  return join(root, CACHE_DIR_NAME, CACHE_MODELS_SUBDIR);
}

export interface EnsureOptions {
  readonly variant?: ModelVariant;
  readonly timeoutMs?: number;
  readonly model?: ModelRef;
  /** Reports per-file download progress (0..1 over the variant manifest). */
  readonly onProgress?: (progress: number) => void;
}

/**
 * Manages on-disk caching of model artifacts.
 *
 * Cache layout: `<root>/<repo>/<revision>/<file>`. Revisions are isolated
 * so a future bump fetches side-by-side without disturbing existing ones.
 */
export class ModelManager {
  private readonly cacheDir: string;

  constructor(cacheDir: string = defaultCacheDir()) {
    this.cacheDir = resolve(cacheDir);
  }

  /** Where the artifacts for `model` (or the default) live on disk. */
  modelDirFor(model: ModelRef = DEFAULT_MODEL): string {
    return join(this.cacheDir, model.repo, model.revision);
  }

  /** Backwards-compatible accessor for the default model dir. */
  get modelDir(): string {
    return this.modelDirFor(DEFAULT_MODEL);
  }

  /** Ensure the unified model artifacts are cached. The `variant` field
   * on `EnsureOptions` is currently unused (default is FP32) — preserved
   * for forward-compat when a quantized (`int4`/`int8`) variant is
   * published alongside `model.onnx`. */
  async ensure(options: EnsureOptions = {}): Promise<{ modelDir: string }> {
    const model = options.model ?? DEFAULT_MODEL;
    const timeoutMs = options.timeoutMs ?? MODEL_DOWNLOAD_TIMEOUT_MS;
    const target = this.modelDirFor(model);

    const required = UNIFIED_FILES;
    logf(LOG_SCOPE, 'ensure.start', {
      count: required.length,
      repo: model.repo,
      revision: model.revision.slice(0, 12),
    });

    let done = 0;
    for (const f of required) {
      this.assertSafeRelative(f, target);
      await ensureFile(model.repo, model.revision, f, target, { timeoutMs });
      done += 1;
      options.onProgress?.(done / required.length);
    }
    return { modelDir: target };
  }

  private assertSafeRelative(relative: string, base: string): void {
    if (relative.includes('..')) throw new InvalidPathError(relative);
    resolveSafePath(relative, base);
  }
}
