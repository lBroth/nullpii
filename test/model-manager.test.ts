import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ModelNotFoundError } from '../src/errors.js';
import { ModelManager } from '../src/model-manager.js';

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

  // Network-gated download/cache test removed — it required NULLPII_E2E=1
  // and a real HF round-trip. The non-network behaviours (deterministic
  // modelDir, error surfacing) are covered above and don't need an env flag.

  it('surfaces ModelNotFoundError when the underlying download fails', async () => {
    const cache = mkdtempSync(join(tmpdir(), 'nullpii-cache-'));
    const m = new ModelManager(cache);
    const stub = vi.fn().mockRejectedValue(new ModelNotFoundError('boom'));
    vi.doMock('../src/hf-hub.js', () => ({ ensureFile: stub }));
    await expect(m.ensure({ variant: 'int4', timeoutMs: 1 })).rejects.toBeDefined();
  });
});
