// SPDX-License-Identifier: Apache-2.0

import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import { XDG_CACHE_HOME, readEnvVar } from './config.js';
import {
  CACHE_DIR_NAME,
  CACHE_MODELS_SUBDIR,
  DEFAULT_BACKEND,
  DEFAULT_MODEL_REPO,
  DEFAULT_MODEL_REVISION,
  DEFAULT_VARIANT,
} from './defaults.js';
import { InvalidPathError } from './errors.js';
import { ensureFile, isMissingFile } from './hf-hub.js';
import { logf } from './log.js';
import { onnxCandidates } from './model-variant.js';
import { resolveSafePath } from './paths.js';
import { type BackendName, MODEL_DOWNLOAD_TIMEOUT_MS, type ModelVariant } from './types/index.js';

const LOG_SCOPE = 'nullpii:model-manager';

/** Files every model directory needs besides its ONNX graph. The HF repo
 * (`lBroth/nullpii` by default) bundles one merged GLiNER ONNX, in fp32 and
 * optionally fp16 (`MODEL_FILES`), plus its tokenizer and config.
 *
 * First-call download is one-shot; subsequent calls hit the local cache.
 */
const SHARED_FILES: readonly string[] = [
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
  const root = readEnvVar(XDG_CACHE_HOME) ?? join(homedir(), '.cache');
  return join(root, CACHE_DIR_NAME, CACHE_MODELS_SUBDIR);
}

export interface EnsureOptions {
  /** ONNX precision to fetch. Default `'auto'` (see `onnxCandidates`). */
  readonly variant?: ModelVariant;
  /** Backend the model will run on; `'auto'` precision depends on it. */
  readonly backend?: BackendName;
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

  /** Ensure the model artifacts are cached: the shared files, then the
   * first ONNX graph of the variant's candidates that the revision has.
   * A later candidate is tried only when the earlier one is missing from
   * the repo (HTTP 404); any other failure surfaces. */
  async ensure(options: EnsureOptions = {}): Promise<{ modelDir: string; onnxFile: string }> {
    const model = options.model ?? DEFAULT_MODEL;
    const timeoutMs = options.timeoutMs ?? MODEL_DOWNLOAD_TIMEOUT_MS;
    const target = this.modelDirFor(model);
    const candidates = onnxCandidates(
      options.variant ?? DEFAULT_VARIANT,
      options.backend ?? DEFAULT_BACKEND,
    );
    const total = SHARED_FILES.length + 1;
    logf(LOG_SCOPE, 'ensure.start', {
      count: total,
      repo: model.repo,
      revision: model.revision.slice(0, 12),
      path: candidates.join(','),
    });

    let done = 0;
    for (const f of SHARED_FILES) {
      await this.fetch(model, f, target, timeoutMs);
      done += 1;
      options.onProgress?.(done / total);
    }
    const onnxFile = await this.fetchFirstAvailable(model, candidates, target, timeoutMs);
    options.onProgress?.(1);
    return { modelDir: target, onnxFile };
  }

  private async fetchFirstAvailable(
    model: ModelRef,
    candidates: readonly string[],
    target: string,
    timeoutMs: number,
  ): Promise<string> {
    for (const [i, f] of candidates.entries()) {
      try {
        await this.fetch(model, f, target, timeoutMs);
        return f;
      } catch (err) {
        if (i === candidates.length - 1 || !isMissingFile(err)) throw err;
        logf(LOG_SCOPE, 'ensure.fallback', { path: f });
      }
    }
    throw new Error('model-manager: no ONNX candidate');
  }

  private async fetch(
    model: ModelRef,
    file: string,
    target: string,
    timeoutMs: number,
  ): Promise<void> {
    this.assertSafeRelative(file, target);
    await ensureFile(model.repo, model.revision, file, target, { timeoutMs });
  }

  private assertSafeRelative(relative: string, base: string): void {
    if (relative.includes('..')) throw new InvalidPathError(relative);
    resolveSafePath(relative, base);
  }
}
