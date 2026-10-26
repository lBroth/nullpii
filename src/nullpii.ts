// SPDX-License-Identifier: Apache-2.0

import { joinAddressParts } from './address-join.js';
import { OrtBackend } from './backend/backend.js';
import { detectBase64Pii } from './base64-detector.js';
import { dedupeOverlappingSpans, forEachWindow } from './chunking.js';
import { NULLPII_MODEL_DIR, readEnvVar } from './config.js';
import {
  BOUNDARY_REFINE_TRIM_CHARS,
  DEFAULT_BACKEND,
  DEFAULT_BOUNDARY_REFINE,
  DEFAULT_CATEGORY_THRESHOLDS,
  DEFAULT_DECODE_THRESHOLD,
  DEFAULT_DEDUPE_IOU,
  DEFAULT_DISABLED_CATEGORIES,
  DEFAULT_POST_FILTER_THRESHOLD,
  DEFAULT_RECOGNIZERS,
  DEFAULT_RECOGNIZERS_ENABLED,
  DEFAULT_VARIANT,
  MAX_INPUT_CHARS,
  SEGMENT_OVERLAP_CHARS,
} from './defaults.js';
import { EngineDisposedError, ModelNotInitializedError, TextTooLongError } from './errors.js';
import { resolveNonCoordinateGeolocation } from './geo-filter.js';
import { decodeGlinerLogits } from './gliner-decoder.js';
import { buildSpanCandidates } from './gliner-spans.js';
import {
  DEFAULT_MAX_SEQUENCE_LENGTH,
  DEFAULT_MAX_SPAN_WIDTH,
  GlinerTokenizer,
} from './gliner-tokenizer.js';
import { dropModelIpv4Spans } from './ip-filter.js';
import { logf } from './log.js';
import { dropDatesInsideMachineTimestamps } from './machine-timestamps.js';
import { ModelManager } from './model-manager.js';
import { onnxCandidates } from './model-variant.js';
import { normalizeForDetection, remapSpan } from './normalize.js';
import { escapePlaceholders, unescapePlaceholders } from './placeholder-escape.js';
import { dropAssistantNameSpans } from './product-names.js';
import { dropSpansInsidePublicDigests } from './public-digests.js';
import { runRecognizers } from './recognizers.js';
import { segmentWindows } from './segments.js';
import {
  type EnginePolicy,
  GLINER_EXTENDED_CATEGORIES,
  GLINER_MODEL_CATEGORIES,
  GLINER_ZERO_SHOT_EXTRA,
  type NullPiiConfig,
  type PiiCategory,
  type PiiSpan,
  type Recognizer,
  type RestoreOptions,
  type RestoreResult,
  type SanitizeOptions,
  type SanitizeResult,
} from './types/index.js';
import type { ScoredSpan } from './types/scored-span.js';
import { type UrlPolicy, dropCleanPublicUrlSpans, urlPolicy } from './url-filter.js';
import { resolveUuidAccountNumbers } from './uuid-filter.js';
import { PiiVault } from './vault.js';

const LOG_SCOPE = 'nullpii';

/** A model span with offsets into the normalized text, before remapping. */
interface DecodedSpan {
  readonly label: string;
  readonly start: number;
  readonly end: number;
  readonly score: number;
}

/** Every label the model can be prompted with, in prompt order: trained,
 * zero-shot, then the extended categories. See `types/labels.ts`. */
const GLINER_LABELS: readonly PiiCategory[] = [
  ...GLINER_MODEL_CATEGORIES,
  ...GLINER_ZERO_SHOT_EXTRA,
  ...GLINER_EXTENDED_CATEGORIES,
];

/** The text a sanitize call works on: the input with literal `{{`
 * escaped (`escaped`, what the vault sees), its detection-normalised form
 * (`normalized`), and the offset map between them. */
interface Surfaces {
  readonly escaped: string;
  readonly normalized: string;
  readonly normToOrig: readonly number[];
}

/** What detection found on a text, before the final cuts: the model's and
 * the recognizers' spans, and the words the model could not read. */
interface Detected {
  readonly spans: PiiSpan[];
  readonly unscannedWords: number;
}

/** Spans found on `surfaces.normalized`, moved onto `surfaces.escaped`
 * (unchanged when normalisation changed nothing) with their text read
 * there. */
function toEscapedSpans(
  spans: ReadonlyArray<{ label: string; start: number; end: number; score: number }>,
  surfaces: Surfaces,
): PiiSpan[] {
  const { escaped, normalized, normToOrig } = surfaces;
  return spans.map((s) => {
    const [start, end] =
      normalized === escaped ? [s.start, s.end] : remapSpan(s.start, s.end, normToOrig);
    return {
      label: s.label as PiiCategory,
      start,
      end,
      score: s.score,
      text: escaped.slice(start, end),
    };
  });
}

/**
 * Public entry point. Construct with optional `NullPiiConfig`; call
 * `sanitize` (auto-`init`s) and later `restore` with the returned
 * `sessionId`. Call `dispose` to release native resources.
 */
export class NullPii {
  private config: NullPiiConfig;
  /** `GLINER_LABELS` minus `config.disabledCategories`. */
  private promptLabels: readonly string[] = [];
  private disabled: ReadonlySet<string> = new Set();
  /** How much of a clean URL stays readable; `null` masks every URL. */
  private urlPolicy: UrlPolicy | null = null;
  private readonly vault = new PiiVault();
  private readonly recognizers: Recognizer[] = [];
  private backend: OrtBackend | null = null;
  private tokenizer: GlinerTokenizer | null = null;
  private modelDir: string | null = null;
  private initPromise: Promise<void> | null = null;
  private disposed = false;
  /** `sanitize()` calls not yet settled; `dispose()` waits for them. */
  private readonly inFlight = new Set<Promise<SanitizeResult>>();

  constructor(config: NullPiiConfig = {}) {
    // Fail on an unknown variant here, not at the first sanitize().
    onnxCandidates(config.variant ?? DEFAULT_VARIANT, config.backend ?? DEFAULT_BACKEND);
    this.config = config;
    this.derivePolicy();
    if (config.recognizers === 'none') return;
    if (Array.isArray(config.recognizers)) {
      this.recognizers.push(...(config.recognizers as readonly Recognizer[]));
      return;
    }
    if (DEFAULT_RECOGNIZERS_ENABLED) {
      this.recognizers.push(...DEFAULT_RECOGNIZERS);
    }
  }

  /**
   * Replace the masking policy of a running engine: the categories left
   * readable, the thresholds and the URL allowlist. Every later
   * `sanitize()` uses it; a key the policy leaves out takes its default.
   * The model, backend and recognizers keep their settings.
   */
  updatePolicy(policy: EnginePolicy): void {
    const { disabledCategories, categoryThresholds, threshold, urlAllowlist, ...rest } =
      this.config;
    this.config = { ...rest, ...policy };
    this.derivePolicy();
  }

  /** Recompute what the policy settings decide: the categories left
   * readable, the labels prompted to the model, the URL policy. */
  private derivePolicy(): void {
    const config = this.config;
    this.disabled = new Set(config.disabledCategories ?? DEFAULT_DISABLED_CATEGORIES);
    this.promptLabels = GLINER_LABELS.filter((l) => !this.disabled.has(l));
    this.urlPolicy = config.urlAllowlist === 'none' ? null : urlPolicy(config.urlAllowlist);
  }

  /** Register a custom regex-based recognizer. ML matches take priority on overlap. */
  addRecognizer(recognizer: Recognizer): this {
    this.recognizers.push(recognizer);
    return this;
  }

  /** Singleton-promise init, triggered automatically on the first
   * `sanitize()` call. Internal — users don't need to call this directly. */
  private ensureInit(): Promise<void> {
    if (this.disposed) return Promise.reject(new EngineDisposedError());
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
   * (ONNX model) → recognizer pack on escaped + normalized + base64 →
   * cross-label dedupe + threshold → boundary refine → address-part join →
   * vault sanitize. A text longer than `MAX_INPUT_CHARS` is detected in
   * overlapping windows of at most that size and masked once.
   *
   * A window whose words exceed `max_len=384` subwords is cut, and the
   * next window restarts from the last word the encoder kept, so no word
   * is skipped. Pass `strictLength: true` to throw `TextTooLongError` on
   * any cut instead. */
  async sanitize(
    text: string,
    sessionId?: string,
    options: SanitizeOptions = {},
  ): Promise<SanitizeResult> {
    if (this.disposed) throw new EngineDisposedError();
    const run = this.runSanitize(text, sessionId, options);
    this.inFlight.add(run);
    try {
      return await run;
    } finally {
      this.inFlight.delete(run);
    }
  }

  private async runSanitize(
    text: string,
    sessionId: string | undefined,
    options: SanitizeOptions,
  ): Promise<SanitizeResult> {
    const { tokenizer, backend } = await this.readyModel();
    const escaped = escapePlaceholders(text);
    const detected =
      escaped.length > MAX_INPUT_CHARS
        ? await this.detectInSegments(escaped, tokenizer, backend)
        : await this.detect(escaped, tokenizer, backend);
    const spans = this.finalSpans(escaped, detected.spans);

    const session = sessionId ?? this.vault.createSession();
    logf(LOG_SCOPE, 'sanitize', {
      spans: spans.length,
      session: session.slice(0, 8), // log-only truncation, not the security-critical SESSION_PREFIX_LEN
      ...(options.traceId !== undefined && { traceId: options.traceId }),
    });
    const result = this.vault.sanitize(escaped, spans, session);
    return {
      ...result,
      sanitized: unescapePlaceholders(result.sanitized),
      modelUnscannedWords: detected.unscannedWords,
    };
  }

  /** The model's and the recognizers' spans on `escaped`, at most
   * `MAX_INPUT_CHARS` long, before the final cuts and dedupe. */
  private async detect(
    escaped: string,
    tokenizer: GlinerTokenizer,
    backend: OrtBackend,
  ): Promise<Detected> {
    const surfaces: Surfaces = { escaped, ...normalizeForDetection(escaped) };
    const ml = await this.modelSpans(surfaces, tokenizer, backend);
    const recoSpans = this.recognizerSpans(surfaces, ml.spans);
    return { spans: [...ml.spans, ...recoSpans], unscannedWords: ml.unscannedWords };
  }

  /** `detect` over overlapping windows of a text longer than
   * `MAX_INPUT_CHARS` (`segmentWindows`), each window's spans moved onto
   * the whole text. A value two windows both see comes back twice, or cut
   * short by the first window's end; `finalSpans`' dedupe keeps the whole
   * one, which contains the cut piece. Words the model could not read in
   * an overlap are counted once per window. */
  private async detectInSegments(
    escaped: string,
    tokenizer: GlinerTokenizer,
    backend: OrtBackend,
  ): Promise<Detected> {
    const windows = segmentWindows(escaped, MAX_INPUT_CHARS, SEGMENT_OVERLAP_CHARS);
    const spans: PiiSpan[] = [];
    let unscannedWords = 0;
    for (const { start, end } of windows) {
      const part = await this.detect(escaped.slice(start, end), tokenizer, backend);
      unscannedWords += part.unscannedWords;
      for (const s of part.spans) spans.push({ ...s, start: s.start + start, end: s.end + start });
    }
    logf(LOG_SCOPE, 'segmented', { chunks: windows.length, spans: spans.length });
    return { spans, unscannedWords };
  }

  /** The tokenizer and backend, initialising them on first use. */
  private async readyModel(): Promise<{ tokenizer: GlinerTokenizer; backend: OrtBackend }> {
    await this.ensureInit();
    const tokenizer = this.tokenizer;
    const backend = this.backend;
    if (tokenizer === null || backend === null) {
      throw new ModelNotInitializedError();
    }
    return { tokenizer, backend };
  }

  /** The model's spans on the normalised text, cut by the thresholds,
   * deduplicated, and moved back onto the escaped text, with the count of
   * words the model could not read. */
  private async modelSpans(
    surfaces: Surfaces,
    tokenizer: GlinerTokenizer,
    backend: OrtBackend,
  ): Promise<{ spans: PiiSpan[]; unscannedWords: number }> {
    const { normalized } = surfaces;
    const { spans: decodedRaw, unscannedWords } = await this.detectWithModel(
      normalized,
      tokenizer,
      backend,
    );
    // Resolve `private_geolocation` BEFORE any dedupe: the label is
    // prompted zero-shot and the head applies it to place names and
    // postcodes, which are `private_address`. Relabelling here — rather
    // than after — keeps them masked under the right label and lets them
    // merge with the model's own address candidate for the same region.
    // See `geo-filter.ts`.
    const geoResolved = resolveNonCoordinateGeolocation(decodedRaw, normalized);
    // An IPv4 address belongs to the `core:ipv4` recognizer, whatever label
    // the model gave it (`ip-filter.ts`). A UUID labelled `account_number`
    // is an id software minted, unless a credential key comes right before
    // it (`uuid-filter.ts`). "Claude" alone is the assistant, not a person
    // (`product-names.ts`). All are resolved here too, so no recognizer
    // defers to a span that is then dropped.
    const shaped = dropAssistantNameSpans(
      resolveUuidAccountNumbers(dropModelIpv4Spans(geoResolved, normalized), normalized),
      normalized,
    );
    // Score cut BEFORE any dedupe or recognizer deferral: a span the
    // thresholds will drop must not first absorb, outrank or silence
    // another one. A 0.06 `private_date` guess on a MAC address made
    // `core:mac` defer to it, then fell under the 0.125 date threshold
    // and left the address in the clear.
    const decoded = dedupeOverlappingSpans(this.applyConfiguredThresholds(shaped));
    // Remap span offsets from the normalised text back to the escaped
    // text so they align with the regex pack and vault output.
    return { spans: toEscapedSpans(decoded, surfaces), unscannedWords };
  }

  /** The recognizer pack's spans on the escaped text and on the
   * normalised text (moved back onto the escaped text), plus base64-
   * wrapped PII. */
  private recognizerSpans(surfaces: Surfaces, mlSpans: PiiSpan[]): PiiSpan[] {
    const { escaped, normalized } = surfaces;
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
        : toEscapedSpans(runRecognizers(normalized, this.recognizers, []), surfaces);
    // Base64-wrapped PII: regex can't see `user.123@gmail.com` inside
    // `dXNlci4xMjNAZ21haWwuY29t` until we decode the blob. Run on the
    // escaped surface so spans land on the source base64 substring (gold
    // annotations mark the encoded form). Gated on the same flag as the
    // recognizer pack — `recognizers: 'none'` opts out of BOTH so a
    // caller wiring custom validators is not surprised by base64 hits.
    const base64Spans = this.config.recognizers === 'none' ? [] : detectBase64Pii(escaped);
    return [...recoSpansEscaped, ...recoSpansNorm, ...base64Spans];
  }

  /** The spans to mask: enabled categories over their thresholds, less
   * public digests, log timestamps and allowed URLs, deduplicated across
   * labels, boundary-refined, with split addresses joined. */
  private finalSpans(escaped: string, detected: PiiSpan[]): PiiSpan[] {
    // High-confidence recognizers (≥ 0.9) emit even when overlapping ML
    // output, so dedupe by IoU + score: highest score wins regardless
    // of label. Catches the common case where the GLiNER
    // mislabels a known pattern (e.g., `ghp_…` token classified as
    // `account_number`) — recognizer's `secret` (0.99) overrides ML's
    // `account_number` (0.5–0.7).
    // Drop URLs pointing at well-known public reference / documentation
    // hosts (github.com, anthropic.com, docs.*, …). These leak no PII
    // on their own and otherwise erode the user's token budget when a
    // system prompt cites a project repo or API doc page.
    //
    // Runs BEFORE dedupe, and only for URLs that carry no nested PII.
    // `core:url` is greedy, so `https://github.com/a,AKIA…` is a single
    // span; `removeContainedSpans` inside the dedupe would delete the
    // nested `secret` regardless of score, and dropping the surviving
    // URL span would then emit the key as plaintext. Filtering here,
    // while the nested spans still exist, keeps the check honest — see
    // `dropCleanPublicUrlSpans`.
    // Digests of public artifacts (lockfile `integrity` fields) are not
    // PII; drop pieces of them before dedupe so they cannot absorb or
    // outrank anything else. See `public-digests.ts`.
    // Event timestamps date a log record, not a person. See
    // `machine-timestamps.ts`.
    // Thresholds run before dedupe here too, for the same reason as above.
    const enabled = this.applyConfiguredThresholds(
      detected.filter((s) => !this.disabled.has(s.label)),
    );
    const candidates = dropDatesInsideMachineTimestamps(
      dropSpansInsidePublicDigests(enabled, escaped),
      escaped,
    );
    const allowlisted =
      this.urlPolicy === null ? candidates : dropCleanPublicUrlSpans(candidates, this.urlPolicy);
    // Dedupe can grow a kept span to absorb a duplicate's characters, so
    // `text` is re-derived from the offsets.
    const merged = (
      dedupeOverlappingSpans(allowlisted, DEFAULT_DEDUPE_IOU, { acrossLabels: true }) as PiiSpan[]
    ).map((s) => ({ ...s, text: escaped.slice(s.start, s.end) }));
    const refineOn = this.config.boundaryRefine ?? DEFAULT_BOUNDARY_REFINE;
    // One address the model split into parts is masked as one value, with
    // the separators between the parts (`address-join.ts`).
    return joinAddressParts(escaped, refineOn ? refineSpanBoundaries(escaped, merged) : merged);
  }

  /** The lowest score a model span of each label may have to survive
   * decoding and the post-filter: the decode threshold, raised by the
   * label's post-filter cut. The decoder applies it before NMS, so a span
   * the thresholds would drop never suppresses another. */
  private decodeCut(): (label: string) => number {
    const decode = this.config.threshold ?? DEFAULT_DECODE_THRESHOLD;
    const post = this.config.threshold ?? DEFAULT_POST_FILTER_THRESHOLD;
    const perLabel: Readonly<Partial<Record<string, number>>> =
      this.config.categoryThresholds ?? DEFAULT_CATEGORY_THRESHOLDS;
    return (label) => Math.max(decode, perLabel[label] ?? post);
  }

  /** The configured global and per-label score cuts, or their defaults. */
  private applyConfiguredThresholds<T extends ScoredSpan>(spans: T[]): T[] {
    return applyThresholds(
      spans,
      this.config.threshold ?? DEFAULT_POST_FILTER_THRESHOLD,
      this.config.categoryThresholds ?? DEFAULT_CATEGORY_THRESHOLDS,
    );
  }

  /** Run the model over `normalized` window by window. Windows advance by
   * what the encoder actually kept, so a window cut by the subword budget
   * never hides its tail from the model (see `forEachWindow`). Returned
   * spans carry offsets into `normalized`; `unscannedWords` counts the
   * words too long, alone, for the encoder. */
  private async detectWithModel(
    normalized: string,
    tokenizer: GlinerTokenizer,
    backend: OrtBackend,
  ): Promise<{ spans: DecodedSpan[]; unscannedWords: number }> {
    const minScore = this.decodeCut();
    const maxLen = this.config.maxSequenceLength ?? DEFAULT_MAX_SEQUENCE_LENGTH;
    // One label list for the whole text: `updatePolicy` during the await
    // below must not encode a window with one list and decode it with another.
    const labels = this.promptLabels;
    const decoded: DecodedSpan[] = [];
    const walk = await forEachWindow(normalized, async ({ text: chunk, offset }) => {
      const enc = await tokenizer.encode(chunk, labels);
      if (this.config.strictLength === true && enc.truncated) {
        throw new TextTooLongError(enc.seqLen, maxLen);
      }
      // No word to classify: empty or whitespace-only input, or a single
      // word longer than the subword budget (minified identifiers, data
      // blobs). The GLiNER head cannot take zero words — its LSTM reshape
      // fails — and there is nothing for it to label. The recognizer pack
      // and the base64 detector still scan the full text.
      if (enc.numWords === 0) return 0;
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
      const spans = decodeGlinerLogits(
        out.logits,
        out.textLength,
        out.maxWidth,
        out.numClasses,
        enc.words,
        labels,
        minScore,
      );
      for (const s of spans) {
        decoded.push({
          label: s.label,
          start: s.start + offset,
          end: s.end + offset,
          score: s.score,
        });
      }
      return enc.numWords;
    });
    if (walk.unscannedWords > 0) {
      logf(LOG_SCOPE, 'sanitize.unscanned', { words: walk.unscannedWords, chunks: walk.windows });
    }
    return { spans: decoded, unscannedWords: walk.unscannedWords };
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

  /** Allocate a fresh vault session id. Use when one sanitize+restore
   * span needs to be threaded across multiple `sanitize()` calls
   * (e.g. a gateway sanitizing a whole multi-message request body)
   * before any text has been seen. Pair with `destroySession()`. */
  createSession(): string {
    return this.vault.createSession();
  }

  destroySession(sessionId: string): void {
    this.vault.destroySession(sessionId);
  }

  /** Release the ONNX session and clear the vault. New calls are refused
   * at once; calls already running, and an initialisation in progress,
   * finish first, so no session is released under a running inference
   * or loaded after the release. */
  async dispose(): Promise<void> {
    this.disposed = true;
    await Promise.allSettled([...this.inFlight, this.initPromise ?? Promise.resolve()]);
    if (this.backend !== null) await this.backend.dispose();
    this.backend = null;
    this.tokenizer = null;
    this.vault.clear();
  }

  private async runInit(): Promise<void> {
    const manager = new ModelManager();
    // Resolution order for the model directory:
    //   1. explicit `config.modelDir` (caller intent)
    //   2. `NULLPII_MODEL_DIR` env var (deployment override / air-gap)
    //   3. fall through to HF download into the default cache
    const envModelDir = readEnvVar(NULLPII_MODEL_DIR);
    const variant = this.config.variant ?? DEFAULT_VARIANT;
    const backendName = this.config.backend ?? DEFAULT_BACKEND;
    // A local directory may hold either precision; the backend loads the
    // first candidate present. A download fetches exactly one.
    let onnxFiles = onnxCandidates(variant, backendName);
    let downloaded = false;
    if (this.config.modelDir !== undefined) {
      this.modelDir = this.config.modelDir;
    } else if (envModelDir !== undefined) {
      this.modelDir = envModelDir;
    } else {
      const ensured = await manager.ensure({
        variant,
        backend: backendName,
        ...(this.config.downloadTimeoutMs !== undefined && {
          timeoutMs: this.config.downloadTimeoutMs,
        }),
      });
      this.modelDir = ensured.modelDir;
      onnxFiles = [ensured.onnxFile];
      downloaded = true;
    }

    // Constructor work (no I/O): OrtBackend lazy-loads the ONNX graph
    // on first inference; GlinerTokenizer lazy-loads `tokenizer.json` on
    // first encode.
    this.backend = new OrtBackend(this.modelDir, {
      onnxFiles,
      // On the CPU the precision it is measured in comes first; a model
      // downloaded for CUDA may hold only fp16, which the CPU runs too. A
      // download falls back to the file it verified, never to another one
      // found in the cache.
      cpuFallbackOnnxFiles: downloaded
        ? onnxFiles
        : [...new Set([...onnxCandidates(variant, 'cpu'), ...onnxFiles])],
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
    logf(LOG_SCOPE, 'init', { modelDir: this.modelDir });
  }
}

/** Map the public {@link BackendName} to an ORT execution-provider list.
 * CPU comes last so ORT runs on it the operators the accelerator lacks;
 * an accelerator whose library cannot be loaded is handled by
 * `OrtBackend`, which retries on the CPU alone. */
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

const SECRET_LABEL = 'secret';
const WHITESPACE_TRIM_CHARS = ' \t\n\r';

/** Trim leading/trailing whitespace + common punctuation from each
 * span's edges; drop spans that collapse to empty. Secrets lose only
 * whitespace: punctuation at their edges (`hunter2!`, `"P@ss;`) is part
 * of the credential, and trimming it left those characters unmasked. */
function refineSpanBoundaries(text: string, spans: readonly PiiSpan[]): PiiSpan[] {
  const out: PiiSpan[] = [];
  for (const s of spans) {
    const trim = s.label === SECRET_LABEL ? WHITESPACE_TRIM_CHARS : BOUNDARY_REFINE_TRIM_CHARS;
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
function applyThresholds<T extends ScoredSpan>(
  spans: T[],
  globalThreshold: number,
  perLabel: Partial<Record<string, number>>,
): T[] {
  const noPerLabel = Object.keys(perLabel).length === 0;
  if (globalThreshold <= 0 && noPerLabel) return spans;
  return spans.filter((s) => {
    const t = perLabel[s.label] ?? globalThreshold;
    return s.score >= t;
  });
}
