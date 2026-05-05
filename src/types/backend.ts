import type { BackendName, ModelVariant } from './config.js';

/** Inputs the GLiNER ONNX graph expects per inference (6-input span model
 * — `UniEncoderSpanORTModel`). Names match the ONNX graph. Tensor shapes
 * (batch dim 1 prepended at backend call site):
 *
 *   - `inputIds` / `attentionMask` / `wordsMask` : `[seqLen]` int64
 *   - `textLengths` : `[1]` int64 (numWords as a scalar batch entry)
 *   - `spanIdx` : `[numSpans, 2]` int64 (flat — caller stores as
 *     `[start0, end0, start1, end1, ...]` length `2 * numSpans`)
 *   - `spanMask` : `[numSpans]` int64 (0/1)
 */
export interface InferenceInputs {
  readonly inputIds: BigInt64Array;
  readonly attentionMask: BigInt64Array;
  readonly wordsMask: BigInt64Array;
  readonly textLength: number;
  readonly spanIdx: BigInt64Array;
  readonly spanMask: BigInt64Array;
  readonly numSpans: number;
}

/**
 * Output of one GLiNER inference. `logits` is row-major flattened from
 * `[textLength, maxWidth, numClasses]` — the (i, j, k) entry is at
 * index `i * maxWidth * numClasses + j * numClasses + k`. Caller
 * applies sigmoid + threshold filter to extract spans.
 */
export interface InferenceOutputs {
  readonly logits: Float32Array;
  readonly textLength: number;
  readonly maxWidth: number;
  readonly numClasses: number;
}

/**
 * Contract every backend implementation must satisfy.
 * Backends are stateful: callers create one, `init()` it, run `infer()`
 * many times, then `dispose()` to release native resources.
 */
export interface BackendProvider {
  /** Stable identifier (e.g. `'cpu'`, `'cuda'`). */
  readonly name: BackendName;
  /** Variant of the ONNX model the backend was constructed with. */
  readonly variant: ModelVariant;
  /** Best-effort check; cheap, may be called before `init()`. */
  isAvailable(): Promise<boolean>;
  /** Load the model into memory. Idempotent: calling twice is a no-op. */
  init(): Promise<void>;
  /** Run a single forward pass. Throws if `init()` has not completed. */
  infer(inputs: InferenceInputs): Promise<InferenceOutputs>;
  /** Release native resources. After this call, the instance is unusable. */
  dispose(): Promise<void>;
}
