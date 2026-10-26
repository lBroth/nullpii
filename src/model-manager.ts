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
  DEFAULT_MODEL_SHA256,
  DEFAULT_VARIANT,
} from './defaults.js';
import { InvalidConfigError, InvalidPathError } from './errors.js';
import { ensureFile, isCachedFile } from './hf-hub.js';
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
export const SHARED_FILES: readonly string[] = [
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
  /** Expected SHA-256 of each file, by name. When given, every file
   * fetched must be listed, and a download or cached copy with another
   * hash is refused. */
  readonly sha256?: Readonly<Record<string, string>>;
}

export const DEFAULT_MODEL: ModelRef = {
  repo: DEFAULT_MODEL_REPO,
  revision: DEFAULT_MODEL_REVISION,
  sha256: DEFAULT_MODEL_SHA256,
};

/** A pinned SHA-256: 64 lower-case hex digits, as `sha256File` prints. */
const SHA256_HEX = /^[0-9a-f]{64}$/;

/** The SHA-256 `model` pins for `file`; `undefined` when it pins none.
 * A model that pins hashes must pin every file it fetches. */
function expectedSha(model: ModelRef, file: string): string | undefined {
  if (model.sha256 === undefined) return undefined;
  const sha = model.sha256[file];
  if (sha === undefined) {
    throw new InvalidConfigError(`${model.repo}@${model.revision} pins no SHA-256 for ${file}`);
  }
  if (!SHA256_HEX.test(sha)) {
    throw new InvalidConfigError(
      `${model.repo}@${model.revision} pins ${file} to a SHA-256 that is not 64 lower-case hex digits`,
    );
  }
  return sha;
}

/** The candidates a model can load: with pins, only the pinned files, so
 * a variant the pins leave out (`fp16`) falls back to one they cover. */
function pinnedCandidates(model: ModelRef, candidates: readonly string[]): readonly string[] {
  const pins = model.sha256;
  if (pins === undefined) return candidates;
  const pinned = candidates.filter((f) => pins[f] !== undefined);
  if (pinned.length === 0) {
    throw new InvalidConfigError(
      `${model.repo}@${model.revision} pins none of ${candidates.join(', ')}`,
    );
  }
  return pinned;
}

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
  /** Reports the bytes of the file being downloaded so far (`onBytes` of
   * `ensureFile`), with the file's name. */
  readonly onBytes?: (file: string, received: number, total: number | undefined) => void;
}

/**
 * Manages on-disk caching of model artifacts.
 *
 * Cache layout: `<root>/<repo>/<revision>/<file>`. Revisions are isolated
 * so a future bump fetches side-by-side without disturbing existing ones.
 */
/** A HuggingFace repository id: `org/name`. */
const HF_REPO_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*\/[A-Za-z0-9][A-Za-z0-9._-]*$/;
/** A branch, tag or commit; branches may contain `/` (`refs/pr/1`). */
const HF_REVISION = /^[A-Za-z0-9._-]+(?:\/[A-Za-z0-9._-]+)*$/;

export class ModelManager {
  private readonly cacheDir: string;

  constructor(cacheDir: string = defaultCacheDir()) {
    this.cacheDir = resolve(cacheDir);
  }

  /** Where the artifacts for `model` (or the default) live on disk. The
   * repo and revision become path segments, so they are validated first:
   * a HuggingFace `org/name` id and a branch, tag or commit, never a path
   * that leaves the cache. */
  modelDirFor(model: ModelRef = DEFAULT_MODEL): string {
    if (!HF_REPO_ID.test(model.repo)) throw new InvalidPathError(model.repo);
    if (!HF_REVISION.test(model.revision) || model.revision.split('/').includes('..')) {
      throw new InvalidPathError(model.revision);
    }
    return resolveSafePath(join(model.repo, model.revision), this.cacheDir);
  }

  /** Backwards-compatible accessor for the default model dir. */
  get modelDir(): string {
    return this.modelDirFor(DEFAULT_MODEL);
  }

  /** Ensure the model artifacts are cached: the shared files, then one
   * ONNX graph from the variant's candidates (see `pickOnnx`). */
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
      await this.fetch(model, f, target, timeoutMs, options.onBytes);
      done += 1;
      options.onProgress?.(done / total);
    }
    const onnxFile = await this.pickOnnx(model, candidates, target, timeoutMs, options.onBytes);
    options.onProgress?.(1);
    return { modelDir: target, onnxFile };
  }

  /** The ONNX graph to use, best candidate first.
   *
   * A candidate already cached and verified wins before any network call,
   * so a warm or offline cache keeps working and init never downloads a
   * second 0.6–1.2 GB file nobody asked for (`nullpii prefetch --variant`
   * does that). Otherwise each candidate is downloaded in turn; when one
   * fails for any reason the next is tried, and the last error surfaces. */
  private async pickOnnx(
    model: ModelRef,
    candidates: readonly string[],
    target: string,
    timeoutMs: number,
    onBytes: EnsureOptions['onBytes'],
  ): Promise<string> {
    const usable = pinnedCandidates(model, candidates);
    for (const f of usable) {
      this.assertSafeRelative(f, target);
      if (await isCachedFile(target, f, expectedSha(model, f))) return f;
    }
    let lastErr: unknown;
    for (const f of usable) {
      try {
        await this.fetch(model, f, target, timeoutMs, onBytes);
        return f;
      } catch (err) {
        lastErr = err;
        logf(LOG_SCOPE, 'ensure.fallback', { path: f });
      }
    }
    throw lastErr;
  }

  private async fetch(
    model: ModelRef,
    file: string,
    target: string,
    timeoutMs: number,
    onBytes: EnsureOptions['onBytes'] = undefined,
  ): Promise<void> {
    this.assertSafeRelative(file, target);
    const sha = expectedSha(model, file);
    await ensureFile(model.repo, model.revision, file, target, {
      timeoutMs,
      ...(sha !== undefined && { expectedSha: sha }),
      ...(onBytes !== undefined && {
        onBytes: (received, total) => onBytes(file, received, total),
      }),
    });
  }

  private assertSafeRelative(relative: string, base: string): void {
    if (relative.includes('..')) throw new InvalidPathError(relative);
    resolveSafePath(relative, base);
  }
}
