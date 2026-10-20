// SPDX-License-Identifier: Apache-2.0

import { type NullPii, RestoreStream } from 'nullpii';
import {
  type RestoreAccumulator,
  holdForTool,
  isRecord,
  newRestoreAccumulator,
  restoreJsonText,
  tallyRestore,
  toolMayRestore,
} from './sanitizer.js';
import { ANTHROPIC_SHELL_TOOLS, isShellTool } from './shell-restore.js';
// The gateway hands `NullPii` directly to `RestoreStream` — both
// satisfy the `RestoreCapable` structural type the stream needs. No
// adapter / private-field reach-through required.

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
 * - Partial SSE frame at end of an upstream chunk → kept in `buffer`
 *   until the next chunk delivers the terminating `\n\n`.
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
 * - A `Bash` tool call (named in its `content_block_start`) → its
 *   `command` gets the shell-aware restore (`shell-restore.ts`): a
 *   placeholder is put back only when its value is safe in the quoting
 *   around it, and is otherwise left literal and counted.
 * - Anything else (`message_start`, other delta types, …) → passed
 *   through byte-for-byte.
 */
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
   * chunk BEFORE frame extraction/restore. Carries placeholders only
   * (Anthropic never sees real PII), safe to dump to stdout. */
  readonly onUpstreamChunk?: (chunk: string) => void;
  /** Tools whose arguments get real values back. Default:
   * `DEFAULT_RESTORE_TOOLS`, the tools that run on this machine. */
  readonly restoreTools?: ReadonlySet<string>;
}

/** How a tool call's streamed input is restored at its block's stop. */
type ToolRestore = 'shell' | 'hold';

const FRAME_SEPARATOR = '\n\n';

export async function relaySseStream(opts: SseRelayOptions): Promise<SseRelayCounters> {
  const { np, sessionId, upstream, write, onUpstreamChunk, restoreTools } = opts;
  const decoder = new TextDecoder();
  const restorers = new Map<number, RestoreStream>();
  const jsonBuffers = new Map<number, string>();
  /** Content blocks whose tool input is not restored as plain JSON: a
   * shell tool's, or a tool's outside `restoreTools`. */
  const toolBlocks = new Map<number, ToolRestore>();
  const acc = newRestoreAccumulator(restoreTools);

  function getRestorer(index: number): RestoreStream {
    let rs = restorers.get(index);
    if (rs === undefined) {
      rs = new RestoreStream(np, sessionId);
      restorers.set(index, rs);
    }
    return rs;
  }

  function restoreJsonBuffer(index: number): string | null {
    const buf = jsonBuffers.get(index);
    if (buf === undefined) return null;
    jsonBuffers.delete(index);
    // Empty buffer = upstream stop with no shards. Restoring '' is a
    // no-op but the explicit short-circuit makes the intent obvious.
    if (buf.length === 0) return '';
    const mode = toolBlocks.get(index);
    toolBlocks.delete(index);
    if (mode === 'hold') return holdForTool(buf, acc);
    return restoreJsonText(np, buf, sessionId, acc, mode === 'shell');
  }

  let buffer = '';
  for await (const chunk of upstream) {
    const decoded = decoder.decode(chunk, { stream: true });
    if (onUpstreamChunk !== undefined && decoded.length > 0) onUpstreamChunk(decoded);
    buffer += decoded;
    while (true) {
      const sep = buffer.indexOf(FRAME_SEPARATOR);
      if (sep === -1) break;
      const frame = buffer.slice(0, sep);
      buffer = buffer.slice(sep + FRAME_SEPARATOR.length);
      const out = processFrame(
        frame,
        getRestorer,
        restorers,
        jsonBuffers,
        restoreJsonBuffer,
        acc,
        toolBlocks,
      );
      for (const f of out) await write(f);
    }
  }

  // Flush any trailing decoder bytes. Only forward if the residue
  // actually parses into an SSE frame — a half-frame (e.g.
  // `event: ping\n` with no `data:` line) returned with a synthesised
  // `\n\n` terminator would confuse strict SDKs.
  buffer += decoder.decode();
  if (buffer.length > 0 && parseFrame(buffer) !== null) {
    const out = processFrame(
      buffer,
      getRestorer,
      restorers,
      jsonBuffers,
      restoreJsonBuffer,
      acc,
      toolBlocks,
    );
    for (const f of out) await write(f);
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
): string[] {
  if (frame.length === 0) return [];
  const parsed = parseFrame(frame);
  if (parsed === null) return [`${frame}${FRAME_SEPARATOR}`];

  const data = parsed.data;
  if (data?.type === 'content_block_delta' && isTextDelta(data)) {
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

  if (data?.type === 'content_block_delta' && isInputJsonDelta(data)) {
    // Buffer the partial-JSON shard. Restore happens at
    // `content_block_stop` (or end-of-stream drain) to keep placeholder
    // tokens intact across shard boundaries.
    const idx = data.index;
    jsonBuffers.set(idx, (jsonBuffers.get(idx) ?? '') + data.delta.partial_json);
    return [];
  }

  if (data?.type === 'content_block_stop' && typeof (data as ContentBlockStop).index === 'number') {
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

  if (data?.type === 'content_block_start') noteToolBlock(data, toolBlocks, acc);
  // Everything else — passthrough.
  return [`${frame}${FRAME_SEPARATOR}`];
}

/** Remember how each tool call's input is restored at
 * `content_block_stop`: kept masked for a tool outside `restoreTools`,
 * shell-aware for a shell tool. */
function noteToolBlock(
  data: Record<string, unknown>,
  toolBlocks: Map<number, ToolRestore>,
  acc: RestoreAccumulator,
): void {
  const block = data.content_block;
  if (typeof data.index !== 'number' || !isRecord(block) || block.type !== 'tool_use') return;
  if (!toolMayRestore(block.name, acc)) toolBlocks.set(data.index, 'hold');
  else if (isShellTool(block.name, ANTHROPIC_SHELL_TOOLS)) toolBlocks.set(data.index, 'shell');
}

interface ParsedFrame {
  event: string | null;
  data: Record<string, unknown> | null;
}

function parseFrame(frame: string): ParsedFrame | null {
  let event: string | null = null;
  let dataRaw = '';
  for (const line of frame.split('\n')) {
    if (line.startsWith('event:')) {
      event = line.slice('event:'.length).trim();
    } else if (line.startsWith('data:')) {
      dataRaw += line.slice('data:'.length).trim();
    }
  }
  if (dataRaw.length === 0) return null;
  try {
    return { event, data: JSON.parse(dataRaw) as Record<string, unknown> };
  } catch {
    // Deliberate swallow: a non-JSON `data:` payload is a normal SSE
    // occurrence (heartbeat comments, provider-injected envelopes that
    // lose framing on chunk boundaries). Returning null signals the
    // caller to forward the raw frame verbatim — the safe default.
    return null;
  }
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

function serialiseFrame(event: string | null, data: Record<string, unknown>): string {
  const prefix = event !== null ? `event: ${event}\n` : '';
  return `${prefix}data: ${JSON.stringify(data)}${FRAME_SEPARATOR}`;
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
