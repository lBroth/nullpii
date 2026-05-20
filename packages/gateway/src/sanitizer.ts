// SPDX-License-Identifier: Apache-2.0

import { LLM_PRESERVATION_HINT, type NullPii } from 'nullpii';
import type {
  AnthropicContentBlock,
  AnthropicMessage,
  AnthropicRequest,
  AnthropicResponse,
  AnthropicSystem,
  AnthropicToolDef,
} from './types.js';

/**
 * Walks an Anthropic request body in place, sanitizing every `text`
 * field through the supplied `NullPii` engine and binding all
 * placeholders to a single freshly-minted vault session.
 *
 * Mutating the body in place keeps unknown fields (provider-specific
 * extensions, future params) untouched — the gateway is forward-compat
 * by default.
 */
export interface SanitizedRequest {
  /** The mutated request body — same reference as the input. */
  readonly body: AnthropicRequest;
  /** Session id bound to every placeholder in `body`. Restore the
   *  upstream response against this exact id. */
  readonly sessionId: string;
  /** Total number of spans that the engine replaced across system +
   * messages on the way out. Surfaced so callers (route handlers /
   * pretty-printers) can show humans what got captured before the
   * request hit the upstream LLM. */
  readonly captured: number;
  /** Per-label counts; same labels the engine itself uses. */
  readonly capturedByLabel: Readonly<Record<string, number>>;
}

interface CaptureAccumulator {
  count: number;
  byLabel: Record<string, number>;
}

export async function sanitizeRequest(
  np: NullPii,
  body: AnthropicRequest,
): Promise<SanitizedRequest> {
  const sessionId = np.createSession();
  const acc: CaptureAccumulator = { count: 0, byLabel: {} };
  if (body.system !== undefined) {
    body.system = await sanitizeSystem(np, body.system, sessionId, acc);
  }
  body.messages = await Promise.all(
    body.messages.map((m) => sanitizeMessage(np, m, sessionId, acc)),
  );
  if (Array.isArray(body.tools)) {
    body.tools = await Promise.all(body.tools.map((t) => sanitizeToolDef(np, t, sessionId, acc)));
  }
  // Append the preservation hint AFTER sanitization (and only when we
  // actually replaced something) so the assistant treats placeholders
  // literally and doesn't "tidy" them into realistic-looking values
  // inside tool_use inputs.
  //
  // Why append (not prepend) + why gated on `captured > 0`:
  //
  // 1. Anthropic's `prompt-caching-*` beta keys the prompt cache off
  //    the PREFIX of the system message. Prepending invalidates the
  //    cache for every Claude Code / SDK turn and triggers an
  //    anti-abuse rate-limit branded "Server is temporarily limiting
  //    requests (not your usage limit)" on subscription / OAuth auth.
  //    Appending leaves the original prefix untouched so the cache
  //    still hits the unchanged Claude Code preamble.
  // 2. When no PII is in the body the hint adds nothing and just risks
  //    cache invalidation — skip it entirely.
  //
  // Opt-out: NULLPII_DISABLE_HINT=1 (debugging hook).
  if (acc.count > 0 && process.env.NULLPII_DISABLE_HINT !== '1') {
    injectPreservationHint(body);
  }
  return { body, sessionId, captured: acc.count, capturedByLabel: acc.byLabel };
}

function injectPreservationHint(body: AnthropicRequest): void {
  if (body.system === undefined) {
    body.system = LLM_PRESERVATION_HINT;
    return;
  }
  if (typeof body.system === 'string') {
    body.system = `${body.system}\n\n${LLM_PRESERVATION_HINT}`;
    return;
  }
  body.system = [...body.system, { type: 'text', text: LLM_PRESERVATION_HINT }];
}

function bump(acc: CaptureAccumulator, r: { spans: ReadonlyArray<{ label: string }> }): void {
  acc.count += r.spans.length;
  for (const span of r.spans) {
    acc.byLabel[span.label] = (acc.byLabel[span.label] ?? 0) + 1;
  }
}

async function sanitizeSystem(
  np: NullPii,
  system: AnthropicSystem,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<AnthropicSystem> {
  if (typeof system === 'string') {
    const r = await np.sanitize(system, sessionId);
    bump(acc, r);
    return r.sanitized;
  }
  return Promise.all(system.map((b) => sanitizeBlock(np, b, sessionId, acc)));
}

async function sanitizeMessage(
  np: NullPii,
  msg: AnthropicMessage,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<AnthropicMessage> {
  if (typeof msg.content === 'string') {
    const r = await np.sanitize(msg.content, sessionId);
    bump(acc, r);
    return { ...msg, content: r.sanitized };
  }
  return {
    ...msg,
    content: await Promise.all(msg.content.map((b) => sanitizeBlock(np, b, sessionId, acc))),
  };
}

async function sanitizeToolDef(
  np: NullPii,
  tool: AnthropicToolDef,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<AnthropicToolDef> {
  if (typeof tool.description !== 'string') return tool;
  const r = await np.sanitize(tool.description, sessionId);
  bump(acc, r);
  return { ...tool, description: r.sanitized };
}

async function sanitizeBlock(
  np: NullPii,
  block: AnthropicContentBlock,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<AnthropicContentBlock> {
  if (block.type === 'text' && typeof block.text === 'string') {
    const r = await np.sanitize(block.text, sessionId);
    bump(acc, r);
    return { ...block, text: r.sanitized };
  }
  if (block.type === 'tool_use') {
    // Walk `input` (arbitrary JSON tree) and sanitize every string leaf.
    // Required when the client posts an assistant turn from history that
    // already contained a tool call — without this, raw PII inside the
    // tool's arguments ships unmodified to the upstream.
    if (block.input !== undefined) {
      const next = await sanitizeJsonValue(np, block.input, sessionId, acc);
      return { ...block, input: next };
    }
    return block;
  }
  if (block.type === 'tool_result') {
    const content = block.content;
    if (typeof content === 'string') {
      const r = await np.sanitize(content, sessionId);
      bump(acc, r);
      return { ...block, content: r.sanitized };
    }
    if (Array.isArray(content)) {
      const next = await Promise.all(content.map((b) => sanitizeBlock(np, b, sessionId, acc)));
      return { ...block, content: next };
    }
  }
  return block;
}

/** Recursively walk a JSON value (the result of `JSON.parse` on tool
 * input), sanitising every string leaf. Numbers / booleans / null pass
 * through. Arrays + plain objects recurse. Cycles are not possible on
 * JSON.parse output, so no visited-set is needed. */
async function sanitizeJsonValue(
  np: NullPii,
  value: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<unknown> {
  if (typeof value === 'string') {
    const r = await np.sanitize(value, sessionId);
    bump(acc, r);
    return r.sanitized;
  }
  if (Array.isArray(value)) {
    return Promise.all(value.map((v) => sanitizeJsonValue(np, v, sessionId, acc)));
  }
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = await sanitizeJsonValue(np, v, sessionId, acc);
    }
    return out;
  }
  return value;
}

/**
 * Walks an Anthropic response body in place, restoring every `text`
 * field against the supplied vault session.
 *
 * Returns the (mutated) response plus the aggregated restore-counter
 * triple — caller logs the per-label counts. PII values themselves are
 * never returned in the counter (counts only).
 */
export interface RestoredResponse {
  readonly body: AnthropicResponse;
  readonly replacements: number;
  readonly replacementsByLabel: Readonly<Partial<Record<string, number>>>;
  readonly unknownPlaceholders: number;
  readonly foreignPlaceholders: number;
}

// rothunter:ignore-duplicate-interface
// reason: short-named closure-scope accumulator for restoreResponse; sse-relay's public SseRelayCounters uses long names that match the pino log-field contract — merging would force either a public API rename or verbose names in this 60-line internal struct.
interface RestoreAccumulator {
  replacements: number;
  byLabel: Record<string, number>;
  unknown: number;
  foreign: number;
}

export function restoreResponse(
  np: NullPii,
  body: AnthropicResponse,
  sessionId: string,
): RestoredResponse {
  const acc: RestoreAccumulator = { replacements: 0, byLabel: {}, unknown: 0, foreign: 0 };
  body.content = body.content.map((block) => {
    if (block.type === 'text' && typeof block.text === 'string') {
      return { ...block, text: restoreString(np, block.text, sessionId, acc) };
    }
    if (block.type === 'tool_use' && block.input !== undefined) {
      // Mirror SSE path's `restoreJsonBuffer`: walk the tool input tree
      // and restore string leaves. Without this, non-streaming
      // tool-calling workflows leak `{{PII_*}}` placeholders verbatim
      // to the client.
      return { ...block, input: restoreJsonValue(np, block.input, sessionId, acc) };
    }
    return block;
  });
  return {
    body,
    replacements: acc.replacements,
    replacementsByLabel: acc.byLabel,
    unknownPlaceholders: acc.unknown,
    foreignPlaceholders: acc.foreign,
  };
}

function restoreString(
  np: NullPii,
  text: string,
  sessionId: string,
  acc: RestoreAccumulator,
): string {
  const r = np.restore(text, sessionId);
  acc.replacements += r.replacements;
  for (const [lbl, count] of Object.entries(r.replacementsByLabel)) {
    acc.byLabel[lbl] = (acc.byLabel[lbl] ?? 0) + (count ?? 0);
  }
  acc.unknown += r.unknownPlaceholders.length;
  acc.foreign += r.foreignPlaceholders.length;
  return r.restored;
}

function restoreJsonValue(
  np: NullPii,
  value: unknown,
  sessionId: string,
  acc: RestoreAccumulator,
): unknown {
  if (typeof value === 'string') return restoreString(np, value, sessionId, acc);
  if (Array.isArray(value)) return value.map((v) => restoreJsonValue(np, v, sessionId, acc));
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value as Record<string, unknown>)) {
      out[k] = restoreJsonValue(np, v, sessionId, acc);
    }
    return out;
  }
  return value;
}
