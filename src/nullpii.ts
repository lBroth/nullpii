import debug from 'debug';
import { MultiOrtBackend } from './backend/multi-backend.js';
import { chunkText, dedupeOverlappingSpans } from './chunking.js';
import {
  BOUNDARY_REFINE_TRIM_CHARS,
  DEFAULT_BOUNDARY_REFINE,
  DEFAULT_RECOGNIZERS,
  DEFAULT_RECOGNIZERS_ENABLED,
  DEFAULT_VARIANT,
} from './defaults.js';
import { DistiluseEncoder } from './distiluse-encoder.js';
import { ModelNotInitializedError, TextTooLongError } from './errors.js';
import { decodeGlinerLogits } from './gliner-decoder.js';
import { buildSpanCandidates } from './gliner-spans.js';
import {
  DEFAULT_MAX_SEQUENCE_LENGTH,
  DEFAULT_MAX_SPAN_WIDTH,
  GlinerTokenizer,
} from './gliner-tokenizer.js';
import { ModelManager } from './model-manager.js';
import { normalizeForDetection, remapSpan } from './normalize.js';
import { runRecognizers } from './recognizers.js';
import { EmbeddingRouter } from './router-embedding.js';
import {
  type NullPiiConfig,
  PII_LABELS,
  type PiiCategory,
  type PiiSpan,
  type Recognizer,
  type RestoreResult,
  type SanitizeResult,
} from './types/index.js';
import { PiiVault } from './vault.js';

const log = debug('nullpii');

const PLACEHOLDER_OPEN = '[[';
// PUA sentinel — round-trip safe and effectively never appears in
// natural text or LLM output.
const PLACEHOLDER_OPEN_ESCAPED = '';

/** Label list passed to GLiNER — the 8 PII categories without `'O'`. */
const GLINER_LABELS: readonly string[] = PII_LABELS.filter((l): l is PiiCategory => l !== 'O');

/**
 * Public entry point. Construct with optional `NullPiiConfig`; call
 * `sanitize` (auto-`init`s) and later `restore` with the returned
 * `sessionId`. Call `dispose` to release native resources.
 */
export class NullPii {
  private readonly config: NullPiiConfig;
  private readonly vault = new PiiVault();
  private readonly recognizers: Recognizer[] = [];
  private backend: MultiOrtBackend | null = null;
  private tokenizer: GlinerTokenizer | null = null;
  private encoder: DistiluseEncoder | null = null;
  private router: EmbeddingRouter | null = null;
  private modelDir: string | null = null;
  private initPromise: Promise<void> | null = null;
  private disposed = false;

  constructor(config: NullPiiConfig = {}) {
    this.config = config;
    if (config.recognizers === 'none') {
      // explicit opt-out
    } else if (Array.isArray(config.recognizers)) {
      this.recognizers.push(...(config.recognizers as readonly Recognizer[]));
    } else if (DEFAULT_RECOGNIZERS_ENABLED) {
      this.recognizers.push(...DEFAULT_RECOGNIZERS);
    }
  }

  /** Register a custom regex-based recognizer. ML matches take priority on overlap. */
  addRecognizer(recognizer: Recognizer): this {
    this.recognizers.push(recognizer);
    return this;
  }

  /** Singleton-promise init, triggered automatically on the first
   * `sanitize()` call. Internal — users don't need to call this directly. */
  private ensureInit(): Promise<void> {
    if (this.disposed) return Promise.reject(new ModelNotInitializedError());
    if (this.initPromise === null) {
      this.initPromise = this.runInit().catch((err) => {
        this.initPromise = null;
        throw err;
      });
    }
    return this.initPromise;
  }

  /** Detect PII spans in `text` and replace them with vault placeholders.
   *
   * Pipeline:
   *   1. Escape `[[` → PUA sentinel.
   *   2. Adversarial normalisation (NFKC + unidecode + zero-width strip
   *      + HTML entity / URL %XX decode + spaced-PII despace).
   *   3. distiluse encode → cosine sim → domain (with enterprise gate).
   *   4. GLiNER 6-input ONNX inference on the per-domain merged-LoRA shard.
   *   5. Sigmoid + threshold + greedy NMS → spans.
   *   6. Regex recognizer pack on the un-normalised text.
   *   7. Threshold filter + boundary refine + vault sanitize.
   *
   * Inputs longer than GLiNER's `max_len=384` subword tokens are silently
   * truncated; pass `strictLength: true` to throw instead.
   */
  async sanitize(text: string, sessionId?: string): Promise<SanitizeResult> {
    await this.ensureInit();
    const tokenizer = this.tokenizer;
    const backend = this.backend;
    const encoder = this.encoder;
    const router = this.router;
    if (tokenizer === null || backend === null || encoder === null || router === null) {
      throw new ModelNotInitializedError();
    }

    const escaped = escapePlaceholders(text);
    const { normalized, normToOrig } = normalizeForDetection(escaped);

    const embedding = await encoder.encode(normalized);
    const decision = router.route(embedding);
    log('route: domain=%s score=%f gated=%s', decision.domain, decision.score, decision.gated);

    const threshold = this.config.threshold ?? 0.5;
    const chunks = chunkText(normalized);
    const decodedRaw: Array<{ label: string; start: number; end: number; score: number }> = [];
    for (const { text: chunk, offset } of chunks) {
      const enc = await tokenizer.encode(chunk, GLINER_LABELS);
      if (this.config.strictLength === true && enc.truncated) {
        throw new TextTooLongError(enc.seqLen, DEFAULT_MAX_SEQUENCE_LENGTH);
      }
      const cand = buildSpanCandidates(enc.numWords, DEFAULT_MAX_SPAN_WIDTH);
      const out = await backend.infer(
        {
          inputIds: enc.inputIds,
          attentionMask: enc.attentionMask,
          wordsMask: enc.wordsMask,
          textLength: enc.numWords,
          spanIdx: cand.spanIdx,
          spanMask: cand.spanMask,
          numSpans: cand.numSpans,
        },
        decision.domain,
      );
      const chunkSpans = decodeGlinerLogits(
        out.logits,
        out.textLength,
        out.maxWidth,
        out.numClasses,
        enc.words,
        GLINER_LABELS,
        threshold,
      );
      for (const s of chunkSpans) {
        decodedRaw.push({
          label: s.label,
          start: s.start + offset,
          end: s.end + offset,
          score: s.score,
        });
      }
    }
    const decoded = dedupeOverlappingSpans(decodedRaw);

    // Remap span offsets from the normalised text back to the escaped
    // text so they align with the regex pack and vault output.
    const mlSpans: PiiSpan[] =
      normalized === escaped
        ? decoded.map((s) => ({
            label: s.label as PiiCategory,
            start: s.start,
            end: s.end,
            score: s.score,
            text: escaped.slice(s.start, s.end),
          }))
        : decoded.map((s) => {
            const [origStart, origEnd] = remapSpan(s.start, s.end, normToOrig);
            return {
              label: s.label as PiiCategory,
              start: origStart,
              end: origEnd,
              score: s.score,
              text: escaped.slice(origStart, origEnd),
            };
          });

    const recoSpans = runRecognizers(escaped, this.recognizers, mlSpans);
    const merged = applyThresholds(
      [...mlSpans, ...recoSpans],
      this.config.threshold ?? 0,
      this.config.categoryThresholds ?? {},
    );
    const refineOn = this.config.boundaryRefine ?? DEFAULT_BOUNDARY_REFINE;
    const spans = refineOn ? refineSpanBoundaries(escaped, merged) : merged;

    const session = sessionId ?? this.vault.createSession();
    log('sanitize: spans=%d session=%s', spans.length, session.slice(0, 8));
    const result = this.vault.sanitize(escaped, spans, session);
    return mapBackToOriginal(result, text);
  }

  restore(text: string, sessionId: string): RestoreResult {
    const r = this.vault.restore(text, sessionId);
    return { restored: unescapePlaceholders(r.restored), replacements: r.replacements };
  }

  destroySession(sessionId: string): void {
    this.vault.destroySession(sessionId);
  }

  async dispose(): Promise<void> {
    if (this.backend !== null) await this.backend.dispose();
    if (this.encoder !== null) await this.encoder.dispose();
    this.backend = null;
    this.tokenizer = null;
    this.encoder = null;
    this.router = null;
    this.disposed = true;
  }

  private async runInit(): Promise<void> {
    const manager = new ModelManager();
    if (this.config.modelDir !== undefined) {
      this.modelDir = this.config.modelDir;
    } else {
      const ensured = await manager.ensure({
        variant: this.config.variant ?? DEFAULT_VARIANT,
        ...(this.config.downloadTimeoutMs !== undefined && {
          timeoutMs: this.config.downloadTimeoutMs,
        }),
      });
      this.modelDir = ensured.modelDir;
    }

    // Constructor work (no I/O): MultiOrtBackend lazy-loads per-domain
    // ONNX shards on first inference; GlinerTokenizer lazy-loads
    // tokenizer.json on first encode; DistiluseEncoder + EmbeddingRouter
    // do their disk reads inside init() and run in parallel below.
    this.backend = new MultiOrtBackend(this.modelDir);
    this.encoder = new DistiluseEncoder(this.modelDir);
    this.router = new EmbeddingRouter(this.modelDir);
    this.tokenizer = new GlinerTokenizer(
      this.modelDir,
      this.config.maxSequenceLength ?? DEFAULT_MAX_SEQUENCE_LENGTH,
    );
    await Promise.all([this.encoder.init(), this.router.init()]);
    log(
      'init complete: modelDir=%s domains=%s',
      this.modelDir,
      this.router.listDomains().join(','),
    );
  }
}

/** Trim leading/trailing whitespace + common punctuation from each
 * span's edges; drop spans that collapse to empty. */
function refineSpanBoundaries(text: string, spans: readonly PiiSpan[]): PiiSpan[] {
  const trim = BOUNDARY_REFINE_TRIM_CHARS;
  const out: PiiSpan[] = [];
  for (const s of spans) {
    let start = s.start;
    let end = s.end;
    while (start < end && trim.includes(text[start] as string)) start += 1;
    while (end > start && trim.includes(text[end - 1] as string)) end -= 1;
    if (start >= end) continue;
    if (start === s.start && end === s.end) {
      out.push(s);
    } else {
      // Recompute the slice — vault uses span.text verbatim.
      out.push({ ...s, start, end, text: text.slice(start, end) });
    }
  }
  return out;
}

/** Drop spans below threshold. Per-category override wins over the global threshold. */
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

function escapePlaceholders(text: string): string {
  return text.split(PLACEHOLDER_OPEN).join(PLACEHOLDER_OPEN_ESCAPED);
}

function unescapePlaceholders(text: string): string {
  return text.split(PLACEHOLDER_OPEN_ESCAPED).join(PLACEHOLDER_OPEN);
}

function mapBackToOriginal(result: SanitizeResult, _original: string): SanitizeResult {
  return { ...result, sanitized: unescapePlaceholders(result.sanitized) };
}

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
