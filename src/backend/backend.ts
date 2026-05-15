// SPDX-License-Identifier: Apache-2.0

import { join } from 'node:path';
import type { InferenceSession, Tensor as TensorType } from 'onnxruntime-node';
import { ModelNotFoundError, OrtNotInstalledError } from '../errors.js';
import { logf } from '../log.js';
import { fileExists } from '../paths.js';
import type { InferenceInputs, InferenceOutputs } from '../types/index.js';

const LOG_SCOPE = 'nullpii:backend';

const ONNX_FILE = 'model.onnx';

/** Reused dim tuples — `text_lengths` is always a `[1, 1]` int64 scalar,
 * and `[1]` is the dim for the scalar's data buffer. ORT clones the dim
 * array on Tensor construction, so this is purely an allocation
 * micro-optimisation (no aliasing concerns). */
const DIMS_SCALAR_1_1: readonly number[] = [1, 1];

export interface BackendOptions {
  /** ORT execution providers, in priority order. Default: `['cpu']`. */
  readonly executionProviders?: ReadonlyArray<
    NonNullable<InferenceSession.SessionOptions['executionProviders']>[number]
  >;
  /** ORT intra-op thread count. `0` (default) = ORT picks based on host. */
  readonly intraOpNumThreads?: number;
  /** ORT inter-op thread count. `0` (default) = ORT picks based on host. */
  readonly interOpNumThreads?: number;
  /** Override the runtime ORT loader. Test-only — production code leaves
   * this undefined and `loadOrt()` dynamically imports `onnxruntime-node`. */
  readonly ortLoader?: () => Promise<typeof import('onnxruntime-node')>;
}

/** GLiNER ONNX backend.
 *
 * Loads `<modelDir>/model.onnx` lazily on first `infer()`. The unified
 * model replaces the v0.1 5-shard + cosine router stack; there is no
 * per-domain dispatch — every input runs through the same ONNX.
 *
 * `onnxruntime-node` is an optional peer dependency. The runtime is
 * imported dynamically on the first inference call so users who only
 * touch the recognizer pack / vault APIs never trigger the load.
 *
 * Concurrency. `infer()` allocates fresh `text_lengths` and `span_mask`
 * tensors per call so two concurrent callers on the same backend instance
 * never share scratch storage. A previous version pooled these buffers
 * and assumed "the await on session.run() never interleaves with another
 * infer call" — that's true only for strictly sequential use; under
 * `await Promise.all([np.sanitize(a), np.sanitize(b)])` the pool's first
 * write was clobbered by the second caller before ORT consumed it. Per-
 * call allocation costs one trivial `BigInt64Array(1)` + `Uint8Array(N)`
 * per inference; not worth the correctness risk to elide.
 */
export class OrtBackend {
  private session: InferenceSession | null = null;
  private TensorCtor: typeof TensorType | null = null;

  constructor(
    private readonly modelDir: string,
    private readonly options: BackendOptions = {},
  ) {}

  private async ensureSession(): Promise<InferenceSession> {
    if (this.session !== null) return this.session;
    const onnxPath = join(this.modelDir, ONNX_FILE);
    if (!(await fileExists(onnxPath))) {
      throw new ModelNotFoundError(onnxPath);
    }
    const ort = await (this.options.ortLoader ?? loadOrt)();
    this.TensorCtor = ort.Tensor;
    logf(LOG_SCOPE, 'session.load', { path: onnxPath });
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
    // Per-call allocation — see class-level concurrency note. Cost is a
    // single tiny typed-array per inference; eliminates any possibility of
    // cross-call buffer clobber even under Promise.all() on a shared
    // backend.
    const textLengthsBuf = new BigInt64Array([BigInt(inputs.textLength)]);
    const boolBuf = new Uint8Array(inputs.spanMask.length);
    fillBoolBuf(boolBuf, inputs.spanMask);
    const feeds: Record<string, TensorType> = {
      input_ids: new Tensor('int64', inputs.inputIds, tDims),
      attention_mask: new Tensor('int64', inputs.attentionMask, tDims),
      words_mask: new Tensor('int64', inputs.wordsMask, tDims),
      text_lengths: new Tensor('int64', textLengthsBuf, DIMS_SCALAR_1_1),
      span_idx: new Tensor('int64', inputs.spanIdx, [1, inputs.numSpans, 2]),
      span_mask: new Tensor('bool', boolBuf, [1, inputs.numSpans]),
    };
    const out = await session.run(feeds);
    const outName = session.outputNames[0];
    if (outName === undefined) throw new Error('backend: model has no outputs');
    const tensor = out[outName];
    if (tensor === undefined) throw new Error(`backend: missing tensor '${outName}'`);
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
      logf(LOG_SCOPE, 'session.release');
      await this.session.release();
      this.session = null;
      this.TensorCtor = null;
    }
  }
}

async function loadOrt(): Promise<typeof import('onnxruntime-node')> {
  try {
    return await import('onnxruntime-node');
  } catch (err) {
    // Preserve the underlying loader error (binding mismatch, missing
    // native build, glibc version, etc.) via `cause` so callers can
    // diagnose without re-running the dynamic import themselves.
    throw new OrtNotInstalledError({ cause: err });
  }
}

function fillBoolBuf(dst: Uint8Array, src: BigInt64Array): void {
  for (let i = 0; i < src.length; i++) {
    dst[i] = src[i] === 1n ? 1 : 0;
  }
}
