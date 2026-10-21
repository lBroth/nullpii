// SPDX-License-Identifier: Apache-2.0

/**
 * Minimal OpenAI Chat Completions wire types. As in `types.ts` for the
 * Anthropic Messages API, only the fields the gateway walks for
 * sanitize/restore are modelled — anything else rides along in the
 * index signatures and is forwarded untouched.
 * See https://platform.openai.com/docs/api-reference/chat.
 */

/** One entry of a message `content` array: `text`, `refusal`, or media
 * (`image_url`, `input_audio`, `file`). */
export interface ChatContentPart {
  type: string;
  [k: string]: unknown;
}

/** Message `content`: a string, or an array of parts. */
export type ChatContent = string | ChatContentPart[];

/** A function call: `arguments` is a JSON document encoded as a string. */
export interface ChatFunctionCall {
  name?: string;
  arguments?: string;
  [k: string]: unknown;
}

/** A free-form (`type: 'custom'`) tool call: `input` is plain text. */
export interface ChatCustomCall {
  name?: string;
  input?: string;
  [k: string]: unknown;
}

/** One entry of `tool_calls` on an assistant message. */
export interface ChatToolCall {
  id?: string;
  type?: string;
  function?: ChatFunctionCall;
  custom?: ChatCustomCall;
  [k: string]: unknown;
}

/** A `messages` entry. `role` is `system`, `developer`, `user`,
 * `assistant`, `tool`, or the deprecated `function`. */
export interface ChatMessage {
  role: string;
  content?: ChatContent | null;
  /** Participant name on most roles; the function name on `function`. */
  name?: string;
  refusal?: string | null;
  tool_calls?: ChatToolCall[];
  tool_call_id?: string;
  /** Deprecated single function call, superseded by `tool_calls`. */
  function_call?: ChatFunctionCall;
  [k: string]: unknown;
}

/** A function (or custom tool) definition. Only `description` carries
 * free text; `name` and the `parameters` JSON schema are structure. */
export interface ChatFunctionDef {
  name: string;
  description?: string;
  parameters?: unknown;
  [k: string]: unknown;
}

/** Request `tools[]` entry. */
export interface ChatToolDef {
  type: string;
  function?: ChatFunctionDef;
  custom?: ChatFunctionDef;
  [k: string]: unknown;
}

/** POST /v1/chat/completions request body (subset). */
export interface ChatCompletionRequest {
  model: string;
  messages: ChatMessage[];
  tools?: ChatToolDef[];
  /** Deprecated, superseded by `tools`. */
  functions?: ChatFunctionDef[];
  /** Predicted Outputs: text the reply is expected to largely repeat. */
  prediction?: { type?: string; content?: ChatContent; [k: string]: unknown };
  stream?: boolean;
  [k: string]: unknown;
}

/** One choice of a non-streaming response. */
export interface ChatChoice {
  index: number;
  message?: ChatMessage;
  finish_reason?: string | null;
  [k: string]: unknown;
}

/** POST /v1/chat/completions response body (subset). */
export interface ChatCompletionResponse {
  id: string;
  object: string;
  choices: ChatChoice[];
  [k: string]: unknown;
}

/** `tool_calls` entry of a streamed delta. The first delta of a call
 * carries `id`, `type` and the tool's `name`; the following ones carry
 * `index` and a shard of `function.arguments`, or of `custom.input` for a
 * free-form (`type: 'custom'`) tool. */
export interface ChatToolCallDelta {
  index: number;
  id?: string;
  type?: string;
  function?: ChatFunctionCall;
  custom?: ChatCustomCall;
  [k: string]: unknown;
}

/** `delta` of a streamed choice. */
export interface ChatDelta {
  role?: string;
  content?: string | null;
  refusal?: string | null;
  tool_calls?: ChatToolCallDelta[];
  function_call?: ChatFunctionCall;
  [k: string]: unknown;
}

/** One choice of a `chat.completion.chunk`. */
export interface ChatChunkChoice {
  index: number;
  delta?: ChatDelta;
  finish_reason?: string | null;
  [k: string]: unknown;
}

/** A `chat.completion.chunk`, one per `data:` line of the SSE stream. */
export interface ChatCompletionChunk {
  id?: string;
  object?: string;
  choices: ChatChunkChoice[];
  usage?: unknown;
  [k: string]: unknown;
}
