// SPDX-License-Identifier: Apache-2.0

import { join } from 'node:path';
import { Tokenizer } from '@anush008/tokenizers';
import debug from 'debug';
import { type InferenceSession, InferenceSession as Session, Tensor } from 'onnxruntime-node';
import { ModelNotFoundError } from './errors.js';
import { fileExists } from './paths.js';

const log = debug('nullpii:distiluse-encoder');

/** distiluse-base-multilingual-cased-v2 encoder, ONNX-backed.
 *
 * Loads `distiluse.onnx` + `distiluse-tokenizer.json` from a model dir.
 * Encodes text → 512-dim sentence embedding via mean pooling over the
 * last hidden state, with attention mask weighting and L2 normalisation.
 *
 * Mirrors `sentence-transformers/distiluse-base-multilingual-cased-v2`
 * inference path (DistilBERT encoder → mean pool → optional dense
 * projection — DistilBERT-multi v2 is mean-pool only, no extra dense).
 */
export class DistiluseEncoder {
  private session: Session | null = null;
  private tokenizer: Tokenizer | null = null;

  constructor(
    private readonly modelDir: string,
    private readonly maxSequenceLength: number = 128,
  ) {}

  /** Embedding dimension. */
  get dim(): number {
    return 512;
  }

  private async loadTokenizer(): Promise<Tokenizer> {
    if (this.tokenizer !== null) return this.tokenizer;
    const path = join(this.modelDir, 'distiluse-tokenizer.json');
    if (!(await fileExists(path))) {
      throw new ModelNotFoundError(path);
    }
    log('loading tokenizer %s', path);
    const t = Tokenizer.fromFile(path);
    t.setTruncation(this.maxSequenceLength);
    this.tokenizer = t;
    return t;
  }

  async init(): Promise<void> {
    if (this.session !== null) return;
    const onnxPath = join(this.modelDir, 'distiluse.onnx');
    if (!(await fileExists(onnxPath))) {
      throw new ModelNotFoundError(onnxPath);
    }
    log('loading ONNX %s', onnxPath);
    const opts: InferenceSession.SessionOptions = {
      executionProviders: ['cpu'],
      graphOptimizationLevel: 'all',
    };
    this.session = await Session.create(onnxPath, opts);
    await this.loadTokenizer();
  }

  /** Encode `text` into a 512-dim L2-normalised embedding. */
  async encode(text: string): Promise<Float32Array> {
    if (this.session === null) {
      throw new Error('DistiluseEncoder.encode: not initialised, call init() first');
    }
    const tok = await this.loadTokenizer();
    const enc = await tok.encode(text);
    const ids = enc.getIds();
    const mask = enc.getAttentionMask();
    const seqLen = ids.length;
    const dims: readonly number[] = [1, seqLen];
    const feeds: Record<string, Tensor> = {
      input_ids: new Tensor(
        'int64',
        BigInt64Array.from(ids, (n) => BigInt(n)),
        dims,
      ),
      attention_mask: new Tensor(
        'int64',
        BigInt64Array.from(mask, (n) => BigInt(n)),
        dims,
      ),
    };
    const out = await this.session.run(feeds);
    // The exported ONNX includes the full sentence-transformers pipeline:
    // transformer → mean-pool (mask-weighted) → Dense (768→512) → Tanh →
    // L2-normalise. Output: `sentence_embedding` of shape `[batch, 512]`.
    const tensor = out.sentence_embedding;
    if (tensor === undefined) {
      throw new Error('distiluse: missing `sentence_embedding` output tensor');
    }
    const flat =
      tensor.data instanceof Float32Array
        ? tensor.data
        : Float32Array.from(tensor.data as ArrayLike<number>);
    if (flat.length !== this.dim) {
      throw new Error(`distiluse: expected ${this.dim}-dim embedding, got ${flat.length}`);
    }
    return flat;
  }

  async dispose(): Promise<void> {
    if (this.session !== null) {
      await this.session.release();
      this.session = null;
    }
    this.tokenizer = null;
  }
}
