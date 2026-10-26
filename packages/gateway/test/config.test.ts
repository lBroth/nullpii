// SPDX-License-Identifier: Apache-2.0

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { DEFAULT_RESTORE_TOOLS } from 'nullpii';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { loadConfig } from '../src/config.js';

let dir = '';
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'nullpii-gw-config-'));
  // No config file in the default location.
  vi.stubEnv('XDG_CONFIG_HOME', dir);
});
afterEach(() => {
  vi.unstubAllEnvs();
  rmSync(dir, { recursive: true, force: true });
});

describe('loadConfig', () => {
  it('uses safe defaults', () => {
    const c = loadConfig();
    expect(c).toMatchObject({
      host: '127.0.0.1',
      port: 8787,
      upstreamBaseUrl: 'https://api.anthropic.com',
      openaiUpstreamBaseUrl: 'https://api.openai.com',
      backend: 'cpu',
      logTraffic: false,
      appendHint: true,
      policy: {},
    });
    expect(c.sidecarToken).toBeUndefined();
    expect([...c.restoreTools]).toEqual([...DEFAULT_RESTORE_TOOLS]);
    expect(c.policyFile).toBe(join(dir, 'nullpii', 'config.json'));
    expect(c.policyLoaded).toBe(false);
  });

  it('reads every variable and treats empty ones as unset', () => {
    vi.stubEnv('NULLPII_HOST', '');
    vi.stubEnv('NULLPII_MODEL_DIR', '');
    vi.stubEnv('NULLPII_PORT', '9000');
    vi.stubEnv('NULLPII_UPSTREAM', 'https://proxy.test///');
    vi.stubEnv('NULLPII_OPENAI_UPSTREAM', 'https://openai.proxy.test');
    vi.stubEnv('NULLPII_BACKEND', 'cuda');
    vi.stubEnv('NULLPII_LOG_TRAFFIC', 'wire');
    vi.stubEnv('NULLPII_DISABLE_HINT', '1');
    vi.stubEnv('NULLPII_SIDECAR_TOKEN', 'x'.repeat(32));
    const c = loadConfig();
    expect(c).toMatchObject({
      host: '127.0.0.1',
      port: 9000,
      upstreamBaseUrl: 'https://proxy.test',
      openaiUpstreamBaseUrl: 'https://openai.proxy.test',
      backend: 'cuda',
      logTraffic: true,
      appendHint: false,
      sidecarToken: 'x'.repeat(32),
    });
    expect(c.modelDir).toBeUndefined();
  });

  it.each([
    ['NULLPII_PORT', 'eighty'],
    ['NULLPII_PORT', '-1'],
    ['NULLPII_PORT', '0'],
    ['NULLPII_PORT', '65536'],
    ['NULLPII_PORT', '80.5'],
    ['NULLPII_VAULT_TTL_MS', '30m'],
    ['NULLPII_VAULT_TTL_MS', '0'],
    ['NULLPII_VAULT_TTL_MS', '999'],
    ['NULLPII_VAULT_TTL_MS', '1e6'],
    ['NULLPII_BODY_LIMIT_BYTES', '0'],
    ['NULLPII_SIDECAR_MAX_SESSIONS', '0'],
    ['NULLPII_BACKEND', 'gpu'],
    ['NULLPII_LOG_LEVEL', 'loud'],
    ['NULLPII_OPENAI_UPSTREAM', 'https://api.openai.com/v1'],
    ['NULLPII_SIDECAR_TOKEN', 'short'],
  ])('rejects %s=%s', (name, value) => {
    vi.stubEnv(name, value);
    expect(() => loadConfig()).toThrow();
  });

  it('names the variable and the allowed range in the error', () => {
    vi.stubEnv('NULLPII_VAULT_TTL_MS', '30m');
    expect(() => loadConfig()).toThrow(/NULLPII_VAULT_TTL_MS must be an integer of at least 1000/);
  });

  it.each([
    ['1', false],
    ['0', true],
  ])('reads NULLPII_DISABLE_HINT=%s', (value, appendHint) => {
    vi.stubEnv('NULLPII_DISABLE_HINT', value);
    expect(loadConfig().appendHint).toBe(appendHint);
  });

  it.each(['true', 'false', 'yes', 'on', ' 1'])(
    'refuses NULLPII_DISABLE_HINT=%j instead of ignoring it',
    (value) => {
      vi.stubEnv('NULLPII_DISABLE_HINT', value);
      expect(() => loadConfig()).toThrow(/NULLPII_DISABLE_HINT must be one of 1\|0/);
    },
  );

  it.each([
    ['https://proxy.test///', 'https://proxy.test'],
    ['https://OpenRouter.ai/api/', 'https://openrouter.ai/api'],
    ['http://127.0.0.1:11434', 'http://127.0.0.1:11434'],
    ['http://127.0.0.1:8080/', 'http://127.0.0.1:8080'],
    ['http://[::1]:8080', 'http://[::1]:8080'],
  ])('normalizes the upstream base URL %s', (value, expected) => {
    vi.stubEnv('NULLPII_UPSTREAM', value);
    vi.stubEnv('NULLPII_OPENAI_UPSTREAM', value);
    const c = loadConfig();
    expect(c.upstreamBaseUrl).toBe(expected);
    expect(c.openaiUpstreamBaseUrl).toBe(expected);
  });

  describe.each(['NULLPII_UPSTREAM', 'NULLPII_OPENAI_UPSTREAM'])('%s', (name) => {
    it.each([
      ['not a URL', 'api.anthropic.com', /must be an http: or https: URL$/],
      ['another protocol', 'ftp://proxy.test', /got protocol: ftp:/],
      ['a trailing /v1', 'https://proxy.test/v1', /must not end with \/v1 \(the gateway appends/],
      ['a trailing /v1/', 'https://proxy.test/api/v1/', /must not end with \/v1/],
      [
        'plain http to another machine',
        'http://proxy.test',
        /must use https: unless it is on this machine/,
      ],
      ['plain http to a LAN address', 'http://192.168.1.20:11434', /must use https:/],
      ['plain http to localhost', 'http://localhost:11434', /must use https:/],
    ])('refuses %s', (_case, value, message) => {
      vi.stubEnv(name, value);
      expect(() => loadConfig()).toThrow(message);
      expect(() => loadConfig()).toThrow(new RegExp(`^${name} `));
    });

    it.each([
      ['credentials', 'https://user:s3cr3t-token@proxy.test', /must not embed credentials/],
      ['a query string', 'https://proxy.test/?key=s3cr3t-token', /without a query string/],
      ['a fragment', 'https://proxy.test/#s3cr3t-token', /without a query string or a fragment/],
    ])('refuses %s without echoing the value', (_case, value, message) => {
      vi.stubEnv(name, value);
      expect(() => loadConfig()).toThrow(message);
      let error = '';
      try {
        loadConfig();
      } catch (err) {
        error = (err as Error).message;
      }
      expect(error).not.toContain('s3cr3t-token');
    });
  });

  it('loads the shared policy file and its restoreTools', () => {
    const file = join(dir, 'policy.json');
    writeFileSync(
      file,
      JSON.stringify({ restoreTools: ['Bash'], disabledCategories: ['private_title'] }),
    );
    vi.stubEnv('NULLPII_CONFIG', file);
    const c = loadConfig();
    expect(c.policy).toEqual({ restoreTools: ['Bash'], disabledCategories: ['private_title'] });
    expect([...c.restoreTools]).toEqual(['Bash']);
    expect(c.policyFile).toBe(file);
    expect(c.policyLoaded).toBe(true);
  });
});
