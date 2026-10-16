// SPDX-License-Identifier: Apache-2.0

import { describe, expect, it, vi } from 'vitest';
import { TextTooLongError } from '../src/errors.js';
import { NullPii } from '../src/nullpii.js';

// An encoder whose subword budget only fits KEEP words per window, as the
// real one behaves on dense text (logs of long hashes and tokens). Every
// word handed to the model is recorded so the test can check coverage.
const KEEP = 12;
const seenWords: string[] = [];

vi.mock('../src/backend/backend.js', () => {
  class OrtBackend {
    async infer(): Promise<{
      logits: Float32Array;
      textLength: number;
      maxWidth: number;
      numClasses: number;
    }> {
      return { logits: new Float32Array(0), textLength: 0, maxWidth: 1, numClasses: 12 };
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
    async encode(text: string) {
      const all = actual.splitWords(text);
      const words = all.slice(0, KEEP);
      for (const w of words) seenWords.push(w.text);
      return {
        inputIds: BigInt64Array.from([0n]),
        attentionMask: BigInt64Array.from([1n]),
        wordsMask: BigInt64Array.from([0n]),
        numWords: words.length,
        words,
        seqLen: 1,
        truncated: words.length < all.length,
      };
    }
  }
  return { ...actual, GlinerTokenizer };
});

describe('NullPii windowing on dense input', () => {
  it('hands every word to the model even when every window is cut', async () => {
    seenWords.length = 0;
    const words = Array.from({ length: 1000 }, (_, i) => `tok${i}`);
    const np = new NullPii({ modelDir: '/fake', backend: 'cpu', recognizers: 'none' });
    await np.sanitize(words.join(' '));
    expect(new Set(seenWords)).toEqual(new Set(words));
    await np.dispose();
  });

  it('strictLength still throws when a window is cut', async () => {
    const np = new NullPii({
      modelDir: '/fake',
      backend: 'cpu',
      recognizers: 'none',
      strictLength: true,
    });
    const text = Array.from({ length: 50 }, (_, i) => `tok${i}`).join(' ');
    await expect(np.sanitize(text)).rejects.toBeInstanceOf(TextTooLongError);
    await np.dispose();
  });
});
