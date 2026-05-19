// SPDX-License-Identifier: Apache-2.0

import { type NullPii, RestoreStream } from 'nullpii';
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
 *   string is run through `np.restore()` and re-emitted as a single
 *   synthesised `input_json_delta` ahead of the stop frame. Buffering
 *   loses incremental progress for tool inputs but is the only safe
 *   restore strategy: placeholders may straddle shard boundaries AND
 *   sit inside JSON string values where naive substring restore can
 *   re-emit a partial-JSON shard mid-token. Tool inputs are short
 *   relative to text bodies, so the UX cost is negligible.
 * - Anything else (`message_start`, other delta types, …) → passed
 *   through byte-for-byte.
 */
export interface SseRelayCounters {
  replacements: number;
  replacementsByLabel: Record<string, number>;
  unknownPlaceholders: number;
  foreignPlaceholders: number;
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
  /** Called with each fully-formed SSE frame to forward downstream. */
  readonly write: (frame: string) => void;
  /** Optional debugging hook — invoked with each decoded upstream
   * chunk BEFORE frame extraction/restore. Carries placeholders only
   * (Anthropic never sees real PII), safe to dump to stdout. */
  readonly onUpstreamChunk?: (chunk: string) => void;
}

const FRAME_SEPARATOR = '\n\n';

export async function relaySseStream(opts: SseRelayOptions): Promise<SseRelayCounters> {
  const { np, sessionId, upstream, write, onUpstreamChunk } = opts;
  const decoder = new TextDecoder();
  const restorers = new Map<number, RestoreStream>();
  const jsonBuffers = new Map<number, string>();
  const counters: SseRelayCounters = {
    replacements: 0,
    replacementsByLabel: {},
    unknownPlaceholders: 0,
    foreignPlaceholders: 0,
  };

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
    const r = np.restore(buf, sessionId);
    counters.replacements += r.replacements;
    counters.unknownPlaceholders += r.unknownPlaceholders.length;
    counters.foreignPlaceholders += r.foreignPlaceholders.length;
    for (const [lbl, count] of Object.entries(r.replacementsByLabel)) {
      counters.replacementsByLabel[lbl] = (counters.replacementsByLabel[lbl] ?? 0) + (count ?? 0);
    }
    return r.restored;
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
        counters,
      );
      for (const f of out) write(f);
    }
  }

  // Flush any trailing decoder bytes — should be empty for well-formed
  // streams, but exercising the contract is cheap.
  buffer += decoder.decode();
  if (buffer.length > 0) {
    const out = processFrame(
      buffer,
      getRestorer,
      restorers,
      jsonBuffers,
      restoreJsonBuffer,
      counters,
    );
    for (const f of out) write(f);
  }

  // Drain every per-block restorer — synthesise a final text_delta for
  // any open `{{...` tail so the SDK never sees a truncated placeholder.
  for (const [index, rs] of restorers) {
    const result = rs.end();
    counters.replacements += result.replacements;
    counters.unknownPlaceholders += result.unknownPlaceholders.length;
    counters.foreignPlaceholders += result.foreignPlaceholders.length;
    for (const [lbl, count] of Object.entries(result.replacementsByLabel)) {
      counters.replacementsByLabel[lbl] = (counters.replacementsByLabel[lbl] ?? 0) + (count ?? 0);
    }
    if (result.restored.length > 0) {
      write(buildTextDeltaFrame(index, result.restored));
    }
  }

  // Drain JSON buffers whose `content_block_stop` never arrived (mid-
  // stream cancel, upstream truncation). Emit synthesised
  // `input_json_delta` so the SDK still receives the restored payload.
  for (const index of Array.from(jsonBuffers.keys())) {
    const restored = restoreJsonBuffer(index);
    if (restored !== null && restored.length > 0) {
      write(buildInputJsonDeltaFrame(index, restored));
    }
  }

  return counters;
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
  counters: SseRelayCounters,
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
      counters.replacements += result.replacements;
      counters.unknownPlaceholders += result.unknownPlaceholders.length;
      counters.foreignPlaceholders += result.foreignPlaceholders.length;
      for (const [lbl, count] of Object.entries(result.replacementsByLabel)) {
        counters.replacementsByLabel[lbl] = (counters.replacementsByLabel[lbl] ?? 0) + (count ?? 0);
      }
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

  // Everything else — passthrough.
  return [`${frame}${FRAME_SEPARATOR}`];
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
