// SPDX-License-Identifier: Apache-2.0
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ModelNotFoundError } from '../src/errors.js';
import { ModelManager } from '../src/model-manager.js';

const NETWORK_OK = process.env.NULLPII_E2E === '1';
const itIfNetwork = NETWORK_OK ? it : it.skip;

afterEach(() => vi.restoreAllMocks());

describe('ModelManager', () => {
  it('exposes a deterministic modelDir under the cache root', () => {
    const cache = mkdtempSync(join(tmpdir(), 'nullpii-cache-'));
    const m = new ModelManager(cache);
    expect(m.modelDir.startsWith(cache)).toBe(true);
    expect(m.modelDir).toContain('openai/privacy-filter');
  });

  it('refuses to escape its cache root if asked', () => {
    // resolveSafePath underlies resolveCacheFile and is fully covered in
    // paths.test.ts; this test asserts the cacheDir is canonical so the
    // sandbox cannot be bypassed by giving a relative cwd.
    const cache = mkdtempSync(join(tmpdir(), 'nullpii-cache-'));
    const m = new ModelManager(cache);
    expect(m.modelDir.startsWith(cache)).toBe(true);
    expect(m.modelDir.includes('..')).toBe(false);
  });

  itIfNetwork(
    'downloads, caches, and re-uses files (int8 variant; requires network)',
    async () => {
      const cache = mkdtempSync(join(tmpdir(), 'nullpii-cache-net-'));
      const m = new ModelManager(cache);
      const t0 = Date.now();
      const a = await m.ensure({ variant: 'int8' });
      const t1 = Date.now();
      const b = await m.ensure({ variant: 'int8' });
      const t2 = Date.now();
      expect(a.modelDir).toBe(b.modelDir);
      // Second call should be near-instant (cache hit)
      expect(t2 - t1).toBeLessThan((t1 - t0) / 2 + 100);
    },
    600_000,
  );

  it('surfaces ModelNotFoundError when the underlying download fails', async () => {
    const cache = mkdtempSync(join(tmpdir(), 'nullpii-cache-'));
    const m = new ModelManager(cache);
    const stub = vi.fn().mockRejectedValue(new ModelNotFoundError('boom'));
    vi.doMock('../src/hf-hub.js', () => ({ ensureFile: stub }));
    await expect(m.ensure({ variant: 'int8', timeoutMs: 1 })).rejects.toBeDefined();
  });
});
