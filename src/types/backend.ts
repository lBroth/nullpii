import type { BackendName, ModelVariant } from './config.js';

/** Inputs the model expects per inference. Names match the ONNX graph. */
export interface InferenceInputs {
  readonly inputIds: BigInt64Array;
  readonly attentionMask: BigInt64Array;
}

/**
 * Output of one inference. `logits` is row-major `[seqLen × numLabels]`.
 * Backends MUST return the exact `seqLen` matching the input length.
 */
export interface InferenceOutputs {
  readonly logits: Float32Array;
  readonly seqLen: number;
  readonly numLabels: number;
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
