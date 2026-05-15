// SPDX-License-Identifier: Apache-2.0

/**
 * Minimal Anthropic Messages API wire types. We model only the fields
 * the gateway needs to walk for sanitize/restore — anything else is
 * passed through untouched. See https://docs.anthropic.com/en/api/messages.
 */

/** A single content block on a `message` or `assistant` response. */
export type AnthropicContentBlock =
  | { type: 'text'; text: string; [k: string]: unknown }
  | { type: 'image'; [k: string]: unknown }
  | { type: 'tool_use'; [k: string]: unknown }
  | { type: 'tool_result'; content?: string | AnthropicContentBlock[]; [k: string]: unknown }
  | { type: string; [k: string]: unknown };

/** A `messages` array entry on the request. `content` may be a plain
 * string (shorthand for one text block) or an array of blocks. */
export interface AnthropicMessage {
  role: 'user' | 'assistant';
  content: string | AnthropicContentBlock[];
  [k: string]: unknown;
}

/** `system` may be string or an array of text blocks. */
export type AnthropicSystem = string | AnthropicContentBlock[];

/** POST /v1/messages request body (subset). */
export interface AnthropicRequest {
  model: string;
  messages: AnthropicMessage[];
  system?: AnthropicSystem;
  [k: string]: unknown;
}

/** POST /v1/messages response body (subset). */
export interface AnthropicResponse {
  id: string;
  type: 'message';
  role: 'assistant';
  content: AnthropicContentBlock[];
  [k: string]: unknown;
}
