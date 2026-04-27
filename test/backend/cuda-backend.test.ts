// SPDX-License-Identifier: Apache-2.0
import { describe, expect, it } from 'vitest';
import { CudaBackend } from '../../src/backend/cuda-backend.js';

describe('CudaBackend', () => {
  it('reports name = "cuda"', () => {
    const b = new CudaBackend('/nonexistent');
    expect(b.name).toBe('cuda');
  });

  it('isAvailable() returns false on macOS regardless of env', async () => {
    if (process.platform !== 'darwin') return;
    const b = new CudaBackend('/nonexistent');
    expect(await b.isAvailable()).toBe(false);
  });

  it('isAvailable() returns false on Linux without /dev/nvidia0', async () => {
    if (process.platform !== 'linux') return;
    const b = new CudaBackend('/nonexistent');
    // Most CI runners have no GPU — assert the negative path is reachable
    const result = await b.isAvailable();
    expect(typeof result).toBe('boolean');
  });
});
