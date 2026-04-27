// SPDX-License-Identifier: Apache-2.0
import { join } from 'node:path';
import { Tokenizer } from '@anush008/tokenizers';
import debug from 'debug';
import { TOKENIZER_FILE } from './defaults.js';
import { ModelNotFoundError } from './errors.js';
import { fileExists } from './paths.js';
import { MAX_SEQUENCE_LENGTH } from './types/index.js';

const log = debug('nullpii:tokenizer');

/** Result of `encode(text)`. Arrays are aligned: `inputIds[i]` corresponds
 * to `attentionMask[i]` and `offsetMapping[i]` (a `[start, end]` char range). */
export interface EncodeResult {
  readonly inputIds: BigInt64Array;
  readonly attentionMask: BigInt64Array;
  readonly offsetMapping: ReadonlyArray<readonly [number, number]>;
}

/**
 * Tokenizer wrapper around the upstream `tokenizers` Rust bindings.
 *
 * - Lazy-loads `tokenizer.json` on first call (never in the constructor).
 * - Encodes text into `inputIds` / `attentionMask` (BigInt64 for ORT) plus
 *   character-level `offsetMapping` used for span reconstruction.
 * - Truncates silently to `maxSequenceLength` tokens with a debug warning.
 * - All diagnostics go through `debug('nullpii:tokenizer')`.
 */
export class TokenizerWrapper {
  private impl: Tokenizer | null = null;

  constructor(
    private readonly modelDir: string,
    private readonly maxSequenceLength: number = MAX_SEQUENCE_LENGTH,
  ) {}

  private async load(): Promise<Tokenizer> {
    if (this.impl !== null) return this.impl;
    const path = join(this.modelDir, TOKENIZER_FILE);
    if (!(await fileExists(path))) {
      throw new ModelNotFoundError(path);
    }
    log('loading %s (max_length=%d)', path, this.maxSequenceLength);
    const t = Tokenizer.fromFile(path);
    t.setTruncation(this.maxSequenceLength);
    this.impl = t;
    return t;
  }

  /** Tokenize `text`, returning aligned `inputIds`, `attentionMask`, and
   * `offsetMapping`. Inputs longer than `maxSequenceLength` are truncated. */
  async encode(text: string): Promise<EncodeResult> {
    const tok = await this.load();
    const enc = await tok.encode(text);
    const ids = enc.getIds();
    if (ids.length >= this.maxSequenceLength) {
      log('input truncated to %d tokens', this.maxSequenceLength);
    }
    const mask = enc.getAttentionMask();
    const offsets = enc.getOffsets();
    return {
      inputIds: BigInt64Array.from(ids, (n) => BigInt(n)),
      attentionMask: BigInt64Array.from(mask, (n) => BigInt(n)),
      offsetMapping: offsets.map((pair) => [pair[0] ?? 0, pair[1] ?? 0] as const),
    };
  }

  /** Reconstruct text from a sequence of token ids. Skips special tokens. */
  async decode(inputIds: BigInt64Array | readonly number[]): Promise<string> {
    const tok = await this.load();
    const ids = Array.isArray(inputIds)
      ? (inputIds as readonly number[]).slice()
      : Array.from(inputIds as BigInt64Array, (n) => Number(n));
    return tok.decode(ids, true);
  }
}
