// SPDX-License-Identifier: Apache-2.0

import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ModelNotFoundError } from '../src/errors.js';
import { ensureFile, fileUrl, isCachedFile, sha256File } from '../src/hf-hub.js';

const BODY = 'model bytes';
const SHA = createHash('sha256').update(BODY).digest('hex');

let dir = '';
let calls: string[] = [];
beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), 'nullpii-hf-'));
  calls = [];
});
afterEach(() => {
  vi.unstubAllGlobals();
  rmSync(dir, { recursive: true, force: true });
});

/** A fetch that answers each call with the next status (200 serves BODY). */
function serve(...statuses: number[]): void {
  vi.stubGlobal('fetch', async (url: string) => {
    calls.push(url);
    const status = statuses.shift() ?? 200;
    return new Response(status === 200 ? BODY : 'nope', { status });
  });
}

const OPTS = { timeoutMs: 5_000 };

describe('ensureFile', () => {
  it('downloads, writes a checksum sidecar, then serves the cache without a network call', async () => {
    serve(200);
    const dest = await ensureFile('org/name', 'abc123', 'model.onnx', dir, OPTS);
    expect(calls).toEqual([fileUrl('org/name', 'abc123', 'model.onnx')]);
    expect(readFileSync(dest, 'utf8')).toBe(BODY);
    expect(readFileSync(`${dest}.sha256`, 'utf8')).toContain(SHA);
    expect(await isCachedFile(dir, 'model.onnx', SHA)).toBe(true);
    await ensureFile('org/name', 'abc123', 'model.onnx', dir, { ...OPTS, expectedSha: SHA });
    expect(calls).toHaveLength(1);
  });

  it('retries a transient HTTP error', async () => {
    serve(503, 200);
    await ensureFile('org/name', 'main', 'tokenizer.json', dir, OPTS);
    expect(calls).toHaveLength(2);
  });

  it('does not retry a 404 and leaves no partial file', async () => {
    serve(404);
    await expect(ensureFile('org/name', 'main', 'missing.onnx', dir, OPTS)).rejects.toBeInstanceOf(
      ModelNotFoundError,
    );
    expect(calls).toHaveLength(1);
    expect(readdirSync(dir).filter((f) => f.includes('.partial'))).toEqual([]);
  });

  it('deletes a download whose hash is not the expected one', async () => {
    serve(200);
    await expect(
      ensureFile('org/name', 'main', 'model.onnx', dir, { ...OPTS, expectedSha: 'f'.repeat(64) }),
    ).rejects.toBeInstanceOf(ModelNotFoundError);
    expect(existsSync(join(dir, 'model.onnx'))).toBe(false);
  });

  it('downloads again when the cached file has another hash than expected', async () => {
    writeFileSync(join(dir, 'model.onnx'), 'old weights');
    writeFileSync(join(dir, 'model.onnx.sha256'), await sha256File(join(dir, 'model.onnx')));
    expect(await isCachedFile(dir, 'model.onnx')).toBe(true);
    expect(await isCachedFile(dir, 'model.onnx', SHA)).toBe(false);
    serve(200);
    await ensureFile('org/name', 'main', 'model.onnx', dir, { ...OPTS, expectedSha: SHA });
    expect(readFileSync(join(dir, 'model.onnx'), 'utf8')).toBe(BODY);
  });

  it('does not trust a cached file that no longer matches its sidecar', async () => {
    writeFileSync(join(dir, 'model.onnx'), 'tampered');
    writeFileSync(join(dir, 'model.onnx.sha256'), SHA);
    expect(await isCachedFile(dir, 'model.onnx')).toBe(false);
  });
});
