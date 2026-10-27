// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';

const PACKAGE_JSON = '../package.json';

/** Read the installed library version from the package beside `src` or `dist`. */
export function nullpiiVersion(): string {
  const pkg = JSON.parse(readFileSync(new URL(PACKAGE_JSON, import.meta.url), 'utf8')) as {
    version?: unknown;
  };
  if (typeof pkg.version !== 'string') throw new Error('package.json has no version');
  return pkg.version;
}
