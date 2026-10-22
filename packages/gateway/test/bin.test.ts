// SPDX-License-Identifier: Apache-2.0
//
// The `nullpii-gateway` command line: `--version` and `--help` answer
// without reading any configuration, and anything else on the command
// line is an error that starts no server.

import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const BIN = fileURLToPath(new URL('../bin/nullpii-gateway.mjs', import.meta.url));
const PACKAGE_JSON = new URL('../package.json', import.meta.url);
const USAGE_EXIT = 2;

function run(...args: string[]) {
  return spawnSync(process.execPath, [BIN, ...args], { encoding: 'utf8' });
}

describe('nullpii-gateway command line', () => {
  it.each(['--version', '-v'])('prints the package version for %s', (flag) => {
    const { version } = JSON.parse(readFileSync(PACKAGE_JSON, 'utf8')) as { version: string };
    const r = run(flag);
    expect(r.status).toBe(0);
    expect(r.stdout).toBe(`${version}\n`);
  });

  it.each(['--help', '-h'])('prints the usage for %s', (flag) => {
    const r = run(flag);
    expect(r.status).toBe(0);
    expect(r.stdout).toContain('Usage: nullpii-gateway');
  });

  it.each([['--bogus'], ['--'], [''], ['--version', '--bogus'], ['--help', 'extra'], ['-v', '-h']])(
    'refuses %j with the usage and no server',
    (...args) => {
      const r = run(...args);
      expect(r.status).toBe(USAGE_EXIT);
      expect(r.stdout).toBe('');
      expect(r.stderr).toContain('unexpected argument');
    },
  );
});
