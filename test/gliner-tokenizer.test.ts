// SPDX-License-Identifier: Apache-2.0
//
// GlinerTokenizer against tiny WordLevel tokenizers written to a temp
// dir, so the sequence-wrapper lookup is tested without a model download.

import { mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { GlinerTokenizer } from '../src/gliner-tokenizer.js';

const dirs: string[] = [];
afterEach(() => {
  for (const d of dirs.splice(0)) rmSync(d, { recursive: true, force: true });
});

function tokenizerDir(vocab: Record<string, number>): string {
  const dir = mkdtempSync(join(tmpdir(), 'nullpii-tok-'));
  dirs.push(dir);
  const special = ['<<ENT>>', '<<SEP>>', '[CLS]', '[SEP]', '<s>', '</s>'].filter((t) => t in vocab);
  writeFileSync(
    join(dir, 'tokenizer.json'),
    JSON.stringify({
      version: '1.0',
      truncation: null,
      padding: null,
      added_tokens: special.map((content) => ({
        id: vocab[content],
        content,
        single_word: false,
        lstrip: false,
        rstrip: false,
        normalized: false,
        special: true,
      })),
      normalizer: null,
      pre_tokenizer: { type: 'Whitespace' },
      post_processor: null,
      decoder: null,
      model: { type: 'WordLevel', vocab, unk_token: '[UNK]' },
    }),
  );
  return dir;
}

const WORDS = { '[UNK]': 0, '<<ENT>>': 1, '<<SEP>>': 2, person: 3, hello: 4, mario: 5 };

describe('GlinerTokenizer sequence wrappers', () => {
  it('uses [CLS] and [SEP] for a BERT / DeBERTa vocabulary', async () => {
    const dir = tokenizerDir({ ...WORDS, '[CLS]': 10, '[SEP]': 11 });
    const enc = await new GlinerTokenizer(dir).encode('hello mario', ['person']);
    expect(enc.inputIds[0]).toBe(10n);
    expect(enc.inputIds[enc.seqLen - 1]).toBe(11n);
  });

  it('uses <s> and </s> for a RoBERTa / XLM-R vocabulary', async () => {
    const dir = tokenizerDir({ ...WORDS, '<s>': 20, '</s>': 21 });
    const enc = await new GlinerTokenizer(dir).encode('hello mario', ['person']);
    expect(enc.inputIds[0]).toBe(20n);
    expect(enc.inputIds[enc.seqLen - 1]).toBe(21n);
    expect(enc.numWords).toBe(2);
  });

  it('fails loud when the vocabulary has neither convention', async () => {
    const dir = tokenizerDir(WORDS);
    await expect(new GlinerTokenizer(dir).encode('hello', ['person'])).rejects.toThrow(
      /missing special token id/,
    );
  });
});
