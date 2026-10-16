// SPDX-License-Identifier: Apache-2.0

import * as fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { type WordWindow, chunkText, forEachWindow } from '../src/chunking.js';
import { splitWords } from '../src/gliner-tokenizer.js';

const MAX_WORDS = 20;
const OVERLAP = 5;

function textOf(wordCount: number): string {
  return Array.from({ length: wordCount }, (_, i) => `w${i}`).join(' ');
}

/** Global word indices a window covers, given how many of its words were kept. */
function keptIndices(text: string, window: WordWindow, kept: number): number[] {
  const all = splitWords(text);
  const first = all.findIndex(
    (w) => w.charStart === window.offset + (splitWords(window.text)[0]?.charStart ?? 0),
  );
  return Array.from({ length: kept }, (_, i) => first + i);
}

describe('forEachWindow', () => {
  it('reproduces chunkText exactly when no window is cut', async () => {
    await fc.assert(
      fc.asyncProperty(fc.integer({ min: 0, max: 200 }), async (n) => {
        const text = textOf(n);
        const seen: Array<{ text: string; offset: number }> = [];
        await forEachWindow(
          text,
          async (w) => {
            seen.push({ text: w.text, offset: w.offset });
            return w.wordCount;
          },
          MAX_WORDS,
          OVERLAP,
        );
        expect(seen).toEqual(chunkText(text, MAX_WORDS, OVERLAP));
      }),
      { numRuns: 100 },
    );
  });

  it('every word is kept by some window when windows are cut arbitrarily', async () => {
    await fc.assert(
      fc.asyncProperty(
        fc.integer({ min: 1, max: 200 }),
        fc.array(fc.integer({ min: 1, max: MAX_WORDS }), { minLength: 1, maxLength: 50 }),
        async (n, cuts) => {
          const text = textOf(n);
          const covered = new Set<number>();
          let call = 0;
          const walk = await forEachWindow(
            text,
            async (w) => {
              const kept = Math.min(w.wordCount, cuts[call++ % cuts.length] ?? w.wordCount);
              for (const i of keptIndices(text, w, kept)) covered.add(i);
              return kept;
            },
            MAX_WORDS,
            OVERLAP,
          );
          expect(walk.unscannedWords).toBe(0);
          expect(covered.size).toBe(n);
        },
      ),
      { numRuns: 200 },
    );
  });

  it('counts a word the encoder cannot fit and moves past it', async () => {
    const text = textOf(50);
    const walk = await forEachWindow(
      text,
      async (w) => (w.offset === 0 ? 0 : w.wordCount),
      MAX_WORDS,
      OVERLAP,
    );
    expect(walk.unscannedWords).toBe(1);
  });

  it('rejects overlap >= max words', async () => {
    await expect(forEachWindow('a b c', async () => 0, 5, 5)).rejects.toThrow(RangeError);
  });
});
