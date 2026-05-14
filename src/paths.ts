// SPDX-License-Identifier: Apache-2.0

import { constants, access } from 'node:fs/promises';
import { isAbsolute, normalize, resolve } from 'node:path';
import { InvalidPathError } from './errors.js';

/** Return true if `path` exists and is readable. False otherwise. */
export async function fileExists(path: string): Promise<boolean> {
  try {
    await access(path, constants.R_OK);
    return true;
  } catch {
    return false;
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
  if (!candidate.startsWith(base)) {
    throw new InvalidPathError(userPath);
  }
  return candidate;
}
