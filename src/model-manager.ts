// SPDX-License-Identifier: Apache-2.0
import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import debug from 'debug';
import { xdgCacheHome } from './config.js';
import {
  CACHE_DIR_NAME,
  CACHE_MODELS_SUBDIR,
  DEFAULT_MODEL_REPO,
  DEFAULT_MODEL_REVISION,
  DEFAULT_VARIANT,
  MANAGER_DEFAULT_VARIANT,
} from './defaults.js';
import { InvalidPathError } from './errors.js';
import { ensureFile } from './hf-hub.js';
import { resolveSafePath } from './paths.js';
import { MODEL_DOWNLOAD_TIMEOUT_MS, type ModelVariant } from './types/index.js';

const log = debug('nullpii:model-manager');

/** Files required at runtime for any backend. Variant-specific ONNX is added on demand. */
const COMMON_FILES: readonly string[] = [
  'config.json',
  'tokenizer.json',
  'tokenizer_config.json',
  'viterbi_calibration.json',
];

const VARIANT_FILES: Readonly<Record<Exclude<ModelVariant, 'auto'>, readonly string[]>> = {
  fp32: [
    'onnx/model.onnx',
    'onnx/model.onnx_data',
    'onnx/model.onnx_data_1',
    'onnx/model.onnx_data_2',
  ],
  fp16: ['onnx/model_fp16.onnx', 'onnx/model_fp16.onnx_data', 'onnx/model_fp16.onnx_data_1'],
  int8: ['onnx/model_quantized.onnx', 'onnx/model_quantized.onnx_data'],
  int4: ['onnx/model_q4.onnx', 'onnx/model_q4.onnx_data'],
  int4f16: ['onnx/model_q4f16.onnx', 'onnx/model_q4f16.onnx_data'],
};

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

  /** Ensure all artifacts needed for `variant` are cached and verified. */
  async ensure(options: EnsureOptions = {}): Promise<{ modelDir: string }> {
    const variant = options.variant ?? DEFAULT_VARIANT;
    const concrete = variant === 'auto' ? MANAGER_DEFAULT_VARIANT : variant;
    const model = options.model ?? DEFAULT_MODEL;
    const timeoutMs = options.timeoutMs ?? MODEL_DOWNLOAD_TIMEOUT_MS;
    const target = this.modelDirFor(model);

    const required = [...COMMON_FILES, ...VARIANT_FILES[concrete]];
    log(
      'ensuring %d files for %s@%s variant=%s',
      required.length,
      model.repo,
      model.revision.slice(0, 12),
      concrete,
    );

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
