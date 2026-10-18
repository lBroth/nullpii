// SPDX-License-Identifier: Apache-2.0

import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DecodedSpan } from '../src/gliner-decoder.js';
import { NullPii } from '../src/nullpii.js';

// A span the score thresholds drop must not first silence, absorb or
// outrank another span. The decoder is stubbed so each test controls
// exactly what the model proposes.
const model = vi.hoisted(() => ({ spans: [] as DecodedSpan[] }));

vi.mock('../src/backend/backend.js', () => {
  class OrtBackend {
    async infer(): Promise<{
      logits: Float32Array;
      textLength: number;
      maxWidth: number;
      numClasses: number;
    }> {
      return { logits: new Float32Array(0), textLength: 0, maxWidth: 1, numClasses: 0 };
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
    async encode(text: string): Promise<{
      inputIds: BigInt64Array;
      attentionMask: BigInt64Array;
      wordsMask: BigInt64Array;
      numWords: number;
      words: ReturnType<typeof actual.splitWords>;
      seqLen: number;
      truncated: boolean;
    }> {
      const words = actual.splitWords(text);
      return {
        inputIds: BigInt64Array.from([0n]),
        attentionMask: BigInt64Array.from([1n]),
        wordsMask: BigInt64Array.from([0n]),
        numWords: words.length,
        words,
        seqLen: 1,
        truncated: false,
      };
    }
  }
  return { ...actual, GlinerTokenizer };
});

vi.mock('../src/gliner-decoder.js', () => ({
  decodeGlinerLogits: (): DecodedSpan[] => model.spans,
}));

const MAC = '3c:22:fb:7a:10:4e';
const at = (text: string, value: string, label: string, score: number): DecodedSpan => {
  const start = text.indexOf(value);
  return { label, start, end: start + value.length, score };
};

describe('score thresholds run before dedupe and recognizer deferral', () => {
  afterEach(() => {
    model.spans = [];
  });

  it('a sub-threshold model span over a MAC does not silence core:mac', async () => {
    const text = `device ${MAC} joined`;
    // 0.06 clears the decode threshold (0.05) but not the date one (0.125).
    model.spans = [at(text, MAC, 'private_date', 0.06)];
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const out = await n.sanitize(text);
    expect(out.spans.map((s) => [s.label, s.text])).toEqual([['private_mac', MAC]]);
    expect(out.sanitized).not.toContain(MAC);
    await n.dispose();
  });

  it('a sub-threshold model span does not absorb a contained span', async () => {
    const text = 'owner Mario Rossi since May';
    model.spans = [
      at(text, 'Mario Rossi since May', 'private_date', 0.06),
      at(text, 'Mario Rossi', 'private_person', 0.9),
    ];
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const out = await n.sanitize(text);
    expect(out.spans.map((s) => [s.label, s.text])).toEqual([['private_person', 'Mario Rossi']]);
    await n.dispose();
  });

  it('a model span that clears its threshold still takes priority over core:mac', async () => {
    const text = `device ${MAC} joined`;
    model.spans = [at(text, MAC, 'private_date', 0.5)];
    const n = new NullPii({ modelDir: '/fake', backend: 'cpu' });
    const out = await n.sanitize(text);
    expect(out.spans.map((s) => [s.label, s.text])).toEqual([['private_date', MAC]]);
    await n.dispose();
  });
});
