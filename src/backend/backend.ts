// SPDX-License-Identifier: Apache-2.0

import { join } from 'node:path';
import type { InferenceSession, Tensor as TensorType } from 'onnxruntime-node';
import { MODEL_FILES } from '../defaults.js';
import { ModelNotFoundError, OrtNotInstalledError } from '../errors.js';
import { logf } from '../log.js';
import { fileExists } from '../paths.js';
import type { InferenceInputs, InferenceOutputs } from '../types/index.js';

const LOG_SCOPE = 'nullpii:backend';

/** Reused dim tuples — `text_lengths` is always a `[1, 1]` int64 scalar,
 * and `[1]` is the dim for the scalar's data buffer. ORT clones the dim
 * array on Tensor construction, so this is purely an allocation
 * micro-optimisation (no aliasing concerns). */
const DIMS_SCALAR_1_1: readonly number[] = [1, 1];

type ExecutionProvider = NonNullable<InferenceSession.SessionOptions['executionProviders']>[number];

const CPU_PROVIDER = 'cpu';

/** `code` of the process warning emitted when an accelerator fails to
 * load and the session runs on the CPU instead. */
export const BACKEND_FALLBACK_WARNING = 'NULLPII_BACKEND_FALLBACK';

export interface BackendOptions {
  /** ONNX files to load from the model directory, best first; the first
   * that exists is used (`onnxCandidates`). Default: `['model.onnx']`. */
  readonly onnxFiles?: readonly string[];
  /** ONNX files to load, best first, when the accelerator in
   * `executionProviders` fails to load and the session falls back to the
   * CPU. Default: `onnxFiles`. */
  readonly cpuFallbackOnnxFiles?: readonly string[];
  /** ORT execution providers, in priority order. Default: `['cpu']`. */
  readonly executionProviders?: ReadonlyArray<ExecutionProvider>;
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
 * Loads the first existing `onnxFiles` entry of `<modelDir>` (by default
 * `model.onnx`) lazily on first `infer()`. Every input
 * runs through one unified ONNX — no per-domain dispatch.
 * `onnxruntime-node` is an optional peer; imported dynamically so
 * recognizer-only / vault-only callers never trigger the load.
 *
 * Concurrency: `infer()` allocates fresh `text_lengths` + `span_mask`
 * tensors per call. Required for safety under
 * `Promise.all([np.sanitize(a), np.sanitize(b)])` — pooled scratch
 * would be clobbered by the second caller before ORT consumed the
 * first. Cost is one `BigInt64Array(1)` + `Uint8Array(N)` per inference.
 * The session itself loads once: concurrent first calls share one load. */
export class OrtBackend {
  private sessionLoad: Promise<InferenceSession> | null = null;
  private TensorCtor: typeof TensorType | null = null;

  constructor(
    private readonly modelDir: string,
    private readonly options: BackendOptions = {},
  ) {}

  /** One load per backend. A failed load is forgotten, so the next call
   * retries instead of replaying the error. */
  private ensureSession(): Promise<InferenceSession> {
    if (this.sessionLoad === null) {
      this.sessionLoad = this.loadSession().catch((err: unknown) => {
        this.sessionLoad = null;
        throw err;
      });
    }
    return this.sessionLoad;
  }

  /** Load the ONNX session now, as the first `infer()` would: a caller
   * that warms the model up before any request (a server) reports the
   * loading step while it runs. */
  async load(): Promise<void> {
    await this.ensureSession();
  }

  /** ORT fails the whole session when an execution provider's library
   * cannot be loaded (a missing CUDA or cuDNN library), so listing `cpu`
   * after it is no fallback. A failed accelerator load is retried on the
   * CPU alone, with a process warning naming the cause. */
  private async loadSession(): Promise<InferenceSession> {
    const files = this.options.onnxFiles ?? [MODEL_FILES.fp32];
    const onnxPath = await this.firstExistingOnnx(files);
    const ort = await (this.options.ortLoader ?? loadOrt)();
    this.TensorCtor = ort.Tensor;
    const providers = this.options.executionProviders ?? [CPU_PROVIDER];
    try {
      return await this.createSession(ort, onnxPath, providers);
    } catch (err) {
      const accelerators = providers.filter((p) => providerName(p) !== CPU_PROVIDER);
      if (accelerators.length === 0) throw err;
      const cpuPath = await this.firstExistingOnnx(this.options.cpuFallbackOnnxFiles ?? files);
      process.emitWarning(
        `nullpii: the ${accelerators.map(providerName).join('/')} execution provider failed to load, so the model runs on the CPU: ${errorMessage(err)}`,
        { code: BACKEND_FALLBACK_WARNING },
      );
      return this.createSession(ort, cpuPath, [CPU_PROVIDER]);
    }
  }

  private createSession(
    ort: typeof import('onnxruntime-node'),
    onnxPath: string,
    providers: ReadonlyArray<ExecutionProvider>,
  ): Promise<InferenceSession> {
    logf(LOG_SCOPE, 'session.load', { path: onnxPath, providers: providers.map(providerName) });
    const sessionOptions: InferenceSession.SessionOptions = {
      executionProviders: [...providers],
      graphOptimizationLevel: 'all',
    };
    if (this.options.intraOpNumThreads !== undefined && this.options.intraOpNumThreads > 0) {
      sessionOptions.intraOpNumThreads = this.options.intraOpNumThreads;
    }
    if (this.options.interOpNumThreads !== undefined && this.options.interOpNumThreads > 0) {
      sessionOptions.interOpNumThreads = this.options.interOpNumThreads;
    }
    return ort.InferenceSession.create(onnxPath, sessionOptions);
  }

  private async firstExistingOnnx(files: readonly string[]): Promise<string> {
    for (const f of files) {
      const path = join(this.modelDir, f);
      if (await fileExists(path)) return path;
    }
    throw new ModelNotFoundError(files.map((f) => join(this.modelDir, f)).join(' or '));
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
    const load = this.sessionLoad;
    if (load === null) return;
    this.sessionLoad = null;
    this.TensorCtor = null;
    // A load that failed has no session to release; its error already
    // reached the `infer()` call that started it.
    const session = await load.catch(() => null);
    if (session === null) return;
    logf(LOG_SCOPE, 'session.release');
    await session.release();
  }
}

function providerName(provider: ExecutionProvider): string {
  return typeof provider === 'string' ? provider : provider.name;
}

function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
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
