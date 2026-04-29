// SPDX-License-Identifier: Apache-2.0
import { existsSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { MpsBackend } from '../../src/backend/mps-backend.js';

const ARTIFACT_MODEL_DIR = resolve(
  process.env.NULLPII_TEST_MODEL_DIR ??
    new URL('../.nullpii-test-artifacts/model', import.meta.url).pathname,
);
const HAS_ARTIFACTS = existsSync(join(ARTIFACT_MODEL_DIR, 'onnx', 'model_fp16.onnx'));
const IS_DARWIN = process.platform === 'darwin';
const itIfMacWithArtifacts = IS_DARWIN && HAS_ARTIFACTS ? it : it.skip;

describe('MpsBackend', () => {
  it('reports name = "mps"', () => {
    const b = new MpsBackend('/nonexistent');
    expect(b.name).toBe('mps');
  });

  it('isAvailable() reflects platform', async () => {
    const b = new MpsBackend('/nonexistent');
    const expected = process.platform === 'darwin';
    expect(await b.isAvailable()).toBe(expected);
  });
});

describe('MpsBackend integration (gated on macOS + artifacts)', () => {
  itIfMacWithArtifacts(
    'init → infer → dispose round-trip on fp16 variant via CoreML',
    async () => {
      const b = new MpsBackend(ARTIFACT_MODEL_DIR, 'fp16');
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
    180_000,
  );
});
