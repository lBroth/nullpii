import { join } from 'node:path';
import { type InferenceSession, InferenceSession as Session, Tensor } from 'onnxruntime-node';
import { ONNX_SUBDIR } from '../defaults.js';
import { ModelNotFoundError, ModelNotInitializedError } from '../errors.js';
import { fileExists } from '../paths.js';
import type {
  BackendName,
  BackendProvider,
  InferenceInputs,
  InferenceOutputs,
  ModelVariant,
} from '../types/index.js';
import { resolveVariantFile } from './variant.js';

/** Configuration each subclass must provide for the underlying ORT session. */
export interface BackendConfig {
  /** Stable backend identifier (`'cpu'`, `'mps'`, `'cuda'`, ...). */
  readonly name: BackendName;
  /** ORT execution providers, in priority order. */
  readonly executionProviders: readonly NonNullable<
    InferenceSession.SessionOptions['executionProviders']
  >[number][];
  /** Variant chosen when the user passes `'auto'`. */
  readonly autoVariant: Exclude<ModelVariant, 'auto'>;
}

/** Per-session thread pool sizing. `0` = ORT default. */
export interface SessionThreads {
  readonly intraOpNumThreads?: number;
  readonly interOpNumThreads?: number;
}

/**
 * Abstract base for every ONNX Runtime backend.
 *
 * Subclasses pick a `BackendConfig` (execution providers, default variant)
 * and implement `isAvailable()`. The lifecycle (init/infer/dispose) and
 * tensor plumbing are handled here once.
 */
export abstract class OrtBackend implements BackendProvider {
  private session: Session | null = null;

  protected constructor(
    private readonly config: BackendConfig,
    private readonly modelDir: string,
    readonly variant: ModelVariant,
    private readonly threads: SessionThreads = {},
  ) {}

  get name(): BackendName {
    return this.config.name;
  }

  abstract isAvailable(): Promise<boolean>;

  async init(): Promise<void> {
    if (this.session !== null) return;
    const onnxFile = resolveVariantFile(this.variant, this.config.autoVariant);
    const onnxPath = join(this.modelDir, ONNX_SUBDIR, onnxFile);
    if (!(await fileExists(onnxPath))) {
      throw new ModelNotFoundError(onnxPath);
    }
    const sessionOptions: InferenceSession.SessionOptions = {
      executionProviders: [...this.config.executionProviders],
      graphOptimizationLevel: 'all',
    };
    if (this.threads.intraOpNumThreads !== undefined) {
      sessionOptions.intraOpNumThreads = this.threads.intraOpNumThreads;
    }
    if (this.threads.interOpNumThreads !== undefined) {
      sessionOptions.interOpNumThreads = this.threads.interOpNumThreads;
    }
    this.session = await Session.create(onnxPath, sessionOptions);
  }

  async infer(inputs: InferenceInputs): Promise<InferenceOutputs> {
    const session = this.session;
    if (session === null) throw new ModelNotInitializedError();
    const seqLen = inputs.inputIds.length;
    const feeds = buildFeeds(inputs, seqLen);
    const out = await session.run(feeds);
    const { logits, maxWidth, numClasses } = readLogits(out, session.outputNames, inputs);
    return { logits, textLength: inputs.textLength, maxWidth, numClasses };
  }

  async dispose(): Promise<void> {
    if (this.session === null) return;
    await this.session.release();
    this.session = null;
  }
}

/** Build the 6-input feed dict for `UniEncoderSpanORTModel`. Shapes
 * (batch dim 1 prepended): input_ids/attention_mask/words_mask `[1, T]`,
 * text_lengths `[1]`, span_idx `[1, S, 2]`, span_mask `[1, S]`. */
function buildFeeds(inputs: InferenceInputs, seqLen: number): Record<string, Tensor> {
  const tDims: readonly number[] = [1, seqLen];
  return {
    input_ids: new Tensor('int64', inputs.inputIds, tDims),
    attention_mask: new Tensor('int64', inputs.attentionMask, tDims),
    words_mask: new Tensor('int64', inputs.wordsMask, tDims),
    text_lengths: new Tensor('int64', BigInt64Array.from([BigInt(inputs.textLength)]), [1, 1]),
    span_idx: new Tensor('int64', inputs.spanIdx, [1, inputs.numSpans, 2]),
    span_mask: new Tensor('bool', toBoolArray(inputs.spanMask), [1, inputs.numSpans]),
  };
}

function toBoolArray(src: BigInt64Array): Uint8Array {
  const out = new Uint8Array(src.length);
  for (let i = 0; i < src.length; i++) {
    out[i] = src[i] === 1n ? 1 : 0;
  }
  return out;
}

interface LogitsResult {
  readonly logits: Float32Array;
  readonly maxWidth: number;
  readonly numClasses: number;
}

/** Read GLiNER logits — shape `[1, textLength, maxWidth, numClasses]`,
 * row-major. Inferred dims from `inputs.textLength` and total length. */
function readLogits(
  out: Record<string, Tensor>,
  outputNames: readonly string[],
  inputs: InferenceInputs,
): LogitsResult {
  const name = outputNames[0];
  if (name === undefined) throw new Error('readLogits: model has no outputs');
  const tensor = out[name];
  if (tensor === undefined) throw new Error(`readLogits: missing tensor '${name}'`);
  const flat =
    tensor.data instanceof Float32Array
      ? tensor.data
      : Float32Array.from(tensor.data as ArrayLike<number>);
  const dims = tensor.dims as readonly number[];
  // Expect [batch, textLength, maxWidth, numClasses]. Use as-is if
  // present; otherwise reconstruct from inputs (defensive — some
  // exports drop the batch dim or flatten).
  let maxWidth: number;
  let numClasses: number;
  if (dims.length === 4) {
    maxWidth = Number(dims[2] ?? 0);
    numClasses = Number(dims[3] ?? 0);
  } else if (dims.length === 3) {
    maxWidth = Number(dims[1] ?? 0);
    numClasses = Number(dims[2] ?? 0);
  } else {
    // Fallback: total / (textLength * maxWidth) → infer numClasses.
    maxWidth = inputs.numSpans / Math.max(1, inputs.textLength);
    numClasses = flat.length / Math.max(1, inputs.numSpans);
  }
  return { logits: flat, maxWidth, numClasses };
}
