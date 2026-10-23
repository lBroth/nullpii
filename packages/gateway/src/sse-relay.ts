// SPDX-License-Identifier: Apache-2.0

import { type NullPii, RestoreStream } from 'nullpii';
import {
  type RestoreAccumulator,
  holdForTool,
  isRecord,
  newRestoreAccumulator,
  restoreJsonText,
  tallyRestore,
  toolCallMayRestore,
} from './sanitizer.js';
import { type ShellTool, shellToolOf } from './shell-restore.js';
import { FRAME_SEPARATOR, SseFrameSplitter, parseSseFields, serialiseFrame } from './sse-frames.js';
// The gateway hands `NullPii` directly to `RestoreStream` — both
// satisfy the `RestoreCapable` structural type the stream needs. No
// adapter / private-field reach-through required.

/** Restore counts of one relayed stream: counts and labels, never values. */
export interface SseRelayCounters {
  replacements: number;
  replacementsByLabel: Record<string, number>;
  unknownPlaceholders: number;
  foreignPlaceholders: number;
  /** Placeholders left literal in a shell command (unsafe there). */
  unsafeShellPlaceholders: number;
  /** Placeholders kept in the input of a tool outside `restoreTools`. */
  heldForToolPlaceholders: number;
}

interface ContentBlockDelta {
  type: 'content_block_delta';
  index: number;
  delta: { type: string; text?: string; partial_json?: string; [k: string]: unknown };
  [k: string]: unknown;
}

interface ContentBlockStop {
  type: 'content_block_stop';
  index: number;
  [k: string]: unknown;
}

export interface SseRelayOptions {
  readonly np: NullPii;
  readonly sessionId: string;
  /** Async iterable of upstream body chunks. Pass `upstream.body` from
   * the `Response` directly — Node's `fetch` returns a web-style
   * `ReadableStream<Uint8Array>` which is async-iterable. */
  readonly upstream: AsyncIterable<Uint8Array>;
  /** Called with each fully-formed SSE frame to forward downstream. A
   * returned promise is awaited before the relay reads more from the
   * upstream, so a slow client applies backpressure (`writeFrame`). */
  readonly write: (frame: string) => void | Promise<void>;
  /** Optional debugging hook — invoked with each decoded upstream
   * chunk BEFORE frame extraction/restore (`NULLPII_LOG_TRAFFIC=wire`).
   * Placeholders stay masked in it, but it is not free of personal data:
   * it holds whatever the upstream wrote, including anything nullpii did
   * not mask in the request. */
  readonly onUpstreamChunk?: (chunk: string) => void;
  /** Tools whose arguments get real values back. Default:
   * `DEFAULT_RESTORE_TOOLS`, the tools that run on this machine. */
  readonly restoreTools?: ReadonlySet<string>;
}

/** How a tool call's streamed input is restored at its block's stop: as
 * that shell tool's input (`shell`), or as plain JSON. A block with no
 * entry keeps its placeholders. */
interface ToolRestore {
  readonly shell: ShellTool | undefined;
}

/** State of one stream beyond its blocks. */
interface StreamState {
  /** A frame's `data` was not JSON: from then on, the relay can no longer
   * be sure which block a tool input belongs to, so every tool input
   * keeps its placeholders. */
  degraded: boolean;
}

/**
 * Anthropic SSE streaming relay. The Messages API streams a response
 * as a sequence of `event: <name>\ndata: <json>\n\n` frames. Only
 * `content_block_delta` frames carrying a `text_delta` need text
 * mutation; everything else (`message_start`, `content_block_start`,
 * `content_block_stop`, `message_delta`, `message_stop`, `ping`,
 * `error`, anything we don't recognise) is forwarded byte-for-byte.
 *
 * Per-block `RestoreStream` (one per `index`): the upstream emits
 * text in small deltas (typically token-sized), and a placeholder can
 * straddle delta boundaries. `RestoreStream` holds the open `{{…`
 * prefix until the closing `}}` arrives, then flushes the restored
 * text. The mutated event re-uses the original `index` so downstream
 * SDK reassembly is unchanged.
 *
 * Edge cases handled:
 * - Multi-byte UTF-8 split across upstream chunks → `TextDecoder` with
 *   `stream:true` buffers the partial codepoint.
 * - Frames are read as the SSE specification defines them
 *   (`sse-frames.ts`): CRLF, LF or CR line ends, comments, several
 *   `data:` lines; a partial frame waits for the rest of it.
 * - A frame whose `data` is not JSON is forwarded as it came, and from
 *   then on every tool input keeps its placeholders.
 * - Block ends with text still buffered in `RestoreStream` → flush
 *   via `end()` and synthesise a final `text_delta` before
 *   `content_block_stop` so the SDK never sees a truncated reply.
 * - `input_json_delta` for tool calls → partial-JSON shards are buffered
 *   per block index until `content_block_stop`, then the assembled JSON
 *   is parsed, its string leaves are restored, and it is re-serialized
 *   and re-emitted as a single synthesised `input_json_delta` ahead of
 *   the stop frame. Restoring the leaves (not the raw text) re-escapes a
 *   value holding a quote, a backslash or a newline, which pasted raw
 *   would break the JSON; input that does not parse is restored as text.
 *   Buffering loses incremental progress for tool inputs but is the only
 *   safe restore strategy: placeholders may straddle shard boundaries AND
 *   sit inside JSON string values where naive substring restore can
 *   re-emit a partial-JSON shard mid-token. Tool inputs are short
 *   relative to text bodies, so the UX cost is negligible.
 * - Which tool input gets real values back is decided from the block's
 *   `content_block_start`, as `restoreResponse` decides for a JSON reply:
 *   only a client `tool_use` of a tool in `restoreTools`. A server or MCP
 *   tool call (`server_tool_use`, `mcp_tool_use`), a tool outside the
 *   list, and input whose `content_block_start` was never seen keep their
 *   placeholders, counted as held (fail closed).
 * - A `Bash` tool call (named in its `content_block_start`) → its
 *   `command` gets the shell-aware restore (`shell-restore.ts`): a
 *   placeholder is put back only when its value is safe in the quoting
 *   around it, and is otherwise left literal and counted.
 * - Anything else (`message_start`, other delta types, …) → passed
 *   through byte-for-byte.
 */
export async function relaySseStream(opts: SseRelayOptions): Promise<SseRelayCounters> {
  const { np, sessionId, upstream, write, onUpstreamChunk, restoreTools } = opts;
  const decoder = new TextDecoder();
  const restorers = new Map<number, RestoreStream>();
  const jsonBuffers = new Map<number, string>();
  /** Content blocks whose tool input may get real values back, and how.
   * Input of any other block keeps its placeholders. */
  const toolBlocks = new Map<number, ToolRestore>();
  const acc = newRestoreAccumulator(restoreTools);
  const state: StreamState = { degraded: false };

  function getRestorer(index: number): RestoreStream {
    let rs = restorers.get(index);
    if (rs === undefined) {
      rs = new RestoreStream(np, sessionId);
      restorers.set(index, rs);
    }
    return rs;
  }

  function restoreJsonBuffer(index: number): string | null {
    const mode = toolBlocks.get(index);
    toolBlocks.delete(index);
    const buf = jsonBuffers.get(index);
    if (buf === undefined) return null;
    jsonBuffers.delete(index);
    // Empty buffer = upstream stop with no shards. Restoring '' is a
    // no-op but the explicit short-circuit makes the intent obvious.
    if (buf.length === 0) return '';
    if (mode === undefined) return holdForTool(buf, acc);
    return restoreJsonText(np, buf, sessionId, acc, mode.shell);
  }

  const relay = (frame: string): string[] =>
    processFrame(
      frame,
      getRestorer,
      restorers,
      jsonBuffers,
      restoreJsonBuffer,
      acc,
      toolBlocks,
      state,
    );
  const splitter = new SseFrameSplitter();
  for await (const chunk of upstream) {
    const decoded = decoder.decode(chunk, { stream: true });
    if (onUpstreamChunk !== undefined && decoded.length > 0) onUpstreamChunk(decoded);
    for (const frame of splitter.push(decoded)) {
      for (const f of relay(frame)) await write(f);
    }
  }

  // Flush any trailing decoder bytes. Only forward if the residue
  // actually parses into an SSE frame — a half-frame (e.g.
  // `event: ping\n` with no `data:` line) returned with a synthesised
  // `\n\n` terminator would confuse strict SDKs.
  const rest = splitter.push(decoder.decode()).concat(splitter.end());
  for (const frame of rest) {
    if (frame.length > 0 && parseFrame(frame).kind === 'json') {
      for (const f of relay(frame)) await write(f);
    }
  }

  // Drain every per-block restorer — synthesise a final text_delta for
  // any open `{{...` tail so the SDK never sees a truncated placeholder.
  for (const [index, rs] of restorers) {
    const result = rs.end();
    tallyRestore(acc, result);
    if (result.restored.length > 0) {
      await write(buildTextDeltaFrame(index, result.restored));
    }
  }

  // Drain JSON buffers whose `content_block_stop` never arrived (mid-
  // stream cancel, upstream truncation). Emit synthesised
  // `input_json_delta` so the SDK still receives the restored payload.
  for (const index of Array.from(jsonBuffers.keys())) {
    const restored = restoreJsonBuffer(index);
    if (restored !== null && restored.length > 0) {
      await write(buildInputJsonDeltaFrame(index, restored));
    }
  }

  return {
    replacements: acc.replacements,
    replacementsByLabel: acc.byLabel,
    unknownPlaceholders: acc.unknown,
    foreignPlaceholders: acc.foreign,
    unsafeShellPlaceholders: acc.unsafeShell,
    heldForToolPlaceholders: acc.heldForTool,
  };
}

/**
 * Parse one SSE frame, mutate `content_block_delta.text_delta` events,
 * pass everything else through. Returns the frame text(s) to forward
 * downstream (each ends with `\n\n`).
 */
function processFrame(
  frame: string,
  getRestorer: (index: number) => RestoreStream,
  restorers: Map<number, RestoreStream>,
  jsonBuffers: Map<number, string>,
  restoreJsonBuffer: (index: number) => string | null,
  acc: RestoreAccumulator,
  toolBlocks: Map<number, ToolRestore>,
  state: StreamState,
): string[] {
  if (frame.length === 0) return [];
  const parsed = parseFrame(frame);
  if (parsed.kind === 'invalid') {
    state.degraded = true;
    toolBlocks.clear();
  }
  if (parsed.kind !== 'json') return [`${frame}${FRAME_SEPARATOR}`];

  const data = parsed.data;
  if (data.type === 'content_block_delta' && isTextDelta(data)) {
    const rs = getRestorer(data.index);
    const incoming = data.delta.text ?? '';
    const restoredHead = rs.push(incoming);
    if (restoredHead.length === 0) {
      // Whole delta got buffered (placeholder mid-flight). Don't emit
      // an empty `text_delta`; downstream SDKs accumulate by string
      // length and zero-width events are wasted bytes.
      return [];
    }
    const out: ContentBlockDelta = {
      type: 'content_block_delta',
      index: data.index,
      delta: { ...data.delta, text: restoredHead },
    };
    return [serialiseFrame(parsed.event, out)];
  }

  if (data.type === 'content_block_delta' && isInputJsonDelta(data)) {
    // Buffer the partial-JSON shard. Restore happens at
    // `content_block_stop` (or end-of-stream drain) to keep placeholder
    // tokens intact across shard boundaries.
    const idx = data.index;
    jsonBuffers.set(idx, (jsonBuffers.get(idx) ?? '') + data.delta.partial_json);
    return [];
  }

  if (data.type === 'content_block_stop' && typeof (data as ContentBlockStop).index === 'number') {
    const index = (data as ContentBlockStop).index;
    const rs = restorers.get(index);
    const out: string[] = [];
    if (rs !== undefined) {
      const result = rs.end();
      tallyRestore(acc, result);
      restorers.delete(index);
      if (result.restored.length > 0) {
        out.push(buildTextDeltaFrame(index, result.restored));
      }
    }
    const restoredJson = restoreJsonBuffer(index);
    if (restoredJson !== null && restoredJson.length > 0) {
      out.push(buildInputJsonDeltaFrame(index, restoredJson));
    }
    // Forward the stop frame itself unchanged.
    out.push(`${frame}${FRAME_SEPARATOR}`);
    return out;
  }

  if (data.type === 'content_block_start') {
    if (!state.degraded) noteToolBlock(data, toolBlocks, acc);
    // Re-serialised, so the client reads the block the relay judged.
    return [serialiseFrame(parsed.event, data)];
  }
  // Everything else — passthrough.
  return [`${frame}${FRAME_SEPARATOR}`];
}

/** Remember, at a block's `content_block_start`, whether its tool input
 * gets real values back at `content_block_stop` (`toolCallMayRestore`),
 * and whether with the shell rule. Any other block, server and MCP tool
 * calls included, gets no entry and keeps its placeholders. */
function noteToolBlock(
  data: Record<string, unknown>,
  toolBlocks: Map<number, ToolRestore>,
  acc: RestoreAccumulator,
): void {
  const block = data.content_block;
  if (typeof data.index !== 'number' || !isRecord(block)) return;
  toolBlocks.delete(data.index);
  if (!toolCallMayRestore(block, acc)) return;
  toolBlocks.set(data.index, { shell: shellToolOf(block.name) });
}

/** A frame with no `data` (a comment, a keep-alive), one whose `data` is
 * not a JSON object, or a JSON event. */
type ParsedFrame =
  | { kind: 'none' }
  | { kind: 'invalid' }
  | { kind: 'json'; event: string | null; data: Record<string, unknown> };

function parseFrame(frame: string): ParsedFrame {
  const { event, data } = parseSseFields(frame);
  if (data === null) return { kind: 'none' };
  let value: unknown;
  try {
    value = JSON.parse(data);
  } catch {
    // Not swallowed: the caller forwards the frame as it came and stops
    // restoring tool input for the rest of the stream.
    return { kind: 'invalid' };
  }
  return isRecord(value) ? { kind: 'json', event, data: value } : { kind: 'invalid' };
}

function isTextDelta(data: Record<string, unknown>): data is ContentBlockDelta {
  if (data.type !== 'content_block_delta') return false;
  const d = data as { index?: unknown; delta?: { type?: unknown; text?: unknown } };
  return (
    typeof d.index === 'number' &&
    d.delta !== undefined &&
    d.delta.type === 'text_delta' &&
    typeof d.delta.text === 'string'
  );
}

function isInputJsonDelta(data: Record<string, unknown>): data is ContentBlockDelta {
  if (data.type !== 'content_block_delta') return false;
  const d = data as { index?: unknown; delta?: { type?: unknown; partial_json?: unknown } };
  return (
    typeof d.index === 'number' &&
    d.delta !== undefined &&
    d.delta.type === 'input_json_delta' &&
    typeof d.delta.partial_json === 'string'
  );
}

function buildTextDeltaFrame(index: number, text: string): string {
  const data: ContentBlockDelta = {
    type: 'content_block_delta',
    index,
    delta: { type: 'text_delta', text },
  };
  return serialiseFrame('content_block_delta', data);
}

function buildInputJsonDeltaFrame(index: number, partialJson: string): string {
  const data: ContentBlockDelta = {
    type: 'content_block_delta',
    index,
    delta: { type: 'input_json_delta', partial_json: partialJson },
  };
  return serialiseFrame('content_block_delta', data);
}
