// SPDX-License-Identifier: Apache-2.0

import debug from 'debug';
import { OrtUnifiedBackend } from './backend/unified-backend.js';
import { detectBase64Pii } from './base64-detector.js';
import { chunkText, dedupeOverlappingSpans } from './chunking.js';
import { nullpiiModelDir } from './config.js';
import {
  BOUNDARY_REFINE_TRIM_CHARS,
  DEFAULT_BOUNDARY_REFINE,
  DEFAULT_DECODE_THRESHOLD,
  DEFAULT_DEDUPE_IOU,
  DEFAULT_POST_FILTER_THRESHOLD,
  DEFAULT_RECOGNIZERS,
  DEFAULT_RECOGNIZERS_ENABLED,
  DEFAULT_VARIANT,
  MAX_INPUT_BYTES,
} from './defaults.js';
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
import {
  GLINER_MODEL_CATEGORIES,
  type NullPiiConfig,
  type PiiCategory,
  type PiiSpan,
  type Recognizer,
  type RestoreOptions,
  type RestoreResult,
  type SanitizeResult,
} from './types/index.js';
import { PiiVault } from './vault.js';

const log = debug('nullpii');

const PLACEHOLDER_OPEN = '{{';
// PUA sentinel — round-trip safe and effectively never appears in
// natural text or LLM output.
const PLACEHOLDER_OPEN_ESCAPED = '';

/** Label list prompted to GLiNER — the 8 ML categories the unified
 * model was trained on. `private_ip` is intentionally excluded: it is
 * a post-pass recognizer label only. */
const GLINER_LABELS: readonly string[] = GLINER_MODEL_CATEGORIES;

/**
 * Public entry point. Construct with optional `NullPiiConfig`; call
 * `sanitize` (auto-`init`s) and later `restore` with the returned
 * `sessionId`. Call `dispose` to release native resources.
 */
export class NullPii {
  private readonly config: NullPiiConfig;
  private readonly vault = new PiiVault();
  private readonly recognizers: Recognizer[] = [];
  private backend: OrtUnifiedBackend | null = null;
  private tokenizer: GlinerTokenizer | null = null;
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

  /** Detect PII in `text`, replace with vault placeholders, return
   * `{ sessionId, sanitized, spans }`.
   *
   * Pipeline: escape `[[` → adversarial-normalise → chunk + GLiNER infer
   * (unified ONNX) → recognizer pack on escaped + normalized + base64 →
   * cross-label dedupe + threshold → boundary refine → vault sanitize.
   *
   * Inputs over `max_len=384` subwords truncate silently. Pass
   * `strictLength: true` to throw `TextTooLongError` instead. */
  async sanitize(text: string, sessionId?: string): Promise<SanitizeResult> {
    // Hard cap. Adversarial 1 MB+ payloads cause quadratic regex behaviour
    // and bypass both the recognizer pack and the adversarial-normalize
    // pass. Refuse upfront so callers learn to chunk; matches the
    // README "Inputs > 1 MB — refused upfront" contract.
    if (text.length > MAX_INPUT_BYTES) {
      throw new TextTooLongError(text.length, MAX_INPUT_BYTES, 'bytes');
    }
    await this.ensureInit();
    const tokenizer = this.tokenizer;
    const backend = this.backend;
    if (tokenizer === null || backend === null) {
      throw new ModelNotInitializedError();
    }

    const escaped = escapePlaceholders(text);
    const { normalized, normToOrig } = normalizeForDetection(escaped);

    const threshold = this.config.threshold ?? DEFAULT_DECODE_THRESHOLD;
    const chunks = chunkText(normalized);
    const decodedRaw: Array<{ label: string; start: number; end: number; score: number }> = [];
    for (const { text: chunk, offset } of chunks) {
      const enc = await tokenizer.encode(chunk, GLINER_LABELS);
      if (this.config.strictLength === true && enc.truncated) {
        throw new TextTooLongError(enc.seqLen, DEFAULT_MAX_SEQUENCE_LENGTH);
      }
      const cand = buildSpanCandidates(enc.numWords, DEFAULT_MAX_SPAN_WIDTH);
      const out = await backend.infer({
        inputIds: enc.inputIds,
        attentionMask: enc.attentionMask,
        wordsMask: enc.wordsMask,
        textLength: enc.numWords,
        spanIdx: cand.spanIdx,
        spanMask: cand.spanMask,
        numSpans: cand.numSpans,
      });
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

    // Recognizers run on the *escaped* text so their spans align with
    // the vault output. For inputs where normalisation changed the text
    // (URL %XX, HTML entities, despace, NFKC/transliterate, …) the
    // recognizer patterns can't match the original encoded form — e.g.
    // the email regex won't fire on `john%40acme%2Ecom`. Run them on
    // `normalized` too and remap the hits back so encoded PII is caught
    // by the regex pack, not just the model.
    const recoSpansEscaped = runRecognizers(escaped, this.recognizers, mlSpans);
    const recoSpansNorm: PiiSpan[] =
      normalized === escaped
        ? []
        : runRecognizers(normalized, this.recognizers, []).map((s) => {
            const [origStart, origEnd] = remapSpan(s.start, s.end, normToOrig);
            return {
              label: s.label as PiiCategory,
              start: origStart,
              end: origEnd,
              score: s.score,
              text: escaped.slice(origStart, origEnd),
            } as PiiSpan;
          });
    // Base64-wrapped PII: regex can't see `user.123@gmail.com` inside
    // `dXNlci4xMjNAZ21haWwuY29t` until we decode the blob. Run on the
    // escaped surface so spans land on the source base64 substring (gold
    // annotations mark the encoded form).
    const base64Spans = detectBase64Pii(escaped);
    const recoSpans: PiiSpan[] = [...recoSpansEscaped, ...recoSpansNorm, ...base64Spans];
    // High-confidence recognizers (≥ 0.9) emit even when overlapping ML
    // output, so dedupe by IoU + score: highest score wins regardless
    // of label. Catches the common case where the unified GLiNER
    // mislabels a known pattern (e.g., `ghp_…` token classified as
    // `account_number`) — recognizer's `secret` (0.99) overrides ML's
    // `account_number` (0.5–0.7).
    const combined = dedupeOverlappingSpans(
      [...mlSpans, ...recoSpans] as PiiSpan[],
      DEFAULT_DEDUPE_IOU,
      { acrossLabels: true },
    ) as PiiSpan[];
    const merged = applyThresholds(
      combined,
      this.config.threshold ?? DEFAULT_POST_FILTER_THRESHOLD,
      this.config.categoryThresholds ?? {},
    );
    const refineOn = this.config.boundaryRefine ?? DEFAULT_BOUNDARY_REFINE;
    const spans = refineOn ? refineSpanBoundaries(escaped, merged) : merged;

    const session = sessionId ?? this.vault.createSession();
    log('sanitize: spans=%d session=%s', spans.length, session.slice(0, 8)); // 8-char log prefix (8 ≠ SESSION_PREFIX_LEN; log truncation is purely for readability, not security)
    const result = this.vault.sanitize(escaped, spans, session);
    return mapBackToOriginal(result, text);
  }

  restore(text: string, sessionId: string, options: RestoreOptions = {}): RestoreResult {
    const r = this.vault.restore(text, sessionId, options);
    return {
      restored: unescapePlaceholders(r.restored),
      replacements: r.replacements,
      replacementsByLabel: r.replacementsByLabel,
      unknownPlaceholders: r.unknownPlaceholders,
      foreignPlaceholders: r.foreignPlaceholders,
    };
  }

  destroySession(sessionId: string): void {
    this.vault.destroySession(sessionId);
  }

  async dispose(): Promise<void> {
    if (this.backend !== null) await this.backend.dispose();
    this.backend = null;
    this.tokenizer = null;
    this.vault.clear();
    this.disposed = true;
  }

  private async runInit(): Promise<void> {
    const manager = new ModelManager();
    // Resolution order for the model directory:
    //   1. explicit `config.modelDir` (caller intent)
    //   2. `NULLPII_MODEL_DIR` env var (deployment override / air-gap)
    //   3. fall through to HF download into the default cache
    const envModelDir = nullpiiModelDir();
    if (this.config.modelDir !== undefined) {
      this.modelDir = this.config.modelDir;
    } else if (envModelDir !== undefined) {
      this.modelDir = envModelDir;
    } else {
      const ensured = await manager.ensure({
        variant: this.config.variant ?? DEFAULT_VARIANT,
        ...(this.config.downloadTimeoutMs !== undefined && {
          timeoutMs: this.config.downloadTimeoutMs,
        }),
      });
      this.modelDir = ensured.modelDir;
    }

    // Constructor work (no I/O): OrtUnifiedBackend lazy-loads `model.onnx`
    // on first inference; GlinerTokenizer lazy-loads `tokenizer.json` on
    // first encode.
    this.backend = new OrtUnifiedBackend(this.modelDir, {
      executionProviders: backendToProviders(this.config.backend),
      ...(this.config.intraOpNumThreads !== undefined && {
        intraOpNumThreads: this.config.intraOpNumThreads,
      }),
      ...(this.config.interOpNumThreads !== undefined && {
        interOpNumThreads: this.config.interOpNumThreads,
      }),
    });
    this.tokenizer = new GlinerTokenizer(
      this.modelDir,
      this.config.maxSequenceLength ?? DEFAULT_MAX_SEQUENCE_LENGTH,
    );
    log('init complete: modelDir=%s', this.modelDir);
  }
}

/** Map the public {@link BackendName} to an ORT execution-provider list.
 * Order matters — ORT tries each provider in turn and falls back. CPU is
 * always appended last so the runtime never throws purely because the
 * preferred accelerator is unavailable. */
function backendToProviders(
  backend: NullPiiConfig['backend'],
): ReadonlyArray<'cpu' | 'cuda' | 'coreml'> {
  switch (backend) {
    case 'cuda':
      return ['cuda', 'cpu'];
    case 'mps':
      return ['coreml', 'cpu'];
    case 'cpu':
      return ['cpu'];
    case 'auto':
    case undefined:
      return ['cpu'];
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

/** Engine cache for the convenience `sanitize()` / `restore()` helpers.
 *
 * A previous version used a single `_shared` instance for no-arg callers
 * and `new NullPii(config)` for everything else — the latter leaked an
 * ORT session + vault per call because the engine was never disposed.
 *
 * The current shape:
 *
 *  1. Configs that are *structurally fingerprintable* (no `recognizers`
 *     array, no other regex/function-valued fields) are cached by their
 *     canonical JSON fingerprint. Bare `sanitize(text)` hits the empty
 *     fingerprint slot.
 *  2. Configs carrying custom `recognizers: Recognizer[]` cannot be safely
 *     fingerprinted — `JSON.stringify` flattens regex / fn to `{}` and would
 *     collide two distinct recognizer sets into one shared vault (the prior
 *     bug). Those callers get a fresh `NullPii` and a `NullPiiOneShotWarning`
 *     telling them to manage the lifecycle themselves.
 *  3. A `FinalizationRegistry` calls `dispose()` when a leaked engine is
 *     GC'd. Best-effort defence in depth — does not replace explicit
 *     lifecycle management on the caller side.
 *
 *  `recognizers: 'none'` is a value sentinel and IS fingerprintable, so it
 *  remains cacheable. */
const _cache = new Map<string, NullPii>();

const _finalizer =
  typeof FinalizationRegistry === 'undefined'
    ? null
    : new FinalizationRegistry<{ readonly engine: NullPii }>((held) => {
        held.engine.dispose().catch(() => {
          /* finalizer is best-effort; swallow errors */
        });
      });

/** Canonical fingerprint of a `NullPiiConfig`. Returns `null` if the config
 * carries values that can't be structurally hashed (regex / function under
 * `recognizers`), signalling the caller-must-own-lifecycle path. */
function configFingerprint(config: NullPiiConfig): string | null {
  if (Array.isArray(config.recognizers)) return null;
  const entries: Array<[string, unknown]> = [];
  for (const k of Object.keys(config).sort()) {
    const v = (config as Record<string, unknown>)[k];
    if (v === undefined) continue;
    entries.push([k, v]);
  }
  return JSON.stringify(entries);
}

function instance(config: NullPiiConfig = {}): NullPii {
  const fp = configFingerprint(config);
  if (fp === null) {
    process.emitWarning(
      'nullpii: sanitize()/restore() called with custom `recognizers` — a fresh ' +
        'NullPii is created on each call because regex/function recognizers cannot ' +
        'be structurally cached. The engine will NOT be disposed automatically. ' +
        'For repeated calls, instantiate `new NullPii({ recognizers: [...] })` ' +
        'once and call `.dispose()` yourself when done.',
      'NullPiiOneShotWarning',
    );
    const np = new NullPii(config);
    // FR rejects target === heldValue; use a weakref-style separate token.
    _finalizer?.register(np, { engine: np });
    return np;
  }
  let np = _cache.get(fp);
  if (np === undefined) {
    np = new NullPii(config);
    _cache.set(fp, np);
  }
  return np;
}

/** Test-only escape hatch. Drops the engine cache so tests can assert on
 * fresh-cache behaviour without leaking state across describe blocks. Not
 * exported via `src/index.ts` — internal only. */
export function __resetEngineCacheForTests(): void {
  for (const np of _cache.values()) {
    np.dispose().catch(() => {
      /* test teardown */
    });
  }
  _cache.clear();
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
  configOrOptions: NullPiiConfig | RestoreOptions = {},
  options: RestoreOptions = {},
): RestoreResult {
  // Accept the legacy 3-arg form `restore(text, sessionId, config)` and the
  // new 4-arg form `restore(text, sessionId, config, options)`. When called
  // with only 3 args and the third looks like an options bag (i.e. has
  // `strict`), interpret it as options against the default config.
  const looksLikeOptions = 'strict' in configOrOptions && Object.keys(configOrOptions).length === 1;
  if (looksLikeOptions) {
    return instance({}).restore(text, sessionId, configOrOptions as RestoreOptions);
  }
  return instance(configOrOptions as NullPiiConfig).restore(text, sessionId, options);
}
