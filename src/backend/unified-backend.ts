// SPDX-License-Identifier: Apache-2.0

import { join } from 'node:path';
import debug from 'debug';
import type { InferenceSession, Tensor as TensorType } from 'onnxruntime-node';
import { ModelNotFoundError, OrtNotInstalledError } from '../errors.js';
import { fileExists } from '../paths.js';
import type { InferenceInputs, InferenceOutputs } from '../types/index.js';

const log = debug('nullpii:unified-backend');

const UNIFIED_ONNX_FILE = 'model.onnx';

/** Reused dim tuples — `text_lengths` is always a `[1, 1]` int64 scalar,
 * and `[1]` is the dim for the scalar's data buffer. ORT clones the dim
 * array on Tensor construction, so this is purely an allocation
 * micro-optimisation (no aliasing concerns). */
const DIMS_SCALAR_1_1: readonly number[] = [1, 1];

export interface UnifiedBackendOptions {
  /** ORT execution providers, in priority order. Default: `['cpu']`. */
  readonly executionProviders?: ReadonlyArray<
    NonNullable<InferenceSession.SessionOptions['executionProviders']>[number]
  >;
  /** ORT intra-op thread count. `0` (default) = ORT picks based on host. */
  readonly intraOpNumThreads?: number;
  /** ORT inter-op thread count. `0` (default) = ORT picks based on host. */
  readonly interOpNumThreads?: number;
}

/** Single-ONNX GLiNER backend.
 *
 * Loads `<modelDir>/model.onnx` lazily on first `infer()`. The unified
 * model replaces the v0.1 5-shard + cosine router stack; there is no
 * per-domain dispatch — every input runs through the same ONNX.
 *
 * `onnxruntime-node` is an optional peer dependency. The runtime is
 * imported dynamically on the first inference call so users who only
 * touch the recognizer pack / vault APIs never trigger the load.
 */
export class OrtUnifiedBackend {
  private session: InferenceSession | null = null;
  private TensorCtor: typeof TensorType | null = null;
  /** Reusable scratch buffer for the `text_lengths` scalar tensor.
   *
   * The buffer is rented to ORT for the duration of `session.run()`;
   * we never mutate it from a parallel call because `infer()` runs the
   * full feed → run → consume cycle synchronously between awaits, and
   * ORT clones the data on the native side. Pooling here saves one
   * `BigInt64Array.from` allocation per inference (cheap individually,
   * but `sanitize()` issues one per chunk on long inputs). */
  private readonly textLengthsBuf = new BigInt64Array(1);
  /** Reusable scratch buffer for `span_mask`. Resized lazily — ORT
   * receives a typed-array view and copies. */
  private boolBuf: Uint8Array = new Uint8Array(0);

  constructor(
    private readonly modelDir: string,
    private readonly options: UnifiedBackendOptions = {},
  ) {}

  private async ensureSession(): Promise<InferenceSession> {
    if (this.session !== null) return this.session;
    const onnxPath = join(this.modelDir, UNIFIED_ONNX_FILE);
    if (!(await fileExists(onnxPath))) {
      throw new ModelNotFoundError(onnxPath);
    }
    const ort = await loadOrt();
    this.TensorCtor = ort.Tensor;
    log('loading GLiNER ONNX %s → session', onnxPath);
    const sessionOptions: InferenceSession.SessionOptions = {
      executionProviders: [...(this.options.executionProviders ?? ['cpu'])],
      graphOptimizationLevel: 'all',
    };
    if (this.options.intraOpNumThreads !== undefined && this.options.intraOpNumThreads > 0) {
      sessionOptions.intraOpNumThreads = this.options.intraOpNumThreads;
    }
    if (this.options.interOpNumThreads !== undefined && this.options.interOpNumThreads > 0) {
      sessionOptions.interOpNumThreads = this.options.interOpNumThreads;
    }
    this.session = await ort.InferenceSession.create(onnxPath, sessionOptions);
    return this.session;
  }

  /** Run GLiNER inference against the unified ONNX. */
  async infer(inputs: InferenceInputs): Promise<InferenceOutputs> {
    const session = await this.ensureSession();
    const Tensor = this.TensorCtor;
    if (Tensor === null) throw new OrtNotInstalledError();
    const seqLen = inputs.inputIds.length;
    const tDims: readonly number[] = [1, seqLen];
    this.textLengthsBuf[0] = BigInt(inputs.textLength);
    const boolBuf = this.ensureBoolBuf(inputs.spanMask.length);
    fillBoolBuf(boolBuf, inputs.spanMask);
    const feeds: Record<string, TensorType> = {
      input_ids: new Tensor('int64', inputs.inputIds, tDims),
      attention_mask: new Tensor('int64', inputs.attentionMask, tDims),
      words_mask: new Tensor('int64', inputs.wordsMask, tDims),
      text_lengths: new Tensor('int64', this.textLengthsBuf, DIMS_SCALAR_1_1),
      span_idx: new Tensor('int64', inputs.spanIdx, [1, inputs.numSpans, 2]),
      span_mask: new Tensor('bool', boolBuf, [1, inputs.numSpans]),
    };
    const out = await session.run(feeds);
    const outName = session.outputNames[0];
    if (outName === undefined) throw new Error('unified-backend: model has no outputs');
    const tensor = out[outName];
    if (tensor === undefined) throw new Error(`unified-backend: missing tensor '${outName}'`);
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
    if (this.session !== null) {
      log('releasing session');
      await this.session.release();
      this.session = null;
      this.TensorCtor = null;
    }
  }

  /** Grow `boolBuf` if needed; never shrinks. Returns a buffer of
   * exactly `len` bytes (sliced view when the underlying buffer is
   * larger so ORT receives the right element count). */
  private ensureBoolBuf(len: number): Uint8Array {
    if (this.boolBuf.length < len) {
      this.boolBuf = new Uint8Array(len);
    }
    return this.boolBuf.length === len ? this.boolBuf : this.boolBuf.subarray(0, len);
  }
}

async function loadOrt(): Promise<typeof import('onnxruntime-node')> {
  try {
    return await import('onnxruntime-node');
  } catch (_err) {
    throw new OrtNotInstalledError();
  }
}

function fillBoolBuf(dst: Uint8Array, src: BigInt64Array): void {
  for (let i = 0; i < src.length; i++) {
    dst[i] = src[i] === 1n ? 1 : 0;
  }
}
