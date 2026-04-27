// SPDX-License-Identifier: Apache-2.0
import debug from 'debug';
import { type TokenChunk, dedupeSpans, partitionTokens } from './chunking.js';
import { DEFAULT_MODEL_REPO, DEFAULT_MODEL_REVISION, DEFAULT_VARIANT } from './defaults.js';
import { ModelNotInitializedError, TextTooLongError } from './errors.js';
import { LABEL_MAP, NUM_LABELS } from './labels-bioes.js';
import { ModelManager } from './model-manager.js';
import { runRecognizers } from './recognizers.js';
import { selectBackend } from './router.js';
import { decodeSpans } from './span-decoder.js';
import { TokenizerWrapper } from './tokenizer.js';
import {
  type BackendProvider,
  CHUNK_OVERLAP_TOKENS,
  MAX_SEQUENCE_LENGTH,
  type NullPiiConfig,
  type PiiSpan,
  type Recognizer,
  type RestoreResult,
  type SanitizeResult,
} from './types/index.js';
import { PiiVault } from './vault.js';
import { forwardBackwardMarginals, viterbiBioesDecode } from './viterbi.js';

const log = debug('nullpii');

const PLACEHOLDER_OPEN = '[[';
const PLACEHOLDER_OPEN_ESCAPED = '[\\[';

/**
 * Public entry point for the library.
 *
 * Construct with optional `NullPiiConfig`; call `sanitize` (auto-`init`s)
 * and later `restore` with the returned `sessionId`. Call `dispose` when
 * done to release the backend's native resources.
 */
export class NullPii {
  private readonly config: NullPiiConfig;
  private readonly vault = new PiiVault();
  private readonly recognizers: Recognizer[] = [];
  private backend: BackendProvider | null = null;
  private tokenizer: TokenizerWrapper | null = null;
  private modelDir: string | null = null;
  private initPromise: Promise<void> | null = null;
  private disposed = false;

  constructor(config: NullPiiConfig = {}) {
    this.config = config;
  }

  /** Register a custom regex-based recognizer that runs as a post-pass
   * after the ML detector. ML matches take priority on overlap. */
  addRecognizer(recognizer: Recognizer): this {
    this.recognizers.push(recognizer);
    return this;
  }

  /** Lazy-init: download the model, select & load a backend, build the
   * tokenizer. Idempotent and concurrency-safe (singleton promise). */
  init(): Promise<void> {
    if (this.disposed) return Promise.reject(new ModelNotInitializedError());
    if (this.initPromise === null) {
      this.initPromise = this.runInit().catch((err) => {
        this.initPromise = null;
        throw err;
      });
    }
    return this.initPromise;
  }

  /** Detect PII spans in `text` and replace them with vault placeholders. */
  async sanitize(text: string, sessionId?: string): Promise<SanitizeResult> {
    await this.init();
    const tokenizer = this.tokenizer;
    const backend = this.backend;
    if (tokenizer === null || backend === null) throw new ModelNotInitializedError();

    const escaped = escapePlaceholders(text);
    const enc = await tokenizer.encode(escaped);

    const chunkSize = this.config.maxSequenceLength ?? MAX_SEQUENCE_LENGTH;
    const overlap = this.config.chunkOverlap ?? CHUNK_OVERLAP_TOKENS;
    if (this.config.strictLength === true && enc.inputIds.length > chunkSize) {
      throw new TextTooLongError(enc.inputIds.length, chunkSize);
    }

    const chunks = partitionTokens(enc, chunkSize, overlap);
    const allSpans: PiiSpan[] = [];
    for (const chunk of chunks) {
      const spans = await this.inferChunk(backend, chunk, escaped);
      allSpans.push(...spans);
    }
    const mlSpans = chunks.length === 1 ? allSpans : dedupeSpans(allSpans);
    const recoSpans = dedupeSpans(runRecognizers(escaped, this.recognizers, mlSpans));
    const spans = applyThresholds(
      [...mlSpans, ...recoSpans],
      this.config.threshold ?? 0,
      this.config.categoryThresholds ?? {},
    );

    const session = sessionId ?? this.vault.createSession();
    log(
      'sanitize: spans=%d chunks=%d session=%s',
      spans.length,
      chunks.length,
      session.slice(0, 8),
    );
    const result = this.vault.sanitize(escaped, spans, session);
    return mapBackToOriginal(result, text);
  }

  private async inferChunk(
    backend: BackendProvider,
    chunk: TokenChunk,
    escaped: string,
  ): Promise<PiiSpan[]> {
    const out = await backend.infer({
      inputIds: chunk.inputIds,
      attentionMask: chunk.attentionMask,
    });
    if (out.numLabels !== NUM_LABELS) {
      throw new Error(`sanitize: model emits ${out.numLabels} labels, expected ${NUM_LABELS}`);
    }
    const biases = this.config.transitionBiases ?? {};
    const labels = viterbiBioesDecode(out.logits, out.seqLen, out.numLabels, LABEL_MAP, biases);
    const marginals = forwardBackwardMarginals(
      out.logits,
      out.seqLen,
      out.numLabels,
      LABEL_MAP,
      biases,
    );
    const scores = posteriorScores(marginals, out.seqLen, out.numLabels, labels);
    return decodeSpans(labels, chunk.offsetMapping, scores, escaped);
  }

  restore(text: string, sessionId: string): RestoreResult {
    // Restore-input may already contain valid `[[NULLPII:..]]` we want to
    // match — don't escape it. After replacement, unescape `[\[` back to
    // `[[` so user's original literal `[[` content survives the round-trip.
    const r = this.vault.restore(text, sessionId);
    return { restored: unescapePlaceholders(r.restored), replacements: r.replacements };
  }

  destroySession(sessionId: string): void {
    this.vault.destroySession(sessionId);
  }

  async dispose(): Promise<void> {
    if (this.backend !== null) await this.backend.dispose();
    this.backend = null;
    this.tokenizer = null;
    this.disposed = true;
  }

  private async runInit(): Promise<void> {
    const manager = new ModelManager();
    if (this.config.modelDir !== undefined) {
      this.modelDir = this.config.modelDir;
    } else {
      const ensured = await manager.ensure({
        variant: this.config.variant ?? DEFAULT_VARIANT,
        model: {
          repo: this.config.model?.repo ?? DEFAULT_MODEL_REPO,
          revision: this.config.model?.revision ?? DEFAULT_MODEL_REVISION,
        },
        ...(this.config.downloadTimeoutMs !== undefined && {
          timeoutMs: this.config.downloadTimeoutMs,
        }),
      });
      this.modelDir = ensured.modelDir;
    }
    this.backend = await selectBackend(this.modelDir, this.config);
    await this.backend.init();
    this.tokenizer = new TokenizerWrapper(
      this.modelDir,
      this.config.maxSequenceLength ?? MAX_SEQUENCE_LENGTH,
    );
    log('init complete: backend=%s modelDir=%s', this.backend.name, this.modelDir);
  }
}

/** Per-token posterior probability of the chosen Viterbi label.
 * Uses forward-backward marginals so the score reflects the model's full
 * sequence-level posterior, not just the local-best softmax. */
function posteriorScores(
  marginals: Float64Array,
  seqLen: number,
  numLabels: number,
  labels: readonly string[],
): number[] {
  const out: number[] = new Array(seqLen);
  for (let t = 0; t < seqLen; t++) {
    const labelIdx = LABEL_MAP.indexOf(labels[t] ?? 'O');
    const logProb = marginals[t * numLabels + labelIdx];
    out[t] = logProb === undefined || logProb === Number.NEGATIVE_INFINITY ? 0 : Math.exp(logProb);
  }
  return out;
}

/** Drop spans below the configured score thresholds.
 * Per-category override wins over the global threshold when set. */
function applyThresholds(
  spans: PiiSpan[],
  globalThreshold: number,
  perLabel: Partial<Record<string, number>>,
): PiiSpan[] {
  const noPerLabel = Object.keys(perLabel).length === 0;
  if (globalThreshold <= 0 && noPerLabel) return spans;
  return spans.filter((s) => {
    const t = perLabel[s.label] ?? globalThreshold;
    return s.score >= t;
  });
}

/** Escape literal `[[` in user text so it cannot collide with our placeholder
 * format. Round-trip safe via `unescapePlaceholders`. */
function escapePlaceholders(text: string): string {
  return text.split(PLACEHOLDER_OPEN).join(PLACEHOLDER_OPEN_ESCAPED);
}

function unescapePlaceholders(text: string): string {
  return text.split(PLACEHOLDER_OPEN_ESCAPED).join(PLACEHOLDER_OPEN);
}

/** After sanitize, the result text has placeholders inserted into the
 * already-escaped string. Unescape so the caller sees their original
 * non-PII characters back. */
function mapBackToOriginal(result: SanitizeResult, _original: string): SanitizeResult {
  return { ...result, sanitized: unescapePlaceholders(result.sanitized) };
}

/* ------------------------------------------------------------------ *
 *  Functional convenience wrappers — bounded LRU, dispose on evict
 * ------------------------------------------------------------------ */

const INSTANCE_CACHE_MAX = 8;
const _instances = new Map<string, NullPii>();

function instance(config: NullPiiConfig = {}): NullPii {
  const key = JSON.stringify(config);
  const cached = _instances.get(key);
  if (cached !== undefined) {
    _instances.delete(key);
    _instances.set(key, cached);
    return cached;
  }
  if (_instances.size >= INSTANCE_CACHE_MAX) {
    const oldestKey = _instances.keys().next().value;
    if (oldestKey !== undefined) {
      const evicted = _instances.get(oldestKey);
      _instances.delete(oldestKey);
      void evicted?.dispose();
    }
  }
  const fresh = new NullPii(config);
  _instances.set(key, fresh);
  return fresh;
}

/** Convenience: `await sanitize(text)` using a process-wide instance. */
export async function sanitize(
  text: string,
  config: NullPiiConfig = {},
  sessionId?: string,
): Promise<SanitizeResult> {
  return instance(config).sanitize(text, sessionId);
}

/** Convenience: `await restore(text, sessionId)` using the same shared instance. */
export function restore(
  text: string,
  sessionId: string,
  config: NullPiiConfig = {},
): RestoreResult {
  return instance(config).restore(text, sessionId);
}
