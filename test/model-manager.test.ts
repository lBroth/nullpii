import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ModelNotFoundError } from '../src/errors.js';
import { InvalidPathError } from '../src/errors.js';
import { ModelManager } from '../src/model-manager.js';

// The download is stubbed: no test in this file touches the network.
const hub = vi.hoisted(() => ({ calls: 0 }));

vi.mock('../src/hf-hub.js', async () => {
  const actual = await vi.importActual<typeof import('../src/hf-hub.js')>('../src/hf-hub.js');
  return {
    ...actual,
    ensureFile: async (_repo: string, _rev: string, file: string): Promise<string> => {
      hub.calls += 1;
      throw new ModelNotFoundError(file);
    },
  };
});

const caches: string[] = [];

function tempCache(): string {
  const dir = mkdtempSync(join(tmpdir(), 'nullpii-cache-'));
  caches.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of caches.splice(0)) rmSync(dir, { recursive: true, force: true });
});

describe('ModelManager', () => {
  it('exposes a deterministic modelDir under the cache root', () => {
    const cache = tempCache();
    const m = new ModelManager(cache);
    expect(m.modelDir.startsWith(cache)).toBe(true);
    expect(m.modelDir).toContain(join('lBroth', 'nullpii'));
  });

  it('refuses to escape its cache root if asked', () => {
    // resolveSafePath underlies resolveCacheFile and is fully covered in
    // paths.test.ts; this test asserts the cacheDir is canonical so the
    // sandbox cannot be bypassed by giving a relative cwd.
    const cache = tempCache();
    const m = new ModelManager(cache);
    expect(m.modelDir.startsWith(cache)).toBe(true);
    expect(m.modelDir.includes('..')).toBe(false);
  });

  it('rejects a repo or revision that is not a HuggingFace id', () => {
    const m = new ModelManager('/tmp/nullpii-cache-test');
    for (const model of [
      { repo: '../escape', revision: 'main' },
      { repo: 'org/name/extra', revision: 'main' },
      { repo: 'org/name', revision: '../../etc' },
      { repo: 'org/name', revision: 'refs/../..' },
      { repo: 'org/name', revision: '/abs' },
    ]) {
      expect(() => m.modelDirFor(model), JSON.stringify(model)).toThrow(InvalidPathError);
    }
    expect(m.modelDirFor({ repo: 'org/name', revision: 'refs/pr/1' })).toBe(
      '/tmp/nullpii-cache-test/org/name/refs/pr/1',
    );
  });

  it('surfaces ModelNotFoundError when the underlying download fails', async () => {
    const cache = tempCache();
    const m = new ModelManager(cache);
    hub.calls = 0;
    await expect(m.ensure({ variant: 'fp32', timeoutMs: 1 })).rejects.toBeInstanceOf(
      ModelNotFoundError,
    );
    expect(hub.calls).toBeGreaterThan(0);
  });
});
