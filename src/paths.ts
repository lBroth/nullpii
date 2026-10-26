// SPDX-License-Identifier: Apache-2.0

import { constants, access } from 'node:fs/promises';
import { isAbsolute, normalize, relative, resolve } from 'node:path';
import { InvalidPathError } from './errors.js';

/** Return true if `path` exists and is readable, false if it does not
 * exist. Any other failure (permissions, I/O) is raised, so a model file
 * nullpii cannot read is not reported as missing. */
export async function fileExists(path: string): Promise<boolean> {
  try {
    await access(path, constants.R_OK);
    return true;
  } catch (err) {
    const code = (err as NodeJS.ErrnoException).code;
    if (code === 'ENOENT' || code === 'ENOTDIR') return false;
    throw err;
  }
}

/**
 * Resolve `userPath` relative to `cwd` (default `process.cwd()`) and ensure
 * it stays within `cwd` after normalization. Rejects absolute paths that
 * escape the working directory and rejects any path containing `..` segments
 * that would resolve outside `cwd`.
 *
 * @throws {InvalidPathError} if the path is unsafe.
 */
export function resolveSafePath(userPath: string, cwd: string = process.cwd()): string {
  const base = resolve(cwd);
  const candidate = isAbsolute(userPath) ? normalize(userPath) : resolve(base, userPath);
  // A plain prefix test would let a sibling through (`/cache-evil` starts
  // with `/cache`); the relative path must not climb out or switch root.
  const rel = relative(base, candidate);
  if (rel.startsWith('..') || isAbsolute(rel)) {
    throw new InvalidPathError(userPath);
  }
  return candidate;
}
