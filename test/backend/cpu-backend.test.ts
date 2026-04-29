// SPDX-License-Identifier: Apache-2.0
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { CpuBackend } from '../../src/backend/cpu-backend.js';
import { ModelNotFoundError, ModelNotInitializedError } from '../../src/errors.js';
import { HAS_TEST_ARTIFACTS, TEST_MODEL_DIR } from '../_env.js';

const ARTIFACT_MODEL_DIR = TEST_MODEL_DIR;
const itIfArtifacts = HAS_TEST_ARTIFACTS ? it : it.skip;

describe('CpuBackend lifecycle', () => {
  it('reports name = "cpu" and is always available', async () => {
    const b = new CpuBackend('/nonexistent');
    expect(b.name).toBe('cpu');
    expect(await b.isAvailable()).toBe(true);
  });

  it('infer() before init() throws ModelNotInitializedError', async () => {
    const b = new CpuBackend('/nonexistent');
    await expect(
      b.infer({
        inputIds: BigInt64Array.from([1n]),
        attentionMask: BigInt64Array.from([1n]),
      }),
    ).rejects.toBeInstanceOf(ModelNotInitializedError);
  });

  it('init() throws ModelNotFoundError when ONNX file is missing', async () => {
    const empty = mkdtempSync(join(tmpdir(), 'nullpii-cpu-'));
    const b = new CpuBackend(empty);
    await expect(b.init()).rejects.toBeInstanceOf(ModelNotFoundError);
  });

  it('dispose() before init() is a no-op', async () => {
    const b = new CpuBackend('/nonexistent');
    await expect(b.dispose()).resolves.toBeUndefined();
  });
});

describe('CpuBackend integration (gated on artifacts/model)', () => {
  itIfArtifacts(
    'init → infer → dispose round-trip on int4 variant',
    async () => {
      const b = new CpuBackend(ARTIFACT_MODEL_DIR, 'int4');
      await b.init();
      const seqLen = 8;
      const result = await b.infer({
        inputIds: BigInt64Array.from(new Array(seqLen).fill(1n)),
        attentionMask: BigInt64Array.from(new Array(seqLen).fill(1n)),
      });
      expect(result.seqLen).toBe(seqLen);
      expect(result.numLabels).toBe(33);
      expect(result.logits.length).toBe(seqLen * 33);
      await b.dispose();
    },
    120_000,
  );

  itIfArtifacts(
    'infer() throws after dispose()',
    async () => {
      const b = new CpuBackend(ARTIFACT_MODEL_DIR, 'int4');
      await b.init();
      await b.dispose();
      await expect(
        b.infer({
          inputIds: BigInt64Array.from([1n]),
          attentionMask: BigInt64Array.from([1n]),
        }),
      ).rejects.toBeInstanceOf(ModelNotInitializedError);
    },
    120_000,
  );
});
