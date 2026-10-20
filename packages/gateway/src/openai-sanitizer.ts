// SPDX-License-Identifier: Apache-2.0

import { LLM_PRESERVATION_HINT, type NullPii } from 'nullpii';
import type {
  ChatCompletionRequest,
  ChatCompletionResponse,
  ChatContent,
  ChatContentPart,
  ChatCustomCall,
  ChatFunctionCall,
  ChatFunctionDef,
  ChatMessage,
  ChatToolCall,
  ChatToolDef,
} from './openai-types.js';
import {
  type CaptureAccumulator,
  type RestoreAccumulator,
  type RestoredResponse,
  type SanitizedRequest,
  holdForTool,
  isRecord,
  newCaptureAccumulator,
  newRestoreAccumulator,
  parseJson,
  restoreJsonText,
  restoreShellText,
  restoreString,
  sanitizeJsonSchema,
  sanitizeJsonValue,
  sanitizeLeaves,
  sanitizeText,
  sanitizeTopLevelText,
  shouldAppendHint,
  toolMayRestore,
} from './sanitizer.js';
import { isShellTool } from './shell-restore.js';

/**
 * Request and response walk for the OpenAI Chat Completions format, with
 * the contract `sanitizer.ts` has for Anthropic: every field that carries
 * user text is sanitized into one vault session, protocol structure
 * (roles, ids, tool and function names, JSON schemas) is left alone, and
 * media nullpii cannot read is forwarded as it is and counted.
 *
 * Bodies are mutated in place, so fields the gateway does not model
 * (sampling params, `response_format`, provider extensions) pass through.
 */

/** Content parts whose payload is binary or remote: nothing to scan. */
const UNSCANNABLE_PART_TYPES: ReadonlySet<string> = new Set(['image_url', 'input_audio']);

/** A file part: its data cannot be read, but its `filename` can name a
 * person (`CV of …`), so that one field is scanned. */
const FILE_PART_TYPE = 'file';

/** Content-part fields that carry protocol structure. Every other field
 * of a part is sanitized, so a part type added to the API later is
 * scrubbed by default instead of forwarded verbatim. */
const PART_STRUCTURAL_KEYS: ReadonlySet<string> = new Set(['type', 'cache_control']);

/** Deprecated role whose `name` is the function's name. On every other
 * role, `name` is a free-text participant name and is sanitized. */
const FUNCTION_ROLE = 'function';

/** `tools[]` payloads whose `description` is free text. */
const TOOL_DEF_KEYS = ['function', 'custom'] as const;

/** Role of the message that carries `LLM_PRESERVATION_HINT`. */
const HINT_ROLE = 'system';

/** Top-level fields whose string leaves are user data: the end-user id
 * fields (often an email), `metadata` values and `stop` sequences. Every
 * other top-level field is protocol (model, sampling, `tool_choice`,
 * `logit_bias`, `prompt_cache_key`) and is forwarded as it is. */
const TOP_LEVEL_TEXT_FIELDS: readonly string[] = ['user', 'safety_identifier', 'metadata', 'stop'];

/**
 * Sanitize a Chat Completions request body in place, binding every
 * placeholder to `sessionId`. The caller owns the session and destroys it
 * once the response is restored, on every path.
 *
 * Scanned: message `content` (a string, or `text` / `refusal` parts),
 * participant `name`, `refusal`, tool-call `arguments` (parsed as JSON,
 * string leaves sanitized), custom tool-call `input`, the deprecated
 * `function_call`, tool and function `description`s,
 * `prediction.content`, a file part's `filename`, the text and data of
 * function `parameters` and `response_format` schemas (property names and
 * keywords stay), `user`, `safety_identifier`, `metadata` values, `stop`,
 * and `web_search_options.user_location`. `image_url`, `input_audio` and
 * `file` payloads are forwarded untouched and counted in `unscanned`.
 *
 * @param np - the detection engine.
 * @param body - the client's request body; mutated and returned.
 * @param sessionId - an open vault session, from `np.createSession()`.
 * @returns the body plus capture counts (never values).
 */
export async function sanitizeChatRequest(
  np: NullPii,
  body: ChatCompletionRequest,
  sessionId: string,
  appendHint = true,
): Promise<SanitizedRequest<ChatCompletionRequest>> {
  const acc = newCaptureAccumulator();
  body.messages = await Promise.all(
    body.messages.map((m) => sanitizeMessage(np, m, sessionId, acc)),
  );
  if (Array.isArray(body.tools)) {
    body.tools = await Promise.all(body.tools.map((t) => sanitizeToolDef(np, t, sessionId, acc)));
  }
  if (Array.isArray(body.functions)) {
    body.functions = await Promise.all(
      body.functions.map((f) => sanitizeFunctionDef(np, f, sessionId, acc)),
    );
  }
  const prediction = body.prediction;
  if (isRecord(prediction) && prediction.content !== undefined) {
    const content = await sanitizeContent(np, prediction.content, sessionId, acc);
    body.prediction = { ...prediction, content };
  }
  await sanitizeTopLevelText(np, body, TOP_LEVEL_TEXT_FIELDS, sessionId, acc);
  await sanitizeResponseFormat(np, body, sessionId, acc);
  await sanitizeSearchLocation(np, body, sessionId, acc);
  // Same rules as the Anthropic walk (`sanitizeRequest`): added after
  // sanitization, so its literal `{{PII_…}}` examples are never scanned;
  // only when something was masked; and appended as the LAST message.
  // OpenAI caches prompts by prefix, so a message prepended to every
  // request would invalidate the cache on each turn.
  if (shouldAppendHint(acc.count, appendHint)) {
    body.messages = [...body.messages, { role: HINT_ROLE, content: LLM_PRESERVATION_HINT }];
  }
  return {
    body,
    sessionId,
    captured: acc.count,
    capturedByLabel: acc.byLabel,
    unscanned: acc.unscanned,
  };
}

async function sanitizeMessage(
  np: NullPii,
  msg: ChatMessage,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatMessage> {
  const out: ChatMessage = { ...msg };
  if (msg.content !== undefined && msg.content !== null) {
    out.content = await sanitizeContent(np, msg.content, sessionId, acc);
  }
  if (typeof msg.name === 'string' && msg.role !== FUNCTION_ROLE) {
    out.name = await sanitizeText(np, msg.name, sessionId, acc);
  }
  if (typeof msg.refusal === 'string') {
    out.refusal = await sanitizeText(np, msg.refusal, sessionId, acc);
  }
  if (Array.isArray(msg.tool_calls)) {
    out.tool_calls = await Promise.all(
      msg.tool_calls.map((c) => sanitizeToolCall(np, c, sessionId, acc)),
    );
  }
  if (isRecord(msg.function_call)) {
    out.function_call = await sanitizeFunctionCall(np, msg.function_call, sessionId, acc);
  }
  return out;
}

async function sanitizeContent(
  np: NullPii,
  content: ChatContent,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatContent> {
  if (typeof content === 'string') return sanitizeText(np, content, sessionId, acc);
  return Promise.all(content.map((p) => sanitizePart(np, p, sessionId, acc)));
}

/** `text`, `refusal`, and any part type added later: every field but the
 * structural ones is sanitized. Media parts are counted, not scanned. */
async function sanitizePart(
  np: NullPii,
  part: ChatContentPart,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatContentPart> {
  if (UNSCANNABLE_PART_TYPES.has(part.type)) {
    acc.unscanned += 1;
    return part;
  }
  if (part.type === FILE_PART_TYPE) return sanitizeFilePart(np, part, sessionId, acc);
  const out: ChatContentPart = { ...part };
  for (const [key, value] of Object.entries(part)) {
    if (!PART_STRUCTURAL_KEYS.has(key)) {
      out[key] = await sanitizeJsonValue(np, value, sessionId, acc);
    }
  }
  return out;
}

/** Counted as unscanned (the file itself cannot be read); only the
 * free-text `filename` is sanitized, every other field is forwarded as is. */
async function sanitizeFilePart(
  np: NullPii,
  part: ChatContentPart,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatContentPart> {
  acc.unscanned += 1;
  const file = part.file;
  if (!isRecord(file) || typeof file.filename !== 'string') return part;
  const filename = await sanitizeText(np, file.filename, sessionId, acc);
  return { ...part, file: { ...file, filename } };
}

async function sanitizeToolCall(
  np: NullPii,
  call: ChatToolCall,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatToolCall> {
  const out: ChatToolCall = { ...call };
  if (isRecord(call.function)) {
    out.function = await sanitizeFunctionCall(np, call.function, sessionId, acc);
  }
  if (isRecord(call.custom)) {
    out.custom = await sanitizeCustomCall(np, call.custom, sessionId, acc);
  }
  return out;
}

async function sanitizeFunctionCall(
  np: NullPii,
  fn: ChatFunctionCall,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatFunctionCall> {
  if (typeof fn.arguments !== 'string') return fn;
  return { ...fn, arguments: await sanitizeArguments(np, fn.arguments, sessionId, acc) };
}

async function sanitizeCustomCall(
  np: NullPii,
  call: ChatCustomCall,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatCustomCall> {
  if (typeof call.input !== 'string') return call;
  return { ...call, input: await sanitizeText(np, call.input, sessionId, acc) };
}

/** Tool-call `arguments` is a JSON document encoded as a string. It is
 * parsed and every string leaf is sanitized, so a placeholder never lands
 * across a quote; a string that does not parse is sanitized as plain
 * text. The client's exact string is kept when nothing changed:
 * re-serializing would reformat it and shift the prompt prefix the
 * upstream caches. */
async function sanitizeArguments(
  np: NullPii,
  args: string,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<string> {
  const parsed = parseJson(args);
  if (parsed === undefined) return sanitizeText(np, args, sessionId, acc);
  const next = JSON.stringify(await sanitizeJsonValue(np, parsed.value, sessionId, acc));
  return next === JSON.stringify(parsed.value) ? args : next;
}

async function sanitizeToolDef(
  np: NullPii,
  tool: ChatToolDef,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatToolDef> {
  const out: ChatToolDef = { ...tool };
  for (const key of TOOL_DEF_KEYS) {
    const def = tool[key];
    if (isRecord(def)) out[key] = await sanitizeFunctionDef(np, def, sessionId, acc);
  }
  return out;
}

async function sanitizeFunctionDef(
  np: NullPii,
  def: ChatFunctionDef,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<ChatFunctionDef> {
  const out: ChatFunctionDef = { ...def };
  if (typeof def.description === 'string') {
    out.description = await sanitizeText(np, def.description, sessionId, acc);
  }
  if (def.parameters !== undefined) {
    out.parameters = await sanitizeJsonSchema(np, def.parameters, sessionId, acc);
  }
  return out;
}

/** `response_format: { type: 'json_schema', json_schema: { description,
 * schema } }`: the description as text, the schema as a schema. */
async function sanitizeResponseFormat(
  np: NullPii,
  body: ChatCompletionRequest,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<void> {
  const format = body.response_format;
  if (!isRecord(format) || !isRecord(format.json_schema)) return;
  const spec: Record<string, unknown> = { ...format.json_schema };
  if (typeof spec.description === 'string') {
    spec.description = await sanitizeText(np, spec.description, sessionId, acc);
  }
  if (spec.schema !== undefined) {
    spec.schema = await sanitizeJsonSchema(np, spec.schema, sessionId, acc);
  }
  body.response_format = { ...format, json_schema: spec };
}

/** `web_search_options.user_location` names where the user is. */
async function sanitizeSearchLocation(
  np: NullPii,
  body: ChatCompletionRequest,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<void> {
  const options = body.web_search_options;
  if (!isRecord(options) || options.user_location === undefined) return;
  const location = await sanitizeLeaves(np, options.user_location, sessionId, acc);
  body.web_search_options = { ...options, user_location: location };
}

/**
 * Restore placeholders in a non-streaming Chat Completions response, in
 * place: each choice's `content`, `refusal`, tool-call `arguments`,
 * custom tool-call `input` and deprecated `function_call`. Returns counts
 * only, never values.
 *
 * @param np - the engine whose vault holds `sessionId`.
 * @param body - the parsed upstream response; mutated and returned.
 * @param sessionId - the session the request was sanitized into.
 */
export function restoreChatResponse(
  np: NullPii,
  body: ChatCompletionResponse,
  sessionId: string,
  restoreTools?: ReadonlySet<string>,
): RestoredResponse<ChatCompletionResponse> {
  const acc = newRestoreAccumulator(restoreTools);
  if (Array.isArray(body.choices)) {
    body.choices = body.choices.map((choice) =>
      isRecord(choice.message)
        ? { ...choice, message: restoreMessage(np, choice.message, sessionId, acc) }
        : choice,
    );
  }
  return {
    body,
    replacements: acc.replacements,
    replacementsByLabel: acc.byLabel,
    unknownPlaceholders: acc.unknown,
    foreignPlaceholders: acc.foreign,
    unsafeShellPlaceholders: acc.unsafeShell,
    heldForToolPlaceholders: acc.heldForTool,
  };
}

function restoreMessage(
  np: NullPii,
  msg: ChatMessage,
  sessionId: string,
  acc: RestoreAccumulator,
): ChatMessage {
  const out: ChatMessage = { ...msg };
  if (typeof msg.content === 'string') out.content = restoreString(np, msg.content, sessionId, acc);
  if (typeof msg.refusal === 'string') out.refusal = restoreString(np, msg.refusal, sessionId, acc);
  if (Array.isArray(msg.tool_calls)) {
    out.tool_calls = msg.tool_calls.map((c) => restoreToolCall(np, c, sessionId, acc));
  }
  if (isRecord(msg.function_call)) {
    out.function_call = restoreFunctionCall(np, msg.function_call, sessionId, acc);
  }
  return out;
}

function restoreToolCall(
  np: NullPii,
  call: ChatToolCall,
  sessionId: string,
  acc: RestoreAccumulator,
): ChatToolCall {
  const name = isRecord(call.function) ? call.function.name : call.custom?.name;
  if (!toolMayRestore(name, acc)) {
    holdForTool(JSON.stringify(call), acc);
    return call;
  }
  const out: ChatToolCall = { ...call };
  if (isRecord(call.function)) {
    out.function = restoreFunctionCall(np, call.function, sessionId, acc);
  }
  if (isRecord(call.custom) && typeof call.custom.input === 'string') {
    // A custom shell tool's whole input is the command.
    const input = isShellTool(call.custom.name)
      ? restoreShellText(np, call.custom.input, sessionId, acc)
      : restoreString(np, call.custom.input, sessionId, acc);
    out.custom = { ...call.custom, input };
  }
  return out;
}

function restoreFunctionCall(
  np: NullPii,
  fn: ChatFunctionCall,
  sessionId: string,
  acc: RestoreAccumulator,
): ChatFunctionCall {
  if (typeof fn.arguments !== 'string') return fn;
  if (!toolMayRestore(fn.name, acc)) {
    holdForTool(fn.arguments, acc);
    return fn;
  }
  const runsInShell = isShellTool(fn.name);
  return { ...fn, arguments: restoreJsonText(np, fn.arguments, sessionId, acc, runsInShell) };
}
