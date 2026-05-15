// SPDX-License-Identifier: Apache-2.0

import type { NullPii } from 'nullpii';
import type {
  AnthropicContentBlock,
  AnthropicMessage,
  AnthropicRequest,
  AnthropicResponse,
  AnthropicSystem,
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
}

export async function sanitizeRequest(
  np: NullPii,
  body: AnthropicRequest,
): Promise<SanitizedRequest> {
  const sessionId = np.createSession();
  if (body.system !== undefined) {
    body.system = await sanitizeSystem(np, body.system, sessionId);
  }
  body.messages = await Promise.all(body.messages.map((m) => sanitizeMessage(np, m, sessionId)));
  return { body, sessionId };
}

async function sanitizeSystem(
  np: NullPii,
  system: AnthropicSystem,
  sessionId: string,
): Promise<AnthropicSystem> {
  if (typeof system === 'string') {
    const r = await np.sanitize(system, sessionId);
    return r.sanitized;
  }
  return Promise.all(system.map((b) => sanitizeBlock(np, b, sessionId)));
}

async function sanitizeMessage(
  np: NullPii,
  msg: AnthropicMessage,
  sessionId: string,
): Promise<AnthropicMessage> {
  const next: AnthropicMessage =
    typeof msg.content === 'string'
      ? { ...msg, content: (await np.sanitize(msg.content, sessionId)).sanitized }
      : {
          ...msg,
          content: await Promise.all(msg.content.map((b) => sanitizeBlock(np, b, sessionId))),
        };
  return next;
}

async function sanitizeBlock(
  np: NullPii,
  block: AnthropicContentBlock,
  sessionId: string,
): Promise<AnthropicContentBlock> {
  if (block.type === 'text' && typeof block.text === 'string') {
    const r = await np.sanitize(block.text, sessionId);
    return { ...block, text: r.sanitized };
  }
  if (block.type === 'tool_result') {
    const content = block.content;
    if (typeof content === 'string') {
      const r = await np.sanitize(content, sessionId);
      return { ...block, content: r.sanitized };
    }
    if (Array.isArray(content)) {
      const next = await Promise.all(content.map((b) => sanitizeBlock(np, b, sessionId)));
      return { ...block, content: next };
    }
  }
  return block;
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

export function restoreResponse(
  np: NullPii,
  body: AnthropicResponse,
  sessionId: string,
): RestoredResponse {
  let replacements = 0;
  const byLabel: Record<string, number> = {};
  let unknown = 0;
  let foreign = 0;
  body.content = body.content.map((block) => {
    if (block.type === 'text' && typeof block.text === 'string') {
      const r = np.restore(block.text, sessionId);
      replacements += r.replacements;
      for (const [lbl, count] of Object.entries(r.replacementsByLabel)) {
        byLabel[lbl] = (byLabel[lbl] ?? 0) + (count ?? 0);
      }
      unknown += r.unknownPlaceholders.length;
      foreign += r.foreignPlaceholders.length;
      return { ...block, text: r.restored };
    }
    return block;
  });
  return {
    body,
    replacements,
    replacementsByLabel: byLabel,
    unknownPlaceholders: unknown,
    foreignPlaceholders: foreign,
  };
}
