// SPDX-License-Identifier: Apache-2.0

import { mkdtempSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { OrtBackend } from '../src/backend/backend.js';
import { ModelNotFoundError } from '../src/errors.js';
import { ModelManager } from '../src/model-manager.js';
import { onnxCandidates } from '../src/model-variant.js';
import type { ModelVariant } from '../src/types/index.js';

// Each test sets how the stubbed download treats each file name.
const hub = vi.hoisted(() => ({ fail: new Map<string, Error>(), fetched: [] as string[] }));

vi.mock('../src/hf-hub.js', async () => {
  const actual = await vi.importActual<typeof import('../src/hf-hub.js')>('../src/hf-hub.js');
  return {
    ...actual,
    ensureFile: async (_repo: string, _rev: string, file: string, dir: string): Promise<string> => {
      const err = hub.fail.get(file);
      if (err !== undefined) throw err;
      hub.fetched.push(file);
      return join(dir, file);
    },
  };
});

const notFound = (file: string) =>
  new ModelNotFoundError(`https://huggingface.co/x/${file} (HTTP 404)`);

afterEach(() => {
  hub.fail.clear();
  hub.fetched.length = 0;
});

describe('onnxCandidates', () => {
  it('asks for fp16 then fp32 on CUDA under auto', () => {
    expect(onnxCandidates('auto', 'cuda')).toEqual(['model_fp16.onnx', 'model.onnx']);
  });

  it('keeps fp32 on every other backend under auto', () => {
    for (const backend of ['cpu', 'mps', 'auto'] as const) {
      expect(onnxCandidates('auto', backend)).toEqual(['model.onnx']);
    }
  });

  it('gives an explicit precision no fallback', () => {
    expect(onnxCandidates('fp16', 'cpu')).toEqual(['model_fp16.onnx']);
    expect(onnxCandidates('fp32', 'cuda')).toEqual(['model.onnx']);
  });

  it('refuses an unknown variant', () => {
    expect(() => onnxCandidates('int4' as unknown as ModelVariant, 'cpu')).toThrow(TypeError);
  });
});

describe('ModelManager.ensure picks the ONNX file', () => {
  const manager = () => new ModelManager(mkdtempSync(join(tmpdir(), 'nullpii-cache-')));

  it('fetches fp16 on CUDA when the revision has it', async () => {
    const out = await manager().ensure({ backend: 'cuda', timeoutMs: 1 });
    expect(out.onnxFile).toBe('model_fp16.onnx');
    expect(hub.fetched).not.toContain('model.onnx');
  });

  it('falls back to fp32 when the revision has no fp16 file', async () => {
    hub.fail.set('model_fp16.onnx', notFound('model_fp16.onnx'));
    const out = await manager().ensure({ backend: 'cuda', timeoutMs: 1 });
    expect(out.onnxFile).toBe('model.onnx');
  });

  it('does not fall back on a failure other than a missing file', async () => {
    hub.fail.set('model_fp16.onnx', new ModelNotFoundError('https://huggingface.co/x (HTTP 503)'));
    await expect(manager().ensure({ backend: 'cuda', timeoutMs: 1 })).rejects.toThrow(/HTTP 503/);
    expect(hub.fetched).not.toContain('model.onnx');
  });

  it('fails when an explicit fp16 is missing', async () => {
    hub.fail.set('model_fp16.onnx', notFound('model_fp16.onnx'));
    await expect(
      manager().ensure({ variant: 'fp16', backend: 'cuda', timeoutMs: 1 }),
    ).rejects.toThrow(ModelNotFoundError);
  });

  it('fetches only fp32 on the CPU', async () => {
    const out = await manager().ensure({ timeoutMs: 1 });
    expect(out.onnxFile).toBe('model.onnx');
    expect(hub.fetched).not.toContain('model_fp16.onnx');
  });
});

describe('OrtBackend loads the first ONNX file present', () => {
  const created: string[] = [];
  const stubOrt = {
    Tensor: class {
      constructor(
        public readonly type: string,
        public readonly data: unknown,
        public readonly dims: readonly number[],
      ) {}
    },
    InferenceSession: {
      async create(path: string) {
        created.push(path);
        return {
          outputNames: ['logits'],
          run: async () => ({ logits: { data: new Float32Array(1), dims: [1, 1, 1, 1] } }),
          release: async () => {},
        };
      },
    },
  } as unknown as typeof import('onnxruntime-node');
  const inputs = {
    inputIds: BigInt64Array.from([0n]),
    attentionMask: BigInt64Array.from([1n]),
    wordsMask: BigInt64Array.from([0n]),
    textLength: 1,
    spanIdx: BigInt64Array.from([0n, 0n]),
    spanMask: BigInt64Array.from([1n]),
    numSpans: 1,
  };
  const dirWith = (...files: string[]) => {
    const dir = mkdtempSync(join(tmpdir(), 'nullpii-model-'));
    for (const f of files) writeFileSync(join(dir, f), '');
    return dir;
  };

  afterEach(() => {
    created.length = 0;
  });

  it('prefers fp16 when both files are there', async () => {
    const dir = dirWith('model.onnx', 'model_fp16.onnx');
    const b = new OrtBackend(dir, {
      onnxFiles: ['model_fp16.onnx', 'model.onnx'],
      ortLoader: async () => stubOrt,
    });
    await b.infer(inputs);
    expect(created).toEqual([join(dir, 'model_fp16.onnx')]);
  });

  it('uses fp32 when the directory has no fp16 file', async () => {
    const dir = dirWith('model.onnx');
    const b = new OrtBackend(dir, {
      onnxFiles: ['model_fp16.onnx', 'model.onnx'],
      ortLoader: async () => stubOrt,
    });
    await b.infer(inputs);
    expect(created).toEqual([join(dir, 'model.onnx')]);
  });

  it('reports the preferred file when none is present', async () => {
    const dir = dirWith();
    const b = new OrtBackend(dir, {
      onnxFiles: ['model_fp16.onnx'],
      ortLoader: async () => stubOrt,
    });
    await expect(b.infer(inputs)).rejects.toThrow(join(dir, 'model_fp16.onnx'));
  });
});
