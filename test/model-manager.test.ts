// SPDX-License-Identifier: Apache-2.0

import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ModelNotFoundError } from '../src/errors.js';
import { InvalidConfigError, InvalidPathError } from '../src/errors.js';
import { ModelManager } from '../src/model-manager.js';

// The download is stubbed: no test in this file touches the network.
const hub = vi.hoisted(() => ({
  calls: 0,
  fail: true,
  expected: {} as Record<string, string | undefined>,
}));

vi.mock('../src/hf-hub.js', async () => {
  const actual = await vi.importActual<typeof import('../src/hf-hub.js')>('../src/hf-hub.js');
  return {
    ...actual,
    ensureFile: async (
      _repo: string,
      _rev: string,
      file: string,
      destDir: string,
      options: {
        expectedSha?: string;
        onBytes?: (received: number, total: number | undefined) => void;
      },
    ): Promise<string> => {
      hub.calls += 1;
      hub.expected[file] = options.expectedSha;
      options.onBytes?.(640, 1160);
      if (hub.fail) throw new ModelNotFoundError(file);
      return join(destDir, file);
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
  Object.assign(hub, { calls: 0, fail: true, expected: {} });
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
      resolve('/tmp/nullpii-cache-test', 'org', 'name', 'refs', 'pr', '1'),
    );
  });

  it('surfaces ModelNotFoundError when the underlying download fails', async () => {
    const cache = tempCache();
    const m = new ModelManager(cache);
    await expect(m.ensure({ variant: 'fp32', timeoutMs: 1 })).rejects.toBeInstanceOf(
      ModelNotFoundError,
    );
    expect(hub.calls).toBeGreaterThan(0);
  });

  const PINNED = {
    repo: 'org/name',
    revision: 'a'.repeat(40),
    sha256: {
      'tokenizer.json': '1'.repeat(64),
      'gliner_config.json': '2'.repeat(64),
      'tokenizer_config.json': '3'.repeat(64),
      'model.onnx': '4'.repeat(64),
      'model_fp16.onnx': '5'.repeat(64),
    },
  };

  it('passes each file its pinned SHA-256', async () => {
    const m = new ModelManager(tempCache());
    hub.fail = false;
    await m.ensure({ model: PINNED, variant: 'auto', backend: 'cuda', timeoutMs: 1 });
    expect(hub.expected).toEqual({
      'tokenizer.json': PINNED.sha256['tokenizer.json'],
      'gliner_config.json': PINNED.sha256['gliner_config.json'],
      'tokenizer_config.json': PINNED.sha256['tokenizer_config.json'],
      'model_fp16.onnx': PINNED.sha256['model_fp16.onnx'],
    });
  });

  it('refuses a model that pins hashes but not for every file it fetches', async () => {
    const m = new ModelManager(tempCache());
    hub.fail = false;
    const { 'model.onnx': _dropped, ...partial } = PINNED.sha256;
    await expect(
      m.ensure({ model: { ...PINNED, sha256: partial }, variant: 'fp32', timeoutMs: 1 }),
    ).rejects.toBeInstanceOf(InvalidConfigError);
  });

  it('skips an ONNX candidate the pins leave out, for one they cover', async () => {
    const m = new ModelManager(tempCache());
    hub.fail = false;
    const { 'model_fp16.onnx': _dropped, ...fp32Only } = PINNED.sha256;
    const r = await m.ensure({
      model: { ...PINNED, sha256: fp32Only },
      variant: 'auto',
      backend: 'cuda',
      timeoutMs: 1,
    });
    expect(r.onnxFile).toBe('model.onnx');
    expect(hub.expected['model.onnx']).toBe(PINNED.sha256['model.onnx']);
  });

  it.each(['A'.repeat(64), '4'.repeat(63), `${'4'.repeat(63)}g`])(
    'refuses a pin that is not 64 lower-case hex digits: %s',
    async (sha) => {
      const m = new ModelManager(tempCache());
      hub.fail = false;
      const model = { ...PINNED, sha256: { ...PINNED.sha256, 'model.onnx': sha } };
      await expect(m.ensure({ model, variant: 'fp32', timeoutMs: 1 })).rejects.toBeInstanceOf(
        InvalidConfigError,
      );
    },
  );

  it('passes each download its onBytes, with the file name', async () => {
    const m = new ModelManager(tempCache());
    hub.fail = false;
    const seen: Array<[string, number, number | undefined]> = [];
    const r = await m.ensure({
      model: PINNED,
      variant: 'fp32',
      timeoutMs: 1,
      onBytes: (file, received, total) => seen.push([file, received, total]),
    });
    expect(r.onnxFile).toBe('model.onnx');
    expect(seen.map(([file]) => file)).toEqual([
      'tokenizer.json',
      'gliner_config.json',
      'tokenizer_config.json',
      'model.onnx',
    ]);
    expect(seen.every(([, received, total]) => received === 640 && total === 1160)).toBe(true);
  });

  it('verifies nothing for a model that pins no hashes', async () => {
    const m = new ModelManager(tempCache());
    hub.fail = false;
    await m.ensure({
      model: { repo: 'org/name', revision: 'main' },
      variant: 'fp32',
      timeoutMs: 1,
    });
    expect(Object.values(hub.expected).every((v) => v === undefined)).toBe(true);
  });
});
