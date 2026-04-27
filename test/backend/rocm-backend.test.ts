// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { RocmBackend } from '../../src/backend/rocm-backend.js';

describe('RocmBackend', () => {
  it('reports name = "rocm"', () => {
    const b = new RocmBackend('/nonexistent');
    expect(b.name).toBe('rocm');
  });

  it('isAvailable() returns false on non-Linux', async () => {
    if (process.platform === 'linux') return;
    const b = new RocmBackend('/nonexistent');
    expect(await b.isAvailable()).toBe(false);
  });

  it('isAvailable() returns a boolean on Linux', async () => {
    if (process.platform !== 'linux') return;
    const b = new RocmBackend('/nonexistent');
    expect(typeof (await b.isAvailable())).toBe('boolean');
  });
});
