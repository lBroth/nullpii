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
    const feeds = buildFeeds(session.inputNames, inputs, seqLen);
    const out = await session.run(feeds);
    const logits = readLogits(out, session.outputNames);
    const numLabels = logits.length / seqLen;
    return { logits, seqLen, numLabels };
  }

  async dispose(): Promise<void> {
    if (this.session === null) return;
    await this.session.release();
    this.session = null;
  }
}

function buildFeeds(
  inputNames: readonly string[],
  inputs: InferenceInputs,
  seqLen: number,
): Record<string, Tensor> {
  const dims: readonly number[] = [1, seqLen];
  const feeds: Record<string, Tensor> = {};
  if (inputNames.includes('input_ids')) {
    feeds.input_ids = new Tensor('int64', inputs.inputIds, dims);
  }
  if (inputNames.includes('attention_mask')) {
    feeds.attention_mask = new Tensor('int64', inputs.attentionMask, dims);
  }
  return feeds;
}

function readLogits(out: Record<string, Tensor>, outputNames: readonly string[]): Float32Array {
  const name = outputNames[0];
  if (name === undefined) throw new Error('readLogits: model has no outputs');
  const tensor = out[name];
  if (tensor === undefined) throw new Error(`readLogits: missing tensor '${name}'`);
  return tensor.data instanceof Float32Array
    ? tensor.data
    : Float32Array.from(tensor.data as ArrayLike<number>);
}
