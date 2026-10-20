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
    ['NULLPII_BACKEND', 'gpu'],
    ['NULLPII_LOG_LEVEL', 'loud'],
    ['NULLPII_OPENAI_UPSTREAM', 'https://api.openai.com/v1'],
    ['NULLPII_SIDECAR_TOKEN', 'short'],
  ])('rejects %s=%s', (name, value) => {
    vi.stubEnv(name, value);
    expect(() => loadConfig()).toThrow();
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
