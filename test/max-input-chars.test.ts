// SPDX-License-Identifier: Apache-2.0
//
// Texts longer than `MAX_INPUT_CHARS`. `normalizeForDetection` and
// `runRecognizers` pass a text over the cap through untouched (F-06: the
// model would then run alone, with no signal), so `sanitize()` must never
// hand them one: it reads a longer text in overlapping windows within the
// cap (`segments.ts`) and masks it once. These tests run the recognizer
// pack for real, with a model that finds nothing.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PROMPT_LABEL_COUNT } from './helpers.js';

vi.mock('../src/backend/backend.js', () => {
  class OrtBackend {
    async infer(): Promise<{
      logits: Float32Array;
      textLength: number;
      maxWidth: number;
      numClasses: number;
    }> {
      return {
        logits: new Float32Array(0),
        textLength: 0,
        maxWidth: 1,
        numClasses: PROMPT_LABEL_COUNT,
      };
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
const { MAX_INPUT_CHARS } = await import('../src/defaults.js');

const EMAIL = 'mario.rossi@acme.io';
const PEM_HEAD = '-----BEGIN RSA PRIVATE KEY-----';
const PEM_FOOT = '-----END RSA PRIVATE KEY-----';
// A filler no recognizer matches and the window cut cannot move: no line
// break, no whitespace.
const SOLID = '|';
const PLACEHOLDER = /\{\{PII_[A-Z_]+_\d+_[^}]*\}\}/g;

let np: InstanceType<typeof NullPii>;

beforeEach(() => {
  np = new NullPii({ modelDir: '/fake', backend: 'cpu' });
});

afterEach(async () => {
  await np.dispose();
});

/** `value` placed at `at` inside `length` characters of `filler`. */
function withValueAt(length: number, at: number, value: string, filler = SOLID): string {
  return filler.repeat(at) + value + filler.repeat(length - at - value.length);
}

describe('texts longer than MAX_INPUT_CHARS', () => {
  it('masks a value far past the cap instead of refusing the text', async () => {
    const text = withValueAt(2 * MAX_INPUT_CHARS + 500, Math.floor(1.5 * MAX_INPUT_CHARS), EMAIL);
    const r = await np.sanitize(text);
    expect(r.sanitized).not.toContain(EMAIL);
    expect(r.spans.map((s) => s.label)).toEqual(['private_email']);
  });

  it('masks whole a value that the first window cuts in two', async () => {
    // No line break or whitespace: the first window ends exactly at the cap.
    const at = MAX_INPUT_CHARS - 6;
    const r = await np.sanitize(withValueAt(MAX_INPUT_CHARS + 50_000, at, EMAIL));
    expect(r.spans).toHaveLength(1);
    expect(r.spans[0]).toMatchObject({ start: at, end: at + EMAIL.length, label: 'private_email' });
    expect(r.sanitized).not.toContain('rossi');
  });

  it('masks whole a key block that a line-break cut falls inside', async () => {
    const body = Array.from({ length: 25 }, (_, i) => `${String.fromCharCode(65 + i)}`.repeat(64));
    const pem = [PEM_HEAD, ...body, PEM_FOOT].join('\n');
    const line = `${'z'.repeat(63)}\n`;
    const lines = Math.ceil((MAX_INPUT_CHARS + 100_000) / line.length);
    // The block straddles the cap; the first window ends after the last
    // line break before it, inside the block.
    const before = line.repeat(Math.floor((MAX_INPUT_CHARS - 900) / line.length));
    const text = `${before}${pem}\n${line.repeat(lines)}`;
    const cut = text.lastIndexOf('\n', MAX_INPUT_CHARS - 1) + 1;
    expect(cut).toBeGreaterThan(before.length);
    expect(cut).toBeLessThan(before.length + pem.length);
    const r = await np.sanitize(text);
    const key = r.spans.find((s) => s.label === 'secret');
    expect(key).toMatchObject({ start: before.length, end: before.length + pem.length });
    for (const row of body) expect(r.sanitized).not.toContain(row);
  });

  it('gives a value seen in two windows one placeholder', async () => {
    const text =
      SOLID.repeat(1_000) +
      EMAIL +
      SOLID.repeat(Math.floor(1.6 * MAX_INPUT_CHARS)) +
      EMAIL +
      SOLID.repeat(1_000);
    const r = await np.sanitize(text);
    const placeholders = r.sanitized.match(PLACEHOLDER) ?? [];
    expect(placeholders).toHaveLength(2);
    expect(placeholders[0]).toBe(placeholders[1]);
    expect(np.restore(r.sanitized, r.sessionId).restored).toBe(text);
  });

  it('reads a text of exactly MAX_INPUT_CHARS in one pass', async () => {
    const r = await np.sanitize(withValueAt(MAX_INPUT_CHARS, 10, EMAIL));
    expect(r.sanitized).not.toContain(EMAIL);
  });

  it('leaves small input as before', async () => {
    const r = await np.sanitize('Email me at a@acme.io.');
    expect(r.sanitized).not.toContain('a@acme.io');
  });
});
