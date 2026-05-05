// SPDX-License-Identifier: Apache-2.0

import { join } from 'node:path';
import debug from 'debug';
import { type InferenceSession, InferenceSession as Session, Tensor } from 'onnxruntime-node';
import { ModelNotFoundError } from '../errors.js';
import { fileExists } from '../paths.js';
import type { InferenceInputs, InferenceOutputs } from '../types/index.js';

const log = debug('nullpii:multi-backend');

/** Multi-domain GLiNER ONNX backend.
 *
 * Holds one ORT session per adapter directory. Sessions are created
 * lazily on first call to `infer(inputs, domain)`, so a user that only
 * ever hits one route never pays for the others.
 *
 * Layout assumed under `<modelDir>/onnx-merged/<adapterDir>/model.onnx`,
 * one merged-LoRA ONNX per per-domain adapter (devops, legal,
 * medical, narrative, enterprise).
 */
export class MultiOrtBackend {
  private sessions = new Map<string, Session>();

  constructor(
    private readonly modelDir: string,
    private readonly executionProviders: ReadonlyArray<
      NonNullable<InferenceSession.SessionOptions['executionProviders']>[number]
    > = ['cpu'],
  ) {}

  private async sessionFor(domain: string): Promise<Session> {
    const cached = this.sessions.get(domain);
    if (cached !== undefined) return cached;

    const onnxPath = join(this.modelDir, 'onnx-merged', domain, 'model.onnx');
    if (!(await fileExists(onnxPath))) {
      throw new ModelNotFoundError(onnxPath);
    }
    log('loading adapter ONNX %s → session', onnxPath);
    const session = await Session.create(onnxPath, {
      executionProviders: [...this.executionProviders],
      graphOptimizationLevel: 'all',
    });
    this.sessions.set(domain, session);
    return session;
  }

  /** Run GLiNER inference using the per-domain merged-LoRA ONNX. */
  async infer(inputs: InferenceInputs, domain: string): Promise<InferenceOutputs> {
    const session = await this.sessionFor(domain);
    const seqLen = inputs.inputIds.length;
    const tDims: readonly number[] = [1, seqLen];
    const feeds: Record<string, Tensor> = {
      input_ids: new Tensor('int64', inputs.inputIds, tDims),
      attention_mask: new Tensor('int64', inputs.attentionMask, tDims),
      words_mask: new Tensor('int64', inputs.wordsMask, tDims),
      text_lengths: new Tensor('int64', BigInt64Array.from([BigInt(inputs.textLength)]), [1, 1]),
      span_idx: new Tensor('int64', inputs.spanIdx, [1, inputs.numSpans, 2]),
      span_mask: new Tensor('bool', toBoolArray(inputs.spanMask), [1, inputs.numSpans]),
    };
    const out = await session.run(feeds);
    const outName = session.outputNames[0];
    if (outName === undefined) throw new Error('multi-backend: model has no outputs');
    const tensor = out[outName];
    if (tensor === undefined) throw new Error(`multi-backend: missing tensor '${outName}'`);
    const flat =
      tensor.data instanceof Float32Array
        ? tensor.data
        : Float32Array.from(tensor.data as ArrayLike<number>);
    const dims = tensor.dims as readonly number[];
    let maxWidth = inputs.numSpans / Math.max(1, inputs.textLength);
    let numClasses = flat.length / Math.max(1, inputs.numSpans);
    if (dims.length === 4) {
      maxWidth = Number(dims[2] ?? maxWidth);
      numClasses = Number(dims[3] ?? numClasses);
    } else if (dims.length === 3) {
      maxWidth = Number(dims[1] ?? maxWidth);
      numClasses = Number(dims[2] ?? numClasses);
    }
    return { logits: flat, textLength: inputs.textLength, maxWidth, numClasses };
  }

  async dispose(): Promise<void> {
    for (const [dir, sess] of this.sessions) {
      log('releasing session %s', dir);
      await sess.release();
    }
    this.sessions.clear();
  }

  /** Domain dirs whose sessions are currently loaded (diagnostic). */
  loadedDomains(): readonly string[] {
    return Array.from(this.sessions.keys());
  }
}

function toBoolArray(src: BigInt64Array): Uint8Array {
  const out = new Uint8Array(src.length);
  for (let i = 0; i < src.length; i++) {
    out[i] = src[i] === 1n ? 1 : 0;
  }
  return out;
}
