import { homedir } from 'node:os';
import { join, resolve } from 'node:path';
import debug from 'debug';
import { xdgCacheHome } from './config.js';
import {
  CACHE_DIR_NAME,
  CACHE_MODELS_SUBDIR,
  DEFAULT_MODEL_REPO,
  DEFAULT_MODEL_REVISION,
} from './defaults.js';
import { InvalidPathError } from './errors.js';
import { ensureFile } from './hf-hub.js';
import { resolveSafePath } from './paths.js';
import { MODEL_DOWNLOAD_TIMEOUT_MS, type ModelVariant } from './types/index.js';

const log = debug('nullpii:model-manager');

/** Files required at runtime — full router stack manifest. The HF repo
 * (`lBroth/nullpii-v10-router-embedding` by default) bundles:
 *
 *   - GLiNER backbone tokenizer + SPM (shared by all 5 adapter shards)
 *   - distiluse sentence-encoder ONNX + its tokenizer (router input encoder)
 *   - router prototypes JSON (5 domain centroids + gate margins)
 *   - 5 merged-LoRA GLiNER ONNX (one per domain), under `v10-onnx-merged/`
 *
 * Total artifact size: ~6 GB FP32 (1.1 GB × 5 adapters + 514 MB distiluse).
 * First-call download is one-shot; subsequent calls hit the local cache.
 */
const ROUTER_FILES: readonly string[] = [
  // Shared GLiNER tokenizer + config (same across all per-domain shards).
  'tokenizer.json',
  'spm.model',
  'gliner_config.json',
  // Distiluse encoder + its tokenizer (router input vector).
  'distiluse.onnx',
  'distiluse-tokenizer.json',
  // Prototypes + gate config.
  'router-embeddings.json',
  // Per-domain merged-LoRA ONNX shards.
  'v10-onnx-merged/devops/model.onnx',
  'v10-onnx-merged/legal/model.onnx',
  'v10-onnx-merged/medical/model.onnx',
  'v10-onnx-merged/narrative/model.onnx',
  'v10-onnx-merged/enterprise/model.onnx',
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

  /** Ensure all router-stack artifacts are cached. The `variant` field
   * on `EnsureOptions` is currently unused (all shards are FP32) but
   * preserved for forward-compat with quantized-shard packs. */
  async ensure(options: EnsureOptions = {}): Promise<{ modelDir: string }> {
    const model = options.model ?? DEFAULT_MODEL;
    const timeoutMs = options.timeoutMs ?? MODEL_DOWNLOAD_TIMEOUT_MS;
    const target = this.modelDirFor(model);

    const required = ROUTER_FILES;
    log('ensuring %d files for %s@%s', required.length, model.repo, model.revision.slice(0, 12));

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
