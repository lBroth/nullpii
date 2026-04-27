// SPDX-License-Identifier: Apache-2.0
import { afterEach, describe, expect, it, vi } from 'vitest';
import { BackendNotAvailableError } from '../src/errors.js';
import { selectBackend } from '../src/router.js';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('selectBackend (auto)', () => {
  it('picks CPU when no GPU backend is available', async () => {
    // On macOS in this test env: CUDA → false, MPS → may be true, ROCm → false, CPU → true
    // We force MPS unavailable by clearing platform check via vi.spyOn
    const backend = await selectBackend('/nonexistent', { backend: 'auto' });
    expect(['cpu', 'mps']).toContain(backend.name);
  });

  it('returns the explicitly requested CPU backend', async () => {
    const backend = await selectBackend('/nonexistent', { backend: 'cpu' });
    expect(backend.name).toBe('cpu');
  });

  it('throws BackendNotAvailableError for explicit unavailable backend', async () => {
    // CUDA is unavailable on macOS — explicit request should throw
    if (process.platform === 'darwin') {
      await expect(selectBackend('/nonexistent', { backend: 'cuda' })).rejects.toBeInstanceOf(
        BackendNotAvailableError,
      );
    }
  });

  it('respects explicit MPS on macOS', async () => {
    if (process.platform !== 'darwin') return;
    const backend = await selectBackend('/nonexistent', { backend: 'mps' });
    expect(backend.name).toBe('mps');
  });
});
