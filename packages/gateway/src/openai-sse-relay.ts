// SPDX-License-Identifier: Apache-2.0

import { type NullPii, RestoreStream } from 'nullpii';
import { restoreCustomInput, restoreFunctionArguments } from './openai-sanitizer.js';
import type {
  ChatChunkChoice,
  ChatCompletionChunk,
  ChatDelta,
  ChatFunctionCall,
  ChatToolCallDelta,
} from './openai-types.js';
import {
  type RestoreAccumulator,
  holdForTool,
  isRecord,
  newRestoreAccumulator,
  parseJson,
  tallyRestore,
} from './sanitizer.js';
import { FRAME_SEPARATOR, SseFrameSplitter, parseSseFields, serialiseFrame } from './sse-frames.js';
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
 *   re-escaped instead of breaking the JSON. A custom tool call's
 *   `custom.input` shards are buffered the same way and restored as text.
 *   Either gets real values only for a tool in `restoreTools`, by the
 *   same helpers as the JSON restore (`restoreFunctionArguments`,
 *   `restoreCustomInput`); a call whose name never arrived keeps its
 *   placeholders. The first delta of each call is still forwarded at once,
 *   so its `id` and name arrive on time. A delta with no numeric `index`
 *   is forwarded as it is.
 * - Flush points: the chunk that carries a choice's `finish_reason` also
 *   carries the text still held and the restored arguments; `[DONE]` (or
 *   the end of the stream, when the upstream was cut off) is preceded by
 *   one synthesised chunk for every choice that never finished.
 * - Chunks the relay does not change, `[DONE]`, comments and error events
 *   are forwarded unchanged but for their line ends, which become LF. A chunk whose payload is held back is
 *   still forwarded with that field emptied, so per-chunk metadata (ids,
 *   `usage`, provider extensions) is never lost.
 */

const DONE_SENTINEL = '[DONE]';

/** Delta fields that stream free text. */
const TEXT_FIELDS = ['content', 'refusal'] as const;
type TextField = (typeof TEXT_FIELDS)[number];

/** A streamed tool call is a function call or a custom (free-form) one;
 * the field of its payload that streams text, per kind. */
const CALL_TEXT_FIELD = { function: 'arguments', custom: 'input' } as const;
type CallKind = keyof typeof CALL_TEXT_FIELD;

/** What one choice holds of a streamed tool call: its kind, the tool's
 * name from the call's first delta, and the text shards so far
 * (`function.arguments` or `custom.input`), `null` before the first. */
interface HeldCall {
  readonly kind: CallKind;
  /** `null` when the stream sent two different names (`nextName`). */
  name: string | null | undefined;
  text: string | null;
}

/** The tool name after a delta that carries `fragment`. A name sent once,
 * or repeated unchanged, is kept; a different one makes the name
 * ambiguous (`null`, which no tool list holds): clients differ on whether
 * name fragments are joined or replaced, so the relay picks neither. */
function nextName(current: string | null | undefined, fragment: string): string | null {
  return current === undefined || current === fragment ? fragment : null;
}

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
  const relay = new ChatRelay(opts.np, opts.sessionId, opts.restoreTools);
  const decoder = new TextDecoder();
  const splitter = new SseFrameSplitter();
  for await (const chunk of upstream) {
    const decoded = decoder.decode(chunk, { stream: true });
    if (onUpstreamChunk !== undefined && decoded.length > 0) onUpstreamChunk(decoded);
    for (const frame of splitter.push(decoded)) {
      for (const out of relay.processFrame(frame)) await write(out);
    }
  }
  // A last frame without its blank line is still relayed when it is
  // whole (`[DONE]` or a complete JSON object). A half frame is dropped,
  // as in the Anthropic relay: strict SDKs choke on a truncated payload.
  for (const frame of splitter.push(decoder.decode()).concat(splitter.end())) {
    if (isWholeFrame(frame)) {
      for (const out of relay.processFrame(frame)) await write(out);
    }
  }
  for (const out of relay.flushOpenChoices()) await write(out);
  return relay.counters();
}

/** Per-stream state: one `ChoiceRestorer` per open choice. */
class ChatRelay {
  private readonly choices = new Map<number, ChoiceRestorer>();
  private readonly acc: RestoreAccumulator;
  private envelope: Record<string, unknown> = {};
  /** A frame's `data` was neither a JSON object nor `[DONE]`, or a chunk
   * had a shape clients may read otherwise than the relay
   * (`misreadable`): from then on, which call a shard belongs to is no
   * longer certain, so every tool call keeps its placeholders. */
  private readonly state = { degraded: false };
  /** Choices that sent their `finish_reason`. */
  private readonly finished = new Set<number>();

  constructor(
    private readonly np: NullPii,
    private readonly sessionId: string,
    restoreTools?: ReadonlySet<string>,
  ) {
    this.acc = newRestoreAccumulator(restoreTools);
  }

  /** Frames to forward for one upstream frame, each ending with a blank line. */
  processFrame(frame: string): string[] {
    if (frame.length === 0) return [];
    const passthrough = `${frame}${FRAME_SEPARATOR}`;
    const { event, data } = parseSseFields(frame);
    if (data === DONE_SENTINEL) return [...this.flushOpenChoices(), passthrough];
    const value = data === null ? undefined : parseJson(data)?.value;
    if (data !== null && (!isRecord(value) || misreadable(value, this.finished))) {
      this.state.degraded = true;
    }
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
      unsafeShellPlaceholders: this.acc.unsafeShell,
      heldForToolPlaceholders: this.acc.heldForTool,
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
    this.finished.add(choice.index);
    return changed;
  }

  private restorerFor(index: number): ChoiceRestorer {
    let restorer = this.choices.get(index);
    if (restorer === undefined) {
      restorer = new ChoiceRestorer(this.np, this.sessionId, this.acc, this.state);
      this.choices.set(index, restorer);
    }
    return restorer;
  }
}

/** What one choice holds back: a text restorer per field, and the
 * argument or input shards of each tool call (plus the deprecated
 * function call). */
class ChoiceRestorer {
  private readonly text = new Map<TextField, RestoreStream>();
  /** Per tool-call index. */
  private readonly calls = new Map<number, HeldCall>();
  private functionArgs: string | null = null;
  private functionName: string | null | undefined;

  constructor(
    private readonly np: NullPii,
    private readonly sessionId: string,
    private readonly acc: RestoreAccumulator,
    private readonly state: { readonly degraded: boolean },
  ) {}

  /** Restore `delta` in place: text as far as it is safe, argument shards
   * taken out and held. True when `delta` changed. */
  rewrite(delta: ChatDelta): boolean {
    let changed = false;
    for (const field of TEXT_FIELDS) changed = this.pushText(delta, field) || changed;
    const calls = Array.isArray(delta.tool_calls) ? delta.tool_calls : [];
    for (const call of calls) changed = this.holdToolCall(call) || changed;
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

  /** Take a call's text shard out of the delta and hold it; true when
   * one was taken. */
  private holdToolCall(call: ChatToolCallDelta): boolean {
    if (!isRecord(call) || typeof call.index !== 'number') return false;
    if (isRecord(call.function)) return this.holdShard(call.index, 'function', call.function);
    if (isRecord(call.custom)) return this.holdShard(call.index, 'custom', call.custom);
    return false;
  }

  /** Note the tool's name when `payload` carries it, and move its text
   * shard into the held state of call `index`, leaving the field empty in
   * the forwarded delta. True when a shard was taken. */
  private holdShard(index: number, kind: CallKind, payload: Record<string, unknown>): boolean {
    let held = this.calls.get(index);
    if (held === undefined) {
      held = { kind, name: undefined, text: null };
      this.calls.set(index, held);
    }
    if (typeof payload.name === 'string') held.name = nextName(held.name, payload.name);
    const field = CALL_TEXT_FIELD[kind];
    const shard = payload[field];
    if (typeof shard !== 'string' || shard.length === 0) return false;
    held.text = (held.text ?? '') + shard;
    payload[field] = '';
    return true;
  }

  private holdFunctionArgs(fn: ChatFunctionCall): boolean {
    if (typeof fn.name === 'string') this.functionName = nextName(this.functionName, fn.name);
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
    let added = false;
    for (const [index, held] of this.calls) {
      if (held.text === null) continue;
      setCallText(delta, index, held.kind, this.restoreCall(held, held.text));
      added = true;
    }
    this.calls.clear();
    if (this.functionArgs !== null) {
      const args = this.state.degraded
        ? holdForTool(this.functionArgs, this.acc)
        : restoreFunctionArguments(
            this.np,
            this.functionName,
            this.functionArgs,
            this.sessionId,
            this.acc,
          );
      delta.function_call = { ...delta.function_call, arguments: args };
      this.functionArgs = null;
      added = true;
    }
    return added;
  }

  /** Restore one call's assembled text with the helper the JSON restore
   * uses for that kind of call. */
  private restoreCall(held: HeldCall, text: string): string {
    if (this.state.degraded) return holdForTool(text, this.acc);
    const restore = held.kind === 'function' ? restoreFunctionArguments : restoreCustomInput;
    return restore(this.np, held.name, text, this.sessionId, this.acc);
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

/** Put a call's restored text into `delta` (`function.arguments` or
 * `custom.input`): onto its entry when this delta already has one, else as
 * a new continuation entry. */
function setCallText(delta: ChatDelta, index: number, kind: CallKind, text: string): void {
  const calls = Array.isArray(delta.tool_calls) ? delta.tool_calls : [];
  const existing = calls.find((c) => isRecord(c) && c.index === index);
  const entry: ChatToolCallDelta = existing ?? { index };
  if (kind === 'function') entry.function = { ...entry.function, arguments: text };
  else entry.custom = { ...entry.custom, input: text };
  if (existing === undefined) calls.push(entry);
  delta.tool_calls = calls;
}

/** True when a trailing frame (no blank line after it) is complete. */
function isWholeFrame(frame: string): boolean {
  const { data } = parseSseFields(frame);
  return data !== null && (data === DONE_SENTINEL || isRecord(parseJson(data)?.value));
}

/** True when a chunk has a shape the relay skips or reads one way while a
 * client may read it another: `choices` that is not an array, a choice or
 * tool call that is not an object or has no numeric `index`, a `delta`,
 * `function`, `custom` or `function_call` that is not an object, a tool
 * name that is not a string, or a tool call for a choice that already
 * sent its `finish_reason` (the relay starts that choice afresh; a client
 * appends to the finished call). */
function misreadable(chunk: Record<string, unknown>, finished: ReadonlySet<number>): boolean {
  if (chunk.choices === undefined) return false;
  if (!Array.isArray(chunk.choices)) return true;
  return chunk.choices.some((choice) => misreadableChoice(choice, finished));
}

function misreadableChoice(choice: unknown, finished: ReadonlySet<number>): boolean {
  if (!isRecord(choice) || typeof choice.index !== 'number') return true;
  const delta = choice.delta;
  if (delta === undefined || delta === null) return false;
  if (!isRecord(delta)) return true;
  const calls = delta.tool_calls;
  const hasCalls = calls !== undefined && calls !== null;
  if (hasCalls && (!Array.isArray(calls) || calls.some(misreadableCall))) return true;
  const fn = delta.function_call;
  const hasFn = fn !== undefined && fn !== null;
  if (hasFn && misreadablePayload(fn)) return true;
  return (hasCalls || hasFn) && finished.has(choice.index);
}

function misreadableCall(call: unknown): boolean {
  if (!isRecord(call) || typeof call.index !== 'number') return true;
  return [call.function, call.custom].some(
    (p) => p !== undefined && p !== null && misreadablePayload(p),
  );
}

function misreadablePayload(payload: unknown): boolean {
  if (!isRecord(payload)) return true;
  return payload.name !== undefined && payload.name !== null && typeof payload.name !== 'string';
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
