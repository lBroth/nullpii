// SPDX-License-Identifier: Apache-2.0

import { join } from 'node:path';
import { Tokenizer } from '@anush008/tokenizers';
import debug from 'debug';
import { TOKENIZER_FILE } from './defaults.js';
import { ModelNotFoundError } from './errors.js';
import { fileExists } from './paths.js';

const log = debug('nullpii:gliner-tokenizer');

/** GLiNER special tokens (from `gliner_config.json`). */
export const ENT_TOKEN = '<<ENT>>';
export const SEP_TOKEN = '<<SEP>>';

/** From `gliner_config.json`: max_width=12, max_len=384. */
export const DEFAULT_MAX_SPAN_WIDTH = 12;
export const DEFAULT_MAX_SEQUENCE_LENGTH = 384;

/** Defence-in-depth word cap; chunker is the primary bound. */
export const MAX_TEXT_WORDS = 500;

/** Word splitter — `\w+(?:[-_]\w+)*|\S` matches word blobs +
 * single non-whitespace symbols (port of upstream GLiNER's regex). */
export interface Word {
  readonly text: string;
  readonly charStart: number;
  readonly charEnd: number;
}

const WORD_SPLITTER_RE = /\w+(?:[-_]\w+)*|\S/gu;

export function splitWords(text: string): Word[] {
  const out: Word[] = [];
  for (const m of text.matchAll(WORD_SPLITTER_RE)) {
    const start = m.index ?? 0;
    out.push({ text: m[0], charStart: start, charEnd: start + m[0].length });
  }
  return out;
}

/** Result of `GlinerTokenizer.encode()`. All `BigInt64Array` outputs are
 * shape `[seqLen]` (batch dim = 1, prepended at ORT call site). The
 * accompanying `words` + `numWords` describe the TEXT word boundaries —
 * needed by the span decoder to map (start_word, end_word) pairs back to
 * character offsets in the original input. */
export interface GlinerEncodeResult {
  readonly inputIds: BigInt64Array;
  readonly attentionMask: BigInt64Array;
  readonly wordsMask: BigInt64Array;
  readonly seqLen: number;
  readonly words: readonly Word[];
  readonly numWords: number;
  /** Number of "prompt" input tokens before the actual text words.
   * Equals `2 * labels.length + 1` (each label has its `<<ENT>>` token,
   * plus the final `<<SEP>>`). Used for `words_mask` `seen_words` skip. */
  readonly promptLength: number;
  /** True if the encoder hit the configured `maxSequenceLength` and
   * truncated subwords. Caller may want to chunk the input or warn. */
  readonly truncated: boolean;
}

/**
 * GLiNER multi-PII tokenizer wrapper.
 *
 * Wraps the upstream HF SentencePiece tokenizer (loaded via
 * `@anush008/tokenizers` from `tokenizer.json` shipped with the model).
 * Adds the GLiNER-specific prompt-formatting and `words_mask` computation
 * on top.
 *
 * Lifecycle:
 *   1. Constructor stores `modelDir` only — does not touch disk.
 *   2. First `encode()` call lazy-loads `tokenizer.json` via
 *      `Tokenizer.fromFile()` and registers the two special tokens
 *      (`<<ENT>>` / `<<SEP>>`) so they survive normalization.
 *   3. Subsequent calls reuse the loaded instance.
 *
 * The 6-input ONNX contract derived from this encode result:
 *   - `input_ids`, `attention_mask`, `words_mask` come back here.
 *   - `text_lengths` = `result.numWords`.
 *   - `span_idx` / `span_mask` are built downstream in `gliner-spans.ts`.
 */
export class GlinerTokenizer {
  private impl: Tokenizer | null = null;

  constructor(
    private readonly modelDir: string,
    private readonly maxSequenceLength: number = DEFAULT_MAX_SEQUENCE_LENGTH,
  ) {}

  private async load(): Promise<Tokenizer> {
    if (this.impl !== null) return this.impl;
    const path = join(this.modelDir, TOKENIZER_FILE);
    if (!(await fileExists(path))) {
      throw new ModelNotFoundError(path);
    }
    log('loading %s (max_len=%d)', path, this.maxSequenceLength);
    const t = Tokenizer.fromFile(path);
    // GLiNER ships `<<ENT>>` and `<<SEP>>` as added tokens in
    // `tokenizer.json` already, but registering them again is a no-op
    // and protects us against repos that strip the added_tokens block.
    t.addSpecialTokens([ENT_TOKEN, SEP_TOKEN]);
    t.setTruncation(this.maxSequenceLength);
    this.impl = t;
    return t;
  }

  /** Encode `text` for a given label set. The label list determines
   * the prompt prefix and the model's output `num_classes` dimension —
   * caller must pass the same array to the span decoder.
   *
   * Implementation: the underlying `@anush008/tokenizers` napi binding
   * doesn't honor `isPretokenized: true` for arrays (rejects with
   * `StringExpected`). Workaround: encode each prompt token + each
   * text word separately with `addSpecialTokens: false`, concatenate
   * the ids, and track our own word index. CLS/SEP wrappers are added
   * manually using ids resolved via `tok.tokenToId()`.
   */
  async encode(text: string, labels: readonly string[]): Promise<GlinerEncodeResult> {
    const tok = await this.load();

    const words = splitWords(text);

    // Resolve special tokens by name. CLS / SEP names are mDeBERTa-v3
    // conventions ([CLS] / [SEP]); ENT/SEP_TOKEN are GLiNER additions.
    // If any of these is missing the encoder is unusable — fail loud.
    const clsId = tok.tokenToId('[CLS]');
    const sepId = tok.tokenToId('[SEP]');
    const entId = tok.tokenToId(ENT_TOKEN);
    const sepGlinerId = tok.tokenToId(SEP_TOKEN);
    if (clsId === null || sepId === null || entId === null || sepGlinerId === null) {
      throw new Error(
        `gliner-tokenizer: missing special token id (CLS=${clsId}, SEP=${sepId}, ENT=${entId}, GLINER_SEP=${sepGlinerId})`,
      );
    }

    const ids: number[] = [];
    const wordsMaskArr: number[] = [];

    // [CLS] at start.
    ids.push(clsId);
    wordsMaskArr.push(0);

    // Prompt: each label gets <<ENT>> + (sub-tokens of label name).
    // All prompt subwords map to words_mask = 0.
    for (const lab of labels) {
      ids.push(entId);
      wordsMaskArr.push(0);
      const labEnc = await tok.encode(lab, null, { addSpecialTokens: false });
      for (const subId of labEnc.getIds()) {
        ids.push(subId);
        wordsMaskArr.push(0);
      }
    }
    ids.push(sepGlinerId);
    wordsMaskArr.push(0);

    // Text words: each word's first subword gets words_mask = wordIdx+1
    // (1-indexed). Continuation subwords get 0.
    let truncatedSubwords = false;
    let truncatedByWordCap = false;
    const limit = this.maxSequenceLength - 1; // reserve 1 slot for trailing [SEP]
    let truncatedWordCount = 0;
    const wordCap = Math.min(words.length, MAX_TEXT_WORDS);
    for (let wi = 0; wi < wordCap; wi++) {
      if (ids.length >= limit) {
        truncatedSubwords = true;
        break;
      }
      const w = words[wi];
      if (w === undefined) continue;
      const wordEnc = await tok.encode(w.text, null, { addSpecialTokens: false });
      const subIds = wordEnc.getIds();
      // Snapshot lengths so we can roll back this word's partial subwords
      // if the limit is hit mid-word. Otherwise `words_mask` keeps a
      // `wi+1` value for a word that `numTextWords` does not count,
      // which then writes out of range in the GLiNER head's ScatterND.
      const idsBefore = ids.length;
      const wmBefore = wordsMaskArr.length;
      let first = true;
      let hitLimit = false;
      for (const subId of subIds) {
        if (ids.length >= limit) {
          hitLimit = true;
          break;
        }
        ids.push(subId);
        wordsMaskArr.push(first ? wi + 1 : 0);
        first = false;
      }
      if (hitLimit) {
        // Roll back partial subwords for this word.
        ids.length = idsBefore;
        wordsMaskArr.length = wmBefore;
        truncatedSubwords = true;
        break;
      }
      truncatedWordCount = wi + 1;
    }
    if (truncatedWordCount === MAX_TEXT_WORDS && words.length > MAX_TEXT_WORDS) {
      truncatedByWordCap = true;
    }
    const numTextWords =
      truncatedSubwords || truncatedByWordCap ? truncatedWordCount : words.length;

    // [SEP] at end.
    ids.push(sepId);
    wordsMaskArr.push(0);

    const seqLen = ids.length;
    if (truncatedSubwords || truncatedByWordCap) {
      log(
        'input truncated to %d/%d words (subword cap %d hit=%s, word cap %d hit=%s)',
        numTextWords,
        words.length,
        this.maxSequenceLength,
        truncatedSubwords,
        MAX_TEXT_WORDS,
        truncatedByWordCap,
      );
    }

    const promptLength = 2 * labels.length + 1; // ENT-per-label + final SEP-token
    const truncatedWords = words.slice(0, numTextWords);

    return {
      inputIds: BigInt64Array.from(ids, (n) => BigInt(n)),
      attentionMask: new BigInt64Array(seqLen).fill(1n),
      wordsMask: BigInt64Array.from(wordsMaskArr, (n) => BigInt(n)),
      seqLen,
      words: truncatedWords,
      numWords: numTextWords,
      promptLength,
      truncated: truncatedSubwords,
    };
  }
}
