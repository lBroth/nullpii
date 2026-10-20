// SPDX-License-Identifier: Apache-2.0

import { createHash, randomBytes } from 'node:crypto';
import { createReadStream, createWriteStream, existsSync } from 'node:fs';
import { mkdir, readFile, rename, unlink, writeFile } from 'node:fs/promises';
import { basename, dirname, join } from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { setTimeout as sleep } from 'node:timers/promises';
import { CHECKSUM_SUFFIX } from './defaults.js';
import { ModelNotFoundError } from './errors.js';
import { logf } from './log.js';

const LOG_SCOPE = 'nullpii:hf-hub';

const HF_HOST = 'https://huggingface.co';
const SHA_SUFFIX = CHECKSUM_SUFFIX;

const MAX_ATTEMPTS = 4;
const BACKOFF_BASE_MS = 500;
const BACKOFF_MAX_MS = 8000;
const RETRYABLE_HTTP = new Set([408, 425, 429, 500, 502, 503, 504]);

/** URL of a single file at a pinned revision on HuggingFace Hub. */
export function fileUrl(repo: string, revision: string, file: string): string {
  return `${HF_HOST}/${repo}/resolve/${revision}/${encodeURI(file)}`;
}

/** `true` when `<destDir>/<file>` is already cached, matches its checksum
 * sidecar and, when `expectedSha` is given, has that SHA-256, so using it
 * needs no network call. */
export async function isCachedFile(
  destDir: string,
  file: string,
  expectedSha?: string,
): Promise<boolean> {
  const verified = await verifiedSha(join(destDir, file));
  return verified !== null && (expectedSha === undefined || verified === expectedSha);
}

/**
 * Download `file` from `repo@revision` into `<destDir>/<file>` if not already
 * present and verified. Idempotent. A cached copy is used only when it
 * matches its sidecar and, when `expectedSha` is given, that SHA-256; a
 * cached copy with another hash is downloaded again. Retries transient
 * network errors with exponential backoff before surfacing
 * `ModelNotFoundError`.
 */
export async function ensureFile(
  repo: string,
  revision: string,
  file: string,
  destDir: string,
  options: { readonly expectedSha?: string; readonly timeoutMs: number },
): Promise<string> {
  const dest = join(destDir, file);
  await mkdir(dirname(dest), { recursive: true });

  if (await isCachedFile(destDir, file, options.expectedSha)) {
    logf(LOG_SCOPE, 'cache.hit', { path: dest });
    return dest;
  }

  const url = fileUrl(repo, revision, file);
  const sha = await retryDownload(url, dest, options.timeoutMs);
  if (options.expectedSha !== undefined && options.expectedSha !== sha) {
    await unlink(dest);
    throw new ModelNotFoundError(`${dest} (sha mismatch)`);
  }
  await writeSidecar(dest, sha);
  return dest;
}

async function retryDownload(url: string, dest: string, timeoutMs: number): Promise<string> {
  let lastErr: unknown;
  for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt++) {
    try {
      logf(LOG_SCOPE, 'download.start', { url, attempt, maxAttempts: MAX_ATTEMPTS });
      return await downloadWithTimeout(url, dest, timeoutMs);
    } catch (err) {
      lastErr = err;
      if (!isRetryable(err) || attempt === MAX_ATTEMPTS) break;
      const delay = Math.min(BACKOFF_BASE_MS * 2 ** (attempt - 1), BACKOFF_MAX_MS);
      logf(LOG_SCOPE, 'download.retry', { delayMs: delay, attempt });
      await sleep(delay);
    }
  }
  throw lastErr instanceof Error ? lastErr : new ModelNotFoundError(`${url} (download failed)`);
}

/** Node fetch / DNS / socket error codes that are worth retrying. */
const RETRYABLE_ERROR_CODES = new Set([
  'ABORT_ERR',
  'ECONNRESET',
  'ECONNREFUSED',
  'ETIMEDOUT',
  'ENETUNREACH',
  'ENETDOWN',
  'EAI_AGAIN',
  'EPIPE',
  'UND_ERR_SOCKET',
  'UND_ERR_CONNECT_TIMEOUT',
  'UND_ERR_HEADERS_TIMEOUT',
  'UND_ERR_BODY_TIMEOUT',
]);

function isRetryable(err: unknown): boolean {
  if (err instanceof ModelNotFoundError) {
    const m = err.message;
    const httpMatch = m.match(/HTTP (\d+)/);
    if (httpMatch !== null) return RETRYABLE_HTTP.has(Number(httpMatch[1]));
    return true;
  }
  // Network / abort errors expose either `code` or `name`; everything
  // else (TypeError, RangeError, programmer bugs) is NOT retried — re-
  // trying a deterministic crash is wasted budget and hides the bug.
  if (err instanceof Error) {
    if (err.name === 'AbortError') return true;
    const code = (err as { code?: unknown }).code;
    if (typeof code === 'string' && RETRYABLE_ERROR_CODES.has(code)) return true;
  }
  return false;
}

async function downloadWithTimeout(url: string, dest: string, timeoutMs: number): Promise<string> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  // Per-process, per-attempt temp name: two concurrent `sanitize()` calls on
  // a cold cache must not interleave writes into the same `.partial` file.
  const tmp = `${dest}.${process.pid}.${randomBytes(6).toString('hex')}.partial`;
  try {
    const res = await fetch(url, { signal: controller.signal });
    if (!res.ok || res.body === null) {
      throw new ModelNotFoundError(`${url} (HTTP ${res.status})`);
    }
    const hash = createHash('sha256');
    await pipeline(
      Readable.fromWeb(res.body as Parameters<typeof Readable.fromWeb>[0]),
      async function* (source) {
        for await (const chunk of source) {
          hash.update(chunk as Buffer);
          yield chunk;
        }
      },
      createWriteStream(tmp),
    );
    await rename(tmp, dest);
    return hash.digest('hex');
  } catch (err) {
    await removePartial(tmp);
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/** Delete a partial download after a failed attempt. A missing file is
 * fine; any other failure is logged, and the download error that led
 * here is what the caller sees. */
async function removePartial(path: string): Promise<void> {
  try {
    await unlink(path);
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT')
      logf(LOG_SCOPE, 'download.cleanup_failed', { path, errorCode: code ?? 'unknown' });
  }
}

/** The SHA-256 of `file` when it exists and matches its checksum sidecar,
 * else `null`. */
async function verifiedSha(file: string): Promise<string | null> {
  const sidecar = `${file}${SHA_SUFFIX}`;
  if (!existsSync(file) || !existsSync(sidecar)) return null;
  const expected = (await readFile(sidecar, 'utf-8')).trim().split(/\s+/)[0] ?? '';
  if (expected.length !== 64) return null;
  return (await sha256File(file)) === expected ? expected : null;
}

/** SHA-256 of a file, streamed: the ONNX graphs are 0.6–1.2 GB. */
export async function sha256File(file: string): Promise<string> {
  const hash = createHash('sha256');
  await pipeline(createReadStream(file), hash);
  return hash.digest('hex');
}

async function writeSidecar(file: string, sha: string): Promise<void> {
  const sidecar = `${file}${SHA_SUFFIX}`;
  await mkdir(dirname(sidecar), { recursive: true });
  await writeFile(sidecar, `${sha}  ${basename(file)}\n`, 'utf-8');
}
