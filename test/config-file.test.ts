// SPDX-License-Identifier: Apache-2.0

import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  configFilePath,
  defaultConfigPath,
  loadConfigFile,
  parseConfig,
  resolveConfigFile,
  toEngineConfig,
} from '../src/config-file.js';
import { InvalidConfigError } from '../src/errors.js';

let dir = '';
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'nullpii-config-'));
});
afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
  vi.unstubAllEnvs();
});

const write = (name: string, body: string): string => {
  const path = join(dir, name);
  writeFileSync(path, body);
  return path;
};

describe('parseConfig', () => {
  it('accepts a full policy', () => {
    const config = parseConfig(
      JSON.stringify({
        disabledCategories: ['private_organization'],
        categoryThresholds: { private_date: 0.2 },
        threshold: 0.05,
        urlAllowlist: { hosts: { '*.github.com': 'full' } },
        restoreTools: ['Bash', 'mcp__files__read'],
      }),
      'test',
    );
    expect(config.restoreTools).toEqual(['Bash', 'mcp__files__read']);
    expect(toEngineConfig(config)).toEqual({
      disabledCategories: ['private_organization'],
      categoryThresholds: { private_date: 0.2 },
      threshold: 0.05,
      urlAllowlist: { hosts: { '*.github.com': 'full' } },
    });
  });

  it.each([
    ['not JSON', '{'],
    ['not an object', '[]'],
    ['an unknown key', '{"disabledCategory": []}'],
    ['an unknown category', '{"disabledCategories": ["private_pet"]}'],
    ['a threshold out of range', '{"threshold": 1.5}'],
    [
      'a category threshold that is not a number',
      '{"categoryThresholds": {"private_date": "0.2"}}',
    ],
    ['an unknown urlAllowlist key', '{"urlAllowlist": {"host": {}}}'],
    ['a malformed host', '{"urlAllowlist": {"hosts": {"https://github.com": "full"}}}'],
    ['an unknown release', '{"urlAllowlist": {"hosts": {"github.com": "partial"}}}'],
    ['an invalid tool name', '{"restoreTools": ["rm -rf"]}'],
  ])('rejects %s', (_case, body) => {
    expect(() => parseConfig(body, 'test')).toThrow(InvalidConfigError);
  });
});

describe('loadConfigFile and resolveConfigFile', () => {
  it('loads a file', () => {
    expect(loadConfigFile(write('c.json', '{"threshold": 0.1}'))).toEqual({ threshold: 0.1 });
  });

  it('rejects a missing path, a directory and an oversized file', () => {
    expect(() => loadConfigFile(join(dir, 'missing.json'))).toThrow(InvalidConfigError);
    expect(() => loadConfigFile(dir)).toThrow(InvalidConfigError);
    expect(() =>
      loadConfigFile(write('big.json', `{"threshold": 0.1${' '.repeat(70_000)}}`)),
    ).toThrow(InvalidConfigError);
  });

  it('prefers the explicit path, then NULLPII_CONFIG, then the default location', () => {
    vi.stubEnv('XDG_CONFIG_HOME', dir);
    expect(defaultConfigPath()).toBe(join(dir, 'nullpii', 'config.json'));
    expect(configFilePath()).toBeNull();
    expect(resolveConfigFile()).toBeNull();
    mkdirSync(join(dir, 'nullpii'));
    write('nullpii/config.json', '{"threshold": 0.3}');
    expect(configFilePath()).toBe(defaultConfigPath());
    expect(resolveConfigFile()).toEqual({ threshold: 0.3 });
    const env = write('env.json', '{"threshold": 0.2}');
    vi.stubEnv('NULLPII_CONFIG', env);
    expect(configFilePath()).toBe(env);
    expect(resolveConfigFile()).toEqual({ threshold: 0.2 });
    const flag = write('flag.json', '{"threshold": 0.1}');
    expect(configFilePath(flag)).toBe(flag);
    expect(resolveConfigFile(flag)).toEqual({ threshold: 0.1 });
  });

  it('fails when NULLPII_CONFIG names a file that does not exist', () => {
    vi.stubEnv('NULLPII_CONFIG', join(dir, 'missing.json'));
    expect(() => resolveConfigFile()).toThrow(InvalidConfigError);
  });
});
