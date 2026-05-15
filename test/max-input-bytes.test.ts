// SPDX-License-Identifier: Apache-2.0
//
// F-06 regression test. README states inputs over 1 MB are "refused
// upfront", but `normalizeForDetection` + `runRecognizers` silently
// return passthrough / empty when `text.length > MAX_INPUT_BYTES`.
// Result: ML runs alone, regex pack + adversarial-normalize disabled,
// no error, no signal — silent recall collapse.
//
// `NullPii.sanitize()` must throw `TextTooLongError` upfront so callers
// learn to chunk and the README claim becomes accurate.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../src/backend/backend.js', () => {
  class OrtBackend {
    async infer(): Promise<{
      logits: Float32Array;
      textLength: number;
      maxWidth: number;
      numClasses: number;
    }> {
      return { logits: new Float32Array(0), textLength: 0, maxWidth: 1, numClasses: 8 };
    }
    async dispose(): Promise<void> {}
  }
  return { OrtBackend };
});

vi.mock('../src/gliner-tokenizer.js', async () => {
  const actual = await vi.importActual<typeof import('../src/gliner-tokenizer.js')>(
    '../src/gliner-tokenizer.js',
  );
  class GlinerTokenizer {
    async encode(): Promise<{
      inputIds: BigInt64Array;
      attentionMask: BigInt64Array;
      wordsMask: BigInt64Array;
      numWords: number;
      words: readonly string[];
      seqLen: number;
      truncated: boolean;
    }> {
      return {
        inputIds: BigInt64Array.from([0n]),
        attentionMask: BigInt64Array.from([1n]),
        wordsMask: BigInt64Array.from([0n]),
        numWords: 0,
        words: [],
        seqLen: 1,
        truncated: false,
      };
    }
  }
  return { ...actual, GlinerTokenizer };
});

const { NullPii } = await import('../src/nullpii.js');
const { TextTooLongError } = await import('../src/errors.js');
const { MAX_INPUT_BYTES } = await import('../src/defaults.js');

let np: InstanceType<typeof NullPii>;

beforeEach(() => {
  np = new NullPii({ modelDir: '/fake', backend: 'cpu' });
});

afterEach(async () => {
  await np.dispose();
});

describe('F-06 · MAX_INPUT_BYTES refuses oversized input', () => {
  it('throws TextTooLongError when text.length > MAX_INPUT_BYTES', async () => {
    const huge = 'a'.repeat(MAX_INPUT_BYTES + 1);
    await expect(np.sanitize(huge)).rejects.toBeInstanceOf(TextTooLongError);
  });

  it('error message carries observed length and limit', async () => {
    const huge = 'a'.repeat(MAX_INPUT_BYTES + 1);
    try {
      await np.sanitize(huge);
      throw new Error('expected throw');
    } catch (err) {
      expect(err).toBeInstanceOf(TextTooLongError);
      const msg = (err as Error).message;
      expect(msg).toContain(String(MAX_INPUT_BYTES + 1));
      expect(msg).toContain(String(MAX_INPUT_BYTES));
    }
  });

  it('accepts input at exactly MAX_INPUT_BYTES', async () => {
    const ok = 'a'.repeat(MAX_INPUT_BYTES);
    await expect(np.sanitize(ok)).resolves.toBeTruthy();
  });

  it('accepts small input unchanged', async () => {
    const r = await np.sanitize('Email me at a@acme.io.');
    expect(r.sanitized.length).toBeGreaterThan(0);
  });
});
