// SPDX-License-Identifier: Apache-2.0

import type { OrtBackend } from './backend/backend.js';
import { forEachWindow } from './chunking.js';
import { TextTooLongError } from './errors.js';
import { decodeGlinerLogits } from './gliner-decoder.js';
import { buildSpanCandidates } from './gliner-spans.js';
import { DEFAULT_MAX_SPAN_WIDTH, type GlinerTokenizer } from './gliner-tokenizer.js';
import type { Interval } from './iou.js';

/** A model span with offsets into the text the model ran on. */
export interface DecodedSpan {
  readonly label: string;
  readonly start: number;
  readonly end: number;
  readonly score: number;
}

/** The lowest score a candidate of a label must reach to be decoded. */
export type LabelCut = (label: string) => number;

/** One pass of the model over a text: the labels it is prompted with, and
 * the cuts each window's scores are decoded with. */
export interface ModelPass {
  readonly labels: readonly string[];
  /** One decode of every window per cut, on the same scores. */
  readonly cuts: readonly LabelCut[];
  readonly tokenizer: GlinerTokenizer;
  readonly backend: OrtBackend;
  /** The encoder's budget, when a window the budget cuts must throw
   * `TextTooLongError` (`strictLength`) instead of moving on. */
  readonly strictMaxLength?: number;
}

/** What a pass found: the spans of each cut, in the order of `cuts`, and
 * the char ranges of the words too long, alone, for any window. */
export interface PassResult {
  readonly spans: readonly DecodedSpan[][];
  readonly unscanned: readonly Interval[];
  readonly windows: number;
}

/**
 * Run the model over `text` window by window. Windows advance by what the
 * encoder actually kept, so a window cut by the subword budget never hides
 * its tail from the model (see `forEachWindow`). Spans carry offsets into
 * `text`.
 *
 * @param text - the text to read, at most `MAX_INPUT_CHARS` long
 * @param pass - the prompt, the cuts, the encoder and the backend
 */
export async function runModelPass(text: string, pass: ModelPass): Promise<PassResult> {
  const spans: DecodedSpan[][] = pass.cuts.map(() => []);
  const walk = await forEachWindow(text, async ({ text: chunk, offset }) => {
    const enc = await pass.tokenizer.encode(chunk, pass.labels);
    if (pass.strictMaxLength !== undefined && enc.truncated) {
      throw new TextTooLongError(enc.seqLen, pass.strictMaxLength);
    }
    // No word to classify: empty or whitespace-only input, or a single
    // word longer than the subword budget (minified identifiers, data
    // blobs). The GLiNER head cannot take zero words — its LSTM reshape
    // fails — and there is nothing for it to label. The recognizer pack
    // and the base64 detector still scan the full text.
    if (enc.numWords === 0) return 0;
    const cand = buildSpanCandidates(enc.numWords, DEFAULT_MAX_SPAN_WIDTH);
    const out = await pass.backend.infer({
      inputIds: enc.inputIds,
      attentionMask: enc.attentionMask,
      wordsMask: enc.wordsMask,
      textLength: enc.numWords,
      spanIdx: cand.spanIdx,
      spanMask: cand.spanMask,
      numSpans: cand.numSpans,
    });
    pass.cuts.forEach((cut, i) => {
      const decoded = decodeGlinerLogits(
        out.logits,
        out.textLength,
        out.maxWidth,
        out.numClasses,
        enc.words,
        pass.labels,
        cut,
      );
      for (const s of decoded) {
        spans[i]?.push({
          label: s.label,
          start: s.start + offset,
          end: s.end + offset,
          score: s.score,
        });
      }
    });
    return enc.numWords;
  });
  return { spans, unscanned: walk.unscanned, windows: walk.windows };
}
