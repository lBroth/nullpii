// SPDX-License-Identifier: Apache-2.0

import { type NullPii, RestoreStream } from 'nullpii';
import { isRecord, parseJson, restoreArguments } from './openai-sanitizer.js';
import type {
  ChatChunkChoice,
  ChatCompletionChunk,
  ChatDelta,
  ChatFunctionCall,
  ChatToolCallDelta,
} from './openai-types.js';
import { type RestoreAccumulator, tallyRestore } from './sanitizer.js';
import type { SseRelayCounters, SseRelayOptions } from './sse-relay.js';

/**
 * OpenAI Chat Completions SSE relay. The upstream streams one
 * `data: <chat.completion.chunk>` frame per delta and ends with
 * `data: [DONE]`. Placeholders are restored per choice `index`:
 *
 * - `delta.content` and `delta.refusal` go through one `RestoreStream`
 *   per choice and field, as Anthropic `text_delta`s do in `sse-relay.ts`:
 *   text is forwarded as soon as it cannot be the start of a placeholder,
 *   and an open `{{…` is held until its `}}` arrives.
 * - `delta.tool_calls[].function.arguments` shards (and the deprecated
 *   `delta.function_call.arguments`) are buffered per choice and tool-call
 *   index, as Anthropic `input_json_delta`s are, and forwarded once, when
 *   the choice finishes. The assembled string is parsed and only its
 *   string leaves are restored, so a value holding a quote or a newline is
 *   re-escaped instead of breaking the JSON. The first delta of each call
 *   is still forwarded at once, so its `id` and `function.name` arrive on
 *   time. A delta with no numeric `index` is forwarded as it is.
 * - Flush points: the chunk that carries a choice's `finish_reason` also
 *   carries the text still held and the restored arguments; `[DONE]` (or
 *   the end of the stream, when the upstream was cut off) is preceded by
 *   one synthesised chunk for every choice that never finished.
 * - Chunks the relay does not change, `[DONE]`, comments and error events
 *   are forwarded byte for byte. A chunk whose payload is held back is
 *   still forwarded with that field emptied, so per-chunk metadata (ids,
 *   `usage`, provider extensions) is never lost.
 */

const FRAME_SEPARATOR = '\n\n';
const EVENT_PREFIX = 'event:';
const DATA_PREFIX = 'data:';
const DONE_SENTINEL = '[DONE]';

/** Delta fields that stream free text. */
const TEXT_FIELDS = ['content', 'refusal'] as const;
type TextField = (typeof TEXT_FIELDS)[number];

/** Top-level fields copied from the last upstream chunk onto a chunk the
 * relay synthesises. Anything else (usage, provider extensions) belongs
 * to the chunk it came with. */
const ENVELOPE_FIELDS = [
  'id',
  'object',
  'created',
  'model',
  'system_fingerprint',
  'service_tier',
] as const;

/**
 * Relay an upstream Chat Completions SSE stream to `write`, restoring
 * placeholders on the way. Resolves with the restore counts (never
 * values) once the upstream ends.
 */
export async function relayChatSseStream(opts: SseRelayOptions): Promise<SseRelayCounters> {
  const { upstream, write, onUpstreamChunk } = opts;
  const relay = new ChatRelay(opts.np, opts.sessionId);
  const decoder = new TextDecoder();
  let buffer = '';
  for await (const chunk of upstream) {
    const decoded = decoder.decode(chunk, { stream: true });
    if (onUpstreamChunk !== undefined && decoded.length > 0) onUpstreamChunk(decoded);
    buffer += decoded;
    let sep = buffer.indexOf(FRAME_SEPARATOR);
    while (sep !== -1) {
      for (const out of relay.processFrame(buffer.slice(0, sep))) write(out);
      buffer = buffer.slice(sep + FRAME_SEPARATOR.length);
      sep = buffer.indexOf(FRAME_SEPARATOR);
    }
  }
  // A last frame without its blank line is still relayed when it is
  // whole (`[DONE]` or a complete JSON payload). A half frame is dropped,
  // as in the Anthropic relay: strict SDKs choke on a truncated payload.
  buffer += decoder.decode();
  if (isWholeFrame(buffer)) {
    for (const out of relay.processFrame(buffer)) write(out);
  }
  for (const out of relay.flushOpenChoices()) write(out);
  return relay.counters();
}

/** Per-stream state: one `ChoiceRestorer` per open choice. */
class ChatRelay {
  private readonly choices = new Map<number, ChoiceRestorer>();
  private readonly acc: RestoreAccumulator = {
    replacements: 0,
    byLabel: {},
    unknown: 0,
    foreign: 0,
  };
  private envelope: Record<string, unknown> = {};

  constructor(
    private readonly np: NullPii,
    private readonly sessionId: string,
  ) {}

  /** Frames to forward for one upstream frame, each ending with a blank line. */
  processFrame(frame: string): string[] {
    if (frame.length === 0) return [];
    const passthrough = `${frame}${FRAME_SEPARATOR}`;
    const { event, data } = splitFrame(frame);
    if (data === DONE_SENTINEL) return [...this.flushOpenChoices(), passthrough];
    const chunk = data === null ? null : parseChunk(data);
    if (chunk === null) return [passthrough];
    this.envelope = pickEnvelope(chunk);
    let changed = false;
    for (const choice of chunk.choices) changed = this.rewriteChoice(choice) || changed;
    return [changed ? serialiseFrame(event, chunk) : passthrough];
  }

  /** One synthesised chunk carrying what is still held for choices that
   * never sent a `finish_reason`; nothing when nothing is held. */
  flushOpenChoices(): string[] {
    const choices: ChatChunkChoice[] = [];
    for (const [index, restorer] of this.choices) {
      const delta: ChatDelta = {};
      if (restorer.flushInto(delta)) choices.push({ index, delta, finish_reason: null });
    }
    this.choices.clear();
    if (choices.length === 0) return [];
    return [serialiseFrame(null, { ...this.envelope, choices })];
  }

  counters(): SseRelayCounters {
    return {
      replacements: this.acc.replacements,
      replacementsByLabel: this.acc.byLabel,
      unknownPlaceholders: this.acc.unknown,
      foreignPlaceholders: this.acc.foreign,
    };
  }

  /** Restore one choice in place; true when it changed. */
  private rewriteChoice(choice: ChatChunkChoice): boolean {
    if (!isRecord(choice) || typeof choice.index !== 'number') return false;
    const restorer = this.restorerFor(choice.index);
    let changed = isRecord(choice.delta) && restorer.rewrite(choice.delta);
    if (choice.finish_reason === null || choice.finish_reason === undefined) return changed;
    // The choice is done: what it still holds goes out with this chunk.
    const delta: ChatDelta = isRecord(choice.delta) ? choice.delta : {};
    if (restorer.flushInto(delta)) {
      choice.delta = delta;
      changed = true;
    }
    this.choices.delete(choice.index);
    return changed;
  }

  private restorerFor(index: number): ChoiceRestorer {
    let restorer = this.choices.get(index);
    if (restorer === undefined) {
      restorer = new ChoiceRestorer(this.np, this.sessionId, this.acc);
      this.choices.set(index, restorer);
    }
    return restorer;
  }
}

/** What one choice holds back: a text restorer per field, and the
 * argument shards of each tool call (plus the deprecated function call). */
class ChoiceRestorer {
  private readonly text = new Map<TextField, RestoreStream>();
  private readonly toolArgs = new Map<number, string>();
  private functionArgs: string | null = null;

  constructor(
    private readonly np: NullPii,
    private readonly sessionId: string,
    private readonly acc: RestoreAccumulator,
  ) {}

  /** Restore `delta` in place: text as far as it is safe, argument shards
   * taken out and held. True when `delta` changed. */
  rewrite(delta: ChatDelta): boolean {
    let changed = false;
    for (const field of TEXT_FIELDS) changed = this.pushText(delta, field) || changed;
    const calls = Array.isArray(delta.tool_calls) ? delta.tool_calls : [];
    for (const call of calls) changed = this.holdToolArgs(call) || changed;
    if (isRecord(delta.function_call)) {
      changed = this.holdFunctionArgs(delta.function_call) || changed;
    }
    return changed;
  }

  /** Move everything still held into `delta`: the tail of each text field,
   * and every call's arguments, restored. True when anything was added. */
  flushInto(delta: ChatDelta): boolean {
    const addedText = this.flushText(delta);
    const addedArgs = this.flushArgs(delta);
    return addedText || addedArgs;
  }

  private pushText(delta: ChatDelta, field: TextField): boolean {
    const value = delta[field];
    if (typeof value !== 'string' || value.length === 0) return false;
    const head = this.textStream(field).push(value);
    if (head === value) return false;
    delta[field] = head;
    return true;
  }

  private holdToolArgs(call: ChatToolCallDelta): boolean {
    if (!isRecord(call) || typeof call.index !== 'number') return false;
    const fn = call.function;
    if (!isRecord(fn) || typeof fn.arguments !== 'string' || fn.arguments.length === 0) {
      return false;
    }
    this.toolArgs.set(call.index, (this.toolArgs.get(call.index) ?? '') + fn.arguments);
    fn.arguments = '';
    return true;
  }

  private holdFunctionArgs(fn: ChatFunctionCall): boolean {
    if (typeof fn.arguments !== 'string' || fn.arguments.length === 0) return false;
    this.functionArgs = (this.functionArgs ?? '') + fn.arguments;
    fn.arguments = '';
    return true;
  }

  private flushText(delta: ChatDelta): boolean {
    let added = false;
    for (const [field, stream] of this.text) {
      // `end()` returns the counts for the whole stream plus the held tail.
      const result = stream.end();
      tallyRestore(this.acc, result);
      if (result.restored.length === 0) continue;
      const head = delta[field];
      delta[field] = `${typeof head === 'string' ? head : ''}${result.restored}`;
      added = true;
    }
    this.text.clear();
    return added;
  }

  private flushArgs(delta: ChatDelta): boolean {
    const added = this.toolArgs.size > 0 || this.functionArgs !== null;
    for (const [index, args] of this.toolArgs) {
      setToolArgs(delta, index, restoreArguments(this.np, args, this.sessionId, this.acc));
    }
    this.toolArgs.clear();
    if (this.functionArgs !== null) {
      const args = restoreArguments(this.np, this.functionArgs, this.sessionId, this.acc);
      delta.function_call = { ...delta.function_call, arguments: args };
      this.functionArgs = null;
    }
    return added;
  }

  private textStream(field: TextField): RestoreStream {
    let stream = this.text.get(field);
    if (stream === undefined) {
      stream = new RestoreStream(this.np, this.sessionId);
      this.text.set(field, stream);
    }
    return stream;
  }
}

/** Put a call's restored arguments into `delta`: onto its entry when this
 * delta already has one, else as a new continuation entry. */
function setToolArgs(delta: ChatDelta, index: number, args: string): void {
  const calls = Array.isArray(delta.tool_calls) ? delta.tool_calls : [];
  const existing = calls.find((c) => isRecord(c) && c.index === index);
  if (existing !== undefined) {
    existing.function = { ...existing.function, arguments: args };
  } else {
    calls.push({ index, function: { arguments: args } });
  }
  delta.tool_calls = calls;
}

/** True when a trailing frame (no blank line after it) is complete. */
function isWholeFrame(frame: string): boolean {
  const { data } = splitFrame(frame);
  return data !== null && (data === DONE_SENTINEL || parseJson(data) !== undefined);
}

/** The `event:` name and the joined `data:` payload of one SSE frame. */
function splitFrame(frame: string): { event: string | null; data: string | null } {
  let event: string | null = null;
  const data: string[] = [];
  for (const line of frame.split('\n')) {
    if (line.startsWith(EVENT_PREFIX)) event = line.slice(EVENT_PREFIX.length).trim();
    else if (line.startsWith(DATA_PREFIX)) data.push(line.slice(DATA_PREFIX.length).trim());
  }
  return { event, data: data.length > 0 ? data.join('\n') : null };
}

/** The chunk in a `data:` payload, or null for anything that is not a
 * JSON object with a `choices` array (an error event, a provider's
 * keep-alive): those are forwarded as they are. */
function parseChunk(data: string): ChatCompletionChunk | null {
  const parsed = parseJson(data);
  if (parsed === undefined || !isRecord(parsed.value)) return null;
  return Array.isArray(parsed.value.choices) ? (parsed.value as ChatCompletionChunk) : null;
}

function pickEnvelope(chunk: ChatCompletionChunk): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const key of ENVELOPE_FIELDS) {
    if (chunk[key] !== undefined) out[key] = chunk[key];
  }
  return out;
}

function serialiseFrame(event: string | null, data: Record<string, unknown>): string {
  const prefix = event !== null ? `event: ${event}\n` : '';
  return `${prefix}data: ${JSON.stringify(data)}${FRAME_SEPARATOR}`;
}
