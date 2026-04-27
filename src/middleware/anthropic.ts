// SPDX-License-Identifier: Apache-2.0
import type { NullPiiConfig } from '../types/index.js';
import { ConversationPool, type MiddlewareSession, newSession } from './shared.js';

const PLACEHOLDER_OPEN = '[[';

export interface WithNullPiiOptions extends NullPiiConfig {
  /** Stable identifier for a multi-turn conversation. When provided, the
   * vault is shared across `messages.create` calls with the same key, so
   * a follow-up that quotes back an earlier placeholder restores correctly. */
  readonly conversationKey?: string;
}

/**
 * Wrap an Anthropic SDK client so every outgoing prompt is sanitized and
 * every response has placeholders restored — transparently, with the same
 * TypeScript surface as the original client.
 *
 * For multi-turn:
 * ```ts
 * const safe = withNullPii(client, { conversationKey: 'thread-42' });
 * await safe.messages.create({ ... });   // user mentions John
 * await safe.messages.create({ ... });   // follow-up — placeholder still resolves
 * ```
 *
 * For single-turn (default), the vault session is destroyed in `finally`
 * after each call to avoid leaks.
 */
export function withNullPii<T extends AnthropicLike>(
  client: T,
  options: WithNullPiiOptions = {},
): T {
  const pool: ConversationPool | undefined =
    options.conversationKey !== undefined ? new ConversationPool(options) : undefined;
  return new Proxy(client, {
    get(target, prop, receiver) {
      if (prop === 'messages') return wrapMessages(target.messages, options, pool);
      return Reflect.get(target, prop, receiver);
    },
  });
}

interface AnthropicLike {
  readonly messages: AnthropicMessages;
}
interface AnthropicMessages {
  create(params: AnthropicCreateParams): Promise<AnthropicResponse>;
  stream?(params: AnthropicCreateParams): AsyncIterable<AnthropicStreamEvent>;
}
interface AnthropicCreateParams {
  readonly messages: ReadonlyArray<{ readonly role: string; readonly content: AnthropicContent }>;
  readonly stream?: boolean;
  readonly [k: string]: unknown;
}
type AnthropicContent =
  | string
  | ReadonlyArray<{ readonly type: string; readonly text?: string; readonly [k: string]: unknown }>;
interface AnthropicResponse {
  readonly content: ReadonlyArray<{ readonly type: string; readonly text?: string }>;
  readonly [k: string]: unknown;
}
interface AnthropicStreamEvent {
  readonly type: string;
  readonly delta?: { readonly type?: string; readonly text?: string };
  readonly [k: string]: unknown;
}

function wrapMessages(
  messages: AnthropicMessages,
  options: WithNullPiiOptions,
  pool: ConversationPool | undefined,
): AnthropicMessages {
  return new Proxy(messages, {
    get(target, prop, receiver) {
      if (prop === 'create') {
        return async (params: AnthropicCreateParams) =>
          createWithVault(target, params, options, pool);
      }
      if (prop === 'stream') {
        return (params: AnthropicCreateParams) => streamWithVault(target, params, options, pool);
      }
      return Reflect.get(target, prop, receiver);
    },
  });
}

function openSession(
  options: WithNullPiiOptions,
  pool: ConversationPool | undefined,
): MiddlewareSession {
  if (pool !== undefined && options.conversationKey !== undefined) {
    return pool.open(options.conversationKey);
  }
  return newSession(options);
}

function commitSession(
  session: MiddlewareSession,
  options: WithNullPiiOptions,
  pool: ConversationPool | undefined,
): void {
  if (pool !== undefined && options.conversationKey !== undefined) {
    pool.commit(options.conversationKey, session);
  }
  session.destroy();
}

async function createWithVault(
  messages: AnthropicMessages,
  params: AnthropicCreateParams,
  options: WithNullPiiOptions,
  pool: ConversationPool | undefined,
): Promise<AnthropicResponse> {
  const session = openSession(options, pool);
  try {
    const sanitized = await sanitizeParams(params, session);
    const response = await messages.create(sanitized);
    return restoreResponse(response, session);
  } finally {
    commitSession(session, options, pool);
  }
}

function streamWithVault(
  messages: AnthropicMessages,
  params: AnthropicCreateParams,
  options: WithNullPiiOptions,
  pool: ConversationPool | undefined,
): AsyncIterable<AnthropicStreamEvent> {
  if (messages.stream === undefined) {
    throw new Error('withNullPii: client does not expose `messages.stream()`');
  }
  return makeStream(messages, params, options, pool);
}

async function* makeStream(
  messages: AnthropicMessages,
  params: AnthropicCreateParams,
  options: WithNullPiiOptions,
  pool: ConversationPool | undefined,
): AsyncIterable<AnthropicStreamEvent> {
  const session = openSession(options, pool);
  let buffer = '';
  try {
    const sanitized = await sanitizeParams(params, session);
    const upstream = messages.stream?.(sanitized);
    if (upstream === undefined) throw new Error('withNullPii: stream returned undefined');
    for await (const ev of upstream) {
      const text = ev.delta?.text;
      if (typeof text !== 'string' || ev.delta?.type !== 'text_delta') {
        yield ev;
        continue;
      }
      buffer += text;
      const { emit, keep } = splitAtLastSafe(buffer);
      buffer = keep;
      if (emit.length > 0) {
        yield { ...ev, delta: { ...ev.delta, text: session.restore(emit) } };
      }
    }
    if (buffer.length > 0) {
      yield {
        type: 'content_block_delta',
        delta: { type: 'text_delta', text: session.restore(buffer) },
      };
    }
  } finally {
    commitSession(session, options, pool);
  }
}

/** Split `buf` into (emit, keep) where `keep` is everything from the last
 * partial `[[NULLPII:...` onward (no terminating `]]` yet) so we never emit
 * a placeholder cut in half by a chunk boundary. */
function splitAtLastSafe(buf: string): { emit: string; keep: string } {
  const lastOpen = buf.lastIndexOf(PLACEHOLDER_OPEN);
  if (lastOpen === -1) return { emit: buf, keep: '' };
  const tail = buf.slice(lastOpen);
  if (tail.includes(']]')) return { emit: buf, keep: '' };
  return { emit: buf.slice(0, lastOpen), keep: tail };
}

async function sanitizeParams(
  params: AnthropicCreateParams,
  session: MiddlewareSession,
): Promise<AnthropicCreateParams> {
  const newMessages = await Promise.all(
    params.messages.map(async (msg) => ({
      ...msg,
      content: await sanitizeContent(msg.content, session),
    })),
  );
  return { ...params, messages: newMessages };
}

async function sanitizeContent(
  content: AnthropicContent,
  session: MiddlewareSession,
): Promise<AnthropicContent> {
  if (typeof content === 'string') return session.sanitize(content);
  return Promise.all(
    content.map(async (block) => {
      if (block.type !== 'text' || typeof block.text !== 'string') return block;
      return { ...block, text: await session.sanitize(block.text) };
    }),
  );
}

function restoreResponse(
  response: AnthropicResponse,
  session: MiddlewareSession,
): AnthropicResponse {
  const newContent = response.content.map((block) => {
    if (block.type !== 'text' || typeof block.text !== 'string') return block;
    return { ...block, text: session.restore(block.text) };
  });
  return { ...response, content: newContent };
}
