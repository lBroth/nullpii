// SPDX-License-Identifier: Apache-2.0
//
// ORT fails the whole session when an execution provider's shared library
// cannot be loaded, so `['cuda', 'cpu']` never reached the CPU (#52).
// `OrtBackend` retries a failed accelerator load on the CPU alone, with a
// process warning, and loads the precision the CPU fallback asks for.

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BACKEND_FALLBACK_WARNING, OrtBackend } from '../src/backend/backend.js';

interface CreateCall {
  readonly path: string;
  readonly providers: readonly unknown[];
}

const CUDA_LOAD_ERROR =
  'OrtSessionOptionsAppendExecutionProvider_Cuda: Failed to load shared library';

function stubOrt(calls: CreateCall[], failCpu = false) {
  return async () =>
    ({
      Tensor: class {},
      InferenceSession: {
        async create(path: string, options: { executionProviders: readonly unknown[] }) {
          calls.push({ path, providers: options.executionProviders });
          if (options.executionProviders.includes('cuda')) throw new Error(CUDA_LOAD_ERROR);
          if (failCpu) throw new Error('cpu load failed');
          return { outputNames: [], release: async () => {} };
        },
      },
    }) as unknown as typeof import('onnxruntime-node');
}

describe('OrtBackend accelerator fallback', () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), 'nullpii-fallback-'));
    writeFileSync(join(dir, 'model.onnx'), '');
    writeFileSync(join(dir, 'model_fp16.onnx'), '');
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
    vi.restoreAllMocks();
  });

  it('retries on the CPU alone, with the CPU file, and warns', async () => {
    const calls: CreateCall[] = [];
    const warn = vi.spyOn(process, 'emitWarning').mockImplementation(() => {});
    const backend = new OrtBackend(dir, {
      onnxFiles: ['model_fp16.onnx', 'model.onnx'],
      cpuFallbackOnnxFiles: ['model.onnx'],
      executionProviders: ['cuda', 'cpu'],
      ortLoader: stubOrt(calls),
    });
    await expect(backend.infer({} as never)).rejects.toThrow();
    expect(calls).toEqual([
      { path: join(dir, 'model_fp16.onnx'), providers: ['cuda', 'cpu'] },
      { path: join(dir, 'model.onnx'), providers: ['cpu'] },
    ]);
    expect(warn).toHaveBeenCalledOnce();
    const [message, options] = warn.mock.calls[0] ?? [];
    expect(String(message)).toContain(CUDA_LOAD_ERROR);
    expect(options).toEqual({ code: BACKEND_FALLBACK_WARNING });
  });

  it('throws the CPU error, not a fallback, when the CPU itself fails', async () => {
    const calls: CreateCall[] = [];
    const backend = new OrtBackend(dir, {
      executionProviders: ['cpu'],
      ortLoader: stubOrt(calls, true),
    });
    await expect(backend.infer({} as never)).rejects.toThrow('cpu load failed');
    expect(calls).toHaveLength(1);
  });
});
