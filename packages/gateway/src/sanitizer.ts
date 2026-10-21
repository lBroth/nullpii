// SPDX-License-Identifier: Apache-2.0

import {
  DEFAULT_RESTORE_TOOLS,
  LLM_PRESERVATION_HINT,
  type NullPii,
  type RestoreResult,
} from 'nullpii';
import {
  SHELL_COMMAND_FIELD,
  countPlaceholders,
  isShellTool,
  placeholdersIn,
  restoreShellArgv,
  restoreShellCommand,
} from './shell-restore.js';
import type {
  AnthropicContentBlock,
  AnthropicMessage,
  AnthropicRequest,
  AnthropicResponse,
  AnthropicSystem,
  AnthropicToolDef,
} from './types.js';

/** The result of a request walk: the sanitized body, the vault session
 * its placeholders belong to, and what was masked (counts, never values). */
export interface SanitizedRequest<TBody = AnthropicRequest> {
  /** The mutated request body — same reference as the input. */
  readonly body: TBody;
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
  /** Content the gateway forwarded without being able to scan it: images,
   * and documents sent as base64, URL or file reference. Surfaced so a
   * caller can warn, or refuse by policy; nullpii cannot see inside them. */
  readonly unscanned: number;
  /** Words the model could not read (each longer, alone, than its subword
   * budget); only the recognizer pack scanned them. */
  readonly modelUnscannedWords: number;
}

/** Running sanitize counts for one request walk. Shared with the
 * OpenAI walk (`openai-sanitizer.ts`). */
export interface CaptureAccumulator {
  count: number;
  byLabel: Record<string, number>;
  unscanned: number;
  modelUnscannedWords: number;
  /** Object keys sanitized in this walk, original to sanitized. Tool
   * inputs repeat the same few keys in every turn of a history, so each
   * distinct key costs one model call per request, not one per use. The
   * promise is kept, so blocks walked concurrently share one call. The
   * vault mints one placeholder per value, so the memo returns what a
   * second call would. */
  readonly keys: Map<string, Promise<string>>;
}

/** A zeroed capture accumulator for one request walk. */
export function newCaptureAccumulator(): CaptureAccumulator {
  return { count: 0, byLabel: {}, unscanned: 0, modelUnscannedWords: 0, keys: new Map() };
}

/** Block and source fields that carry protocol structure, never user
 * text. Every other string field of a non-tool block is sanitized, so a
 * block type this gateway does not know yet is scrubbed by default
 * instead of forwarded verbatim. */
const STRUCTURAL_KEYS: ReadonlySet<string> = new Set([
  'type',
  'id',
  'tool_use_id',
  'name',
  'signature',
  'media_type',
  'cache_control',
  'file_id',
  // Server-tool payloads the upstream verifies; rewriting them breaks the turn.
  'encrypted_content',
  'encrypted_index',
]);

/** Source types whose payload is binary or remote: nothing to scan. */
const UNSCANNABLE_SOURCE_TYPES: ReadonlySet<string> = new Set(['base64', 'url', 'file']);

/** Assistant reasoning is forwarded as-is. Its `signature` covers the
 * text, so rewriting it would make the upstream reject the turn; and it
 * already carries placeholders, because it was generated from sanitized
 * input and the restore path never touches thinking deltas. */
const OPAQUE_BLOCK_TYPES: ReadonlySet<string> = new Set(['thinking', 'redacted_thinking']);

/** A call to a tool the client runs. Only its input can get real values
 * back; a server or MCP tool call (`server_tool_use`, `mcp_tool_use`) is
 * run by the upstream, off this machine. */
const CLIENT_TOOL_CALL_TYPE = 'tool_use';

/** Blocks whose `input` is arbitrary tool-argument JSON. */
const TOOL_CALL_TYPES: ReadonlySet<string> = new Set([
  CLIENT_TOOL_CALL_TYPE,
  'server_tool_use',
  'mcp_tool_use',
]);

/** Blocks whose `content` is a string or a list of content blocks. */
const TOOL_RESULT_TYPES: ReadonlySet<string> = new Set(['tool_result', 'mcp_tool_result']);

/**
 * Sanitize an Anthropic request body in place into a new vault session:
 * every field that can carry user text (see the gateway README's
 * "Scanned" list) goes through the engine, and every placeholder is
 * bound to that one session. Mutating the body in place keeps unknown
 * fields (provider extensions, future parameters) as they are.
 *
 * The caller owns the returned `sessionId` and destroys it once the
 * response is restored. If the walk throws, the session is destroyed
 * here before the error propagates: the caller never learns its id, so
 * it could not drop it.
 *
 * @param appendHint - append `LLM_PRESERVATION_HINT` when something was
 *   masked (`NULLPII_DISABLE_HINT=1` turns it off in the config).
 */
export async function sanitizeRequest(
  np: NullPii,
  body: AnthropicRequest,
  appendHint = true,
): Promise<SanitizedRequest> {
  const sessionId = np.createSession();
  try {
    return await sanitizeIntoSession(np, body, sessionId, appendHint);
  } catch (err) {
    np.destroySession(sessionId);
    throw err;
  }
}

async function sanitizeIntoSession(
  np: NullPii,
  body: AnthropicRequest,
  sessionId: string,
  appendHint: boolean,
): Promise<SanitizedRequest> {
  const acc = newCaptureAccumulator();
  if (body.system !== undefined) {
    body.system = await sanitizeSystem(np, body.system, sessionId, acc);
  }
  body.messages = await Promise.all(
    body.messages.map((m) => sanitizeMessage(np, m, sessionId, acc)),
  );
  if (Array.isArray(body.tools)) {
    body.tools = await Promise.all(body.tools.map((t) => sanitizeToolDef(np, t, sessionId, acc)));
  }
  await sanitizeTopLevelText(np, body, TOP_LEVEL_TEXT_FIELDS, sessionId, acc);
  await sanitizeOutputFormats(np, body, sessionId, acc);
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
  // Opt-out: NULLPII_DISABLE_HINT=1 (debugging hook), read by the config.
  if (shouldAppendHint(acc.count, appendHint)) {
    injectPreservationHint(body);
  }
  return {
    body,
    sessionId,
    captured: acc.count,
    capturedByLabel: acc.byLabel,
    unscanned: acc.unscanned,
    modelUnscannedWords: acc.modelUnscannedWords,
  };
}

/** Whether a request walk that masked `captured` spans gets
 * `LLM_PRESERVATION_HINT` appended: only when something was masked, and
 * only when the hint is on (`NULLPII_DISABLE_HINT=1` turns it off in the
 * config). Shared by the Anthropic and OpenAI walks. */
export function shouldAppendHint(captured: number, appendHint: boolean): boolean {
  return captured > 0 && appendHint;
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

/** Top-level request fields that can carry user text besides `system`,
 * `messages`, `tools` and the structured-output schema (see
 * `sanitizeOutputFormats`): `metadata` (`user_id` is often an email) and
 * `stop_sequences`. Every other top-level field is protocol (model,
 * sampling, `tool_choice`, `thinking`, `output_config.effort`) or meant
 * for the upstream itself (`mcp_servers` URLs and credentials), and is
 * forwarded as it is. */
const TOP_LEVEL_TEXT_FIELDS: readonly string[] = ['metadata', 'stop_sequences'];

/** Deprecated top-level structured-output spec, superseded by
 * `output_config.format`. */
const OUTPUT_FORMAT_FIELD = 'output_format';
/** Holds `format` (the structured-output spec) next to protocol settings
 * such as `effort` and `task_budget`, which stay as they are. */
const OUTPUT_CONFIG_FIELD = 'output_config';

/** Sanitize the structured-output spec of a request, in place: the
 * deprecated `output_format` and `output_config.format`, each by
 * `sanitizeSchemaSpec`. A masked `enum` value the model answers with
 * comes back restored, since response text is always restored. */
async function sanitizeOutputFormats(
  np: NullPii,
  body: AnthropicRequest,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<void> {
  const legacy = body[OUTPUT_FORMAT_FIELD];
  if (isRecord(legacy)) {
    body[OUTPUT_FORMAT_FIELD] = await sanitizeSchemaSpec(np, legacy, sessionId, acc);
  }
  const config = body[OUTPUT_CONFIG_FIELD];
  if (isRecord(config) && isRecord(config.format)) {
    const format = await sanitizeSchemaSpec(np, config.format, sessionId, acc);
    body[OUTPUT_CONFIG_FIELD] = { ...config, format };
  }
}

/**
 * Sanitize a structured-output spec: its `description` as text and its
 * `schema` as a JSON schema (`sanitizeJsonSchema`); `type`, `name`,
 * `strict` and any other field stay. Both APIs use this shape: Anthropic's
 * `output_config.format` (and the deprecated `output_format`), OpenAI's
 * `response_format.json_schema`.
 *
 * @returns a sanitized copy; `spec` is not mutated.
 */
export async function sanitizeSchemaSpec(
  np: NullPii,
  spec: Readonly<Record<string, unknown>>,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<Record<string, unknown>> {
  const out: Record<string, unknown> = { ...spec };
  if (typeof spec.description === 'string') {
    out.description = await sanitizeText(np, spec.description, sessionId, acc);
  }
  if (spec.schema !== undefined) {
    out.schema = await sanitizeJsonSchema(np, spec.schema, sessionId, acc);
  }
  return out;
}

/** Sanitize the string leaves of the named top-level fields of `body`, in
 * place; their object keys are API-defined (`user_id`) and stay. Shared
 * with the OpenAI walk. */
export async function sanitizeTopLevelText(
  np: NullPii,
  body: Record<string, unknown>,
  fields: readonly string[],
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<void> {
  for (const field of fields) {
    if (body[field] !== undefined) {
      body[field] = await sanitizeLeaves(np, body[field], sessionId, acc);
    }
  }
}

/** Sanitize one string into the session, tallying its spans into `acc`. */
export async function sanitizeText(
  np: NullPii,
  text: string,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<string> {
  const r = await np.sanitize(text, sessionId);
  bump(acc, r);
  return r.sanitized;
}

/** Add one `sanitize()` result's spans to `acc` (counts and labels only),
 * and the words its model could not read. */
export function bump(
  acc: CaptureAccumulator,
  r: { spans: ReadonlyArray<{ label: string }>; modelUnscannedWords?: number },
): void {
  acc.count += r.spans.length;
  acc.modelUnscannedWords += r.modelUnscannedWords ?? 0;
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
  if (typeof system === 'string') return sanitizeText(np, system, sessionId, acc);
  return Promise.all(system.map((b) => sanitizeBlock(np, b, sessionId, acc)));
}

async function sanitizeMessage(
  np: NullPii,
  msg: AnthropicMessage,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<AnthropicMessage> {
  if (typeof msg.content === 'string') {
    return { ...msg, content: await sanitizeText(np, msg.content, sessionId, acc) };
  }
  return {
    ...msg,
    content: await Promise.all(msg.content.map((b) => sanitizeBlock(np, b, sessionId, acc))),
  };
}

/** Tool-definition fields forwarded as written. `name` and `type` are
 * what the API and the model match a tool by (and `restoreTools` matches
 * the name); `cache_control` is protocol; the web tools' `allowed_domains`
 * and `blocked_domains` are filters the upstream applies as written (a
 * masked domain would match nothing); `allowed_callers` lists tool types,
 * `model` (advisor tool) a model id; `mcp_server_name` must match an
 * `mcp_servers` entry, which is forwarded as it is. */
const TOOL_DEF_STRUCTURAL_KEYS: ReadonlySet<string> = new Set([
  'name',
  'type',
  'cache_control',
  'allowed_domains',
  'blocked_domains',
  'allowed_callers',
  'model',
  'mcp_server_name',
]);

/** The tool-definition field that holds the tool's input JSON schema. */
const TOOL_INPUT_SCHEMA_FIELD = 'input_schema';

/**
 * Sanitize one `tools[]` entry (a client tool, a server tool such as web
 * search, an MCP toolset): `input_schema` as a JSON schema
 * (`sanitizeJsonSchema`), the structural fields as written, and every
 * other field as data whose object keys stay (`sanitizeLeaves`): the
 * `description`, `input_examples` (keyed by the schema's property names,
 * which must keep matching it), web search's `user_location`, and any
 * field the API adds later, which is scrubbed by default instead of
 * forwarded verbatim. Numbers and booleans pass through.
 */
async function sanitizeToolDef(
  np: NullPii,
  tool: AnthropicToolDef,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<AnthropicToolDef> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(tool)) {
    out[key] = await sanitizeToolDefField(np, key, value, sessionId, acc);
  }
  return out as AnthropicToolDef;
}

function sanitizeToolDefField(
  np: NullPii,
  key: string,
  value: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<unknown> {
  if (TOOL_DEF_STRUCTURAL_KEYS.has(key)) return Promise.resolve(value);
  if (key === TOOL_INPUT_SCHEMA_FIELD) return sanitizeJsonSchema(np, value, sessionId, acc);
  return sanitizeLeaves(np, value, sessionId, acc);
}

/** JSON-schema keywords whose value is free text the model reads. */
const SCHEMA_TEXT_KEYWORDS: ReadonlySet<string> = new Set(['description', 'title', '$comment']);

/** JSON-schema keywords whose value is example or allowed data. */
const SCHEMA_DATA_KEYWORDS: ReadonlySet<string> = new Set(['enum', 'const', 'default', 'examples']);

/** JSON-schema keywords whose value maps names to subschemas. */
const SCHEMA_NAMED_KEYWORDS: ReadonlySet<string> = new Set([
  'properties',
  'patternProperties',
  '$defs',
  'definitions',
  'dependentSchemas',
]);

/**
 * Sanitize a JSON schema (a tool's `input_schema`, an OpenAI function's
 * `parameters`, a structured-output schema) without changing what it
 * validates: descriptions, titles and comments are sanitized as text, and
 * `enum`, `const`, `default` and `examples` values as data. Property names
 * and every keyword are the developer's identifiers, which the model must
 * see as written to call the tool, so they stay; so do `pattern` and
 * `format`. A masked `enum` value is what the model then answers with: the
 * response restore puts the real value back where it restores at all, in
 * the reply text and in the input of a tool in `restoreTools`. The input
 * of any other tool keeps it masked.
 */
export async function sanitizeJsonSchema(
  np: NullPii,
  schema: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<unknown> {
  if (Array.isArray(schema)) {
    return Promise.all(schema.map((s) => sanitizeJsonSchema(np, s, sessionId, acc)));
  }
  if (!isRecord(schema)) return schema;
  const out: Record<string, unknown> = {};
  for (const [keyword, value] of Object.entries(schema)) {
    out[keyword] = await sanitizeSchemaKeyword(np, keyword, value, sessionId, acc);
  }
  return out;
}

async function sanitizeSchemaKeyword(
  np: NullPii,
  keyword: string,
  value: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<unknown> {
  if (SCHEMA_TEXT_KEYWORDS.has(keyword) && typeof value === 'string') {
    return sanitizeText(np, value, sessionId, acc);
  }
  if (SCHEMA_DATA_KEYWORDS.has(keyword)) return sanitizeLeaves(np, value, sessionId, acc);
  if (SCHEMA_NAMED_KEYWORDS.has(keyword) && isRecord(value)) {
    const out: Record<string, unknown> = {};
    for (const [name, sub] of Object.entries(value)) {
      out[name] = await sanitizeJsonSchema(np, sub, sessionId, acc);
    }
    return out;
  }
  return sanitizeJsonSchema(np, value, sessionId, acc);
}

async function sanitizeBlock(
  np: NullPii,
  block: AnthropicContentBlock,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<AnthropicContentBlock> {
  if (OPAQUE_BLOCK_TYPES.has(block.type)) return block;
  if (block.type === 'image') {
    acc.unscanned += 1;
    return block;
  }
  if (TOOL_CALL_TYPES.has(block.type)) {
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
  if (TOOL_RESULT_TYPES.has(block.type)) {
    const content = block.content;
    if (typeof content === 'string') {
      return { ...block, content: await sanitizeText(np, content, sessionId, acc) };
    }
    if (Array.isArray(content)) {
      const next = await Promise.all(
        content.map((b) => sanitizeBlock(np, b as AnthropicContentBlock, sessionId, acc)),
      );
      return { ...block, content: next };
    }
    return block;
  }
  // `text` (its `citations` quote source documents), `document`,
  // `search_result`, and any block type added to the API later.
  return (await sanitizeFields(np, block, sessionId, acc)) as AnthropicContentBlock;
}

/** Sanitize every string field of a block, recursively, except the
 * structural ones. A nested `{ type: 'base64' | 'url' | 'file' }` source
 * is binary or remote: it is forwarded untouched and counted as
 * unscanned. A nested object with a `type` is a content block (for
 * example a document's `content`) and goes back through `sanitizeBlock`. */
async function sanitizeFields(
  np: NullPii,
  value: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<unknown> {
  if (typeof value === 'string') return sanitizeText(np, value, sessionId, acc);
  if (Array.isArray(value)) {
    return Promise.all(value.map((v) => sanitizeChild(np, v, sessionId, acc)));
  }
  if (value === null || typeof value !== 'object') return value;
  const obj = value as Record<string, unknown>;
  if (typeof obj.type === 'string' && UNSCANNABLE_SOURCE_TYPES.has(obj.type)) {
    acc.unscanned += 1;
    return value;
  }
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(obj)) {
    out[k] = STRUCTURAL_KEYS.has(k) ? v : await sanitizeChild(np, v, sessionId, acc);
  }
  return out;
}

function sanitizeChild(
  np: NullPii,
  value: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<unknown> {
  const isBlock =
    value !== null &&
    typeof value === 'object' &&
    !Array.isArray(value) &&
    typeof (value as { type?: unknown }).type === 'string';
  return isBlock
    ? sanitizeBlock(np, value as AnthropicContentBlock, sessionId, acc)
    : sanitizeFields(np, value, sessionId, acc);
}

/** A JSON value with every string leaf sanitized into one vault session. */
export interface SanitizedValue {
  readonly value: unknown;
  readonly captured: number;
  readonly capturedByLabel: Readonly<Record<string, number>>;
  /** Words the model could not read; only the recognizers scanned them. */
  readonly modelUnscannedWords: number;
}

/** Sanitize every string of a parsed JSON value (a string, a tool result,
 * a prompt) into an existing vault session, object keys included (see
 * `sanitizeJsonValue`). Used by the sidecar routes. */
export async function sanitizeValue(
  np: NullPii,
  value: unknown,
  sessionId: string,
): Promise<SanitizedValue> {
  const acc = newCaptureAccumulator();
  const out = await sanitizeJsonValue(np, value, sessionId, acc);
  return {
    value: out,
    captured: acc.count,
    capturedByLabel: acc.byLabel,
    modelUnscannedWords: acc.modelUnscannedWords,
  };
}

/** Recursively walk a JSON value that holds data (tool-call input, a tool
 * result, the result of `JSON.parse` on tool arguments), sanitizing every
 * string leaf and every object key: a tool's input can key data by a
 * name or an email (`{ "ada@acme.io": "owner" }`). Numbers, booleans and
 * null pass through. Cycles are not possible on JSON.parse output, so no
 * visited-set is needed. */
export async function sanitizeJsonValue(
  np: NullPii,
  value: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<unknown> {
  return walkJson(np, value, sessionId, acc, true);
}

/** As `sanitizeJsonValue`, but object keys stay: for values whose keys
 * are defined by an API or a schema (`metadata.user_id`, a schema's
 * `examples`). */
export async function sanitizeLeaves(
  np: NullPii,
  value: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<unknown> {
  return walkJson(np, value, sessionId, acc, false);
}

async function walkJson(
  np: NullPii,
  value: unknown,
  sessionId: string,
  acc: CaptureAccumulator,
  keys: boolean,
): Promise<unknown> {
  if (typeof value === 'string') return sanitizeText(np, value, sessionId, acc);
  if (Array.isArray(value)) {
    return Promise.all(value.map((v) => walkJson(np, v, sessionId, acc, keys)));
  }
  if (!isRecord(value)) return value;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value)) {
    const key = keys ? await sanitizeKey(np, k, sessionId, acc) : k;
    out[key] = await walkJson(np, v, sessionId, acc, keys);
  }
  return out;
}

/** Sanitize an object key once per walk (see `CaptureAccumulator.keys`). */
function sanitizeKey(
  np: NullPii,
  key: string,
  sessionId: string,
  acc: CaptureAccumulator,
): Promise<string> {
  const known = acc.keys.get(key);
  if (known !== undefined) return known;
  const sanitized = sanitizeText(np, key, sessionId, acc);
  acc.keys.set(key, sanitized);
  return sanitized;
}

/** The result of a response restore: the restored body and the restore
 * counts per kind (counts only, never values). */
export interface RestoredResponse<TBody = AnthropicResponse> {
  readonly body: TBody;
  readonly replacements: number;
  readonly replacementsByLabel: Readonly<Partial<Record<string, number>>>;
  readonly unknownPlaceholders: number;
  readonly foreignPlaceholders: number;
  /** Placeholders left literal in a shell tool's `command` because their
   * value was not safe in the quoting there (see `shell-restore.ts`). */
  readonly unsafeShellPlaceholders: number;
  /** Placeholders left in the input of a tool outside `restoreTools`
   * (network and MCP tools by default), so no value leaves through it. */
  readonly heldForToolPlaceholders: number;
}

// A short-named accumulator for the restore walks (restoreResponse, and
// the OpenAI walk and relay, which convert it to SseRelayCounters at the
// end). sse-relay's public SseRelayCounters uses long names that match the
// pino log fields; merging the two would rename a public API or make this
// internal struct verbose.
export interface RestoreAccumulator {
  /** Tools whose arguments get real values back; any other tool keeps
   * its placeholders. */
  readonly restoreTools: ReadonlySet<string>;
  replacements: number;
  byLabel: Record<string, number>;
  unknown: number;
  foreign: number;
  /** Placeholders kept literal in a shell command: unsafe there. */
  unsafeShell: number;
  /** Placeholders kept in the input of a tool outside `restoreTools`. */
  heldForTool: number;
}

/** A zeroed restore accumulator for one request. */
export function newRestoreAccumulator(
  restoreTools: ReadonlySet<string> = new Set(DEFAULT_RESTORE_TOOLS),
): RestoreAccumulator {
  return {
    restoreTools,
    replacements: 0,
    byLabel: {},
    unknown: 0,
    foreign: 0,
    unsafeShell: 0,
    heldForTool: 0,
  };
}

/** Whether a tool call named `name` may receive real values. */
export function toolMayRestore(name: unknown, acc: RestoreAccumulator): boolean {
  return typeof name === 'string' && acc.restoreTools.has(name);
}

/** Whether an Anthropic content block is a tool call whose input may
 * receive real values: a client `tool_use` of a tool in `restoreTools`.
 * Server and MCP tool calls never do, whatever their name: the upstream
 * runs them. Shared by the JSON restore and the stream relay. */
export function toolCallMayRestore(
  block: Readonly<Record<string, unknown>>,
  acc: RestoreAccumulator,
): boolean {
  return block.type === CLIENT_TOOL_CALL_TYPE && toolMayRestore(block.name, acc);
}

/** Keep a tool input's placeholders as they are, counting them. */
export function holdForTool(text: string, acc: RestoreAccumulator): string {
  acc.heldForTool += countPlaceholders(text);
  return text;
}

/**
 * Restore an Anthropic response body in place against `sessionId`: every
 * `text` block, and the input of each client tool call (`tool_use`) to a
 * tool in `restoreTools` (a shell tool's `command` by the shell rule). A
 * tool outside the list, and every server or MCP tool call
 * (`server_tool_use`, `mcp_tool_use`: the upstream runs them), keeps its
 * placeholders, counted as held. Returns the body plus counts; the caller
 * logs the counts, never the values.
 */
export function restoreResponse(
  np: NullPii,
  body: AnthropicResponse,
  sessionId: string,
  restoreTools?: ReadonlySet<string>,
): RestoredResponse {
  const acc = newRestoreAccumulator(restoreTools);
  body.content = body.content.map((block) => {
    if (block.type === 'text' && typeof block.text === 'string') {
      return { ...block, text: restoreString(np, block.text, sessionId, acc) };
    }
    if (TOOL_CALL_TYPES.has(block.type) && block.input !== undefined) {
      if (!toolCallMayRestore(block, acc)) {
        holdForTool(JSON.stringify(block.input), acc);
        return block;
      }
      // Mirror SSE path's `restoreJsonBuffer`: walk the tool input tree
      // and restore string leaves. Without this, non-streaming
      // tool-calling workflows leak `{{PII_*}}` placeholders verbatim
      // to the client. A shell tool's command gets the shell-aware restore.
      const runsInShell = isShellTool(block.name);
      return { ...block, input: restoreToolInput(np, block.input, sessionId, acc, runsInShell) };
    }
    return block;
  });
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

/** A JSON value with placeholders restored, plus counts only. */
export interface RestoredValue {
  readonly value: unknown;
  readonly replacements: number;
  readonly replacementsByLabel: Readonly<Partial<Record<string, number>>>;
  readonly unknownPlaceholders: number;
  readonly foreignPlaceholders: number;
  /** With `shell`: the distinct placeholders left masked in `command`
   * because their value was not safe there, or because the command sends
   * data off the machine. Placeholders, never values. */
  readonly shellKeptMasked?: readonly string[];
}

/** Restore placeholders in every string leaf of a parsed JSON value.
 * With `fields`, only those top-level keys of an object are restored and
 * every other key keeps its placeholders, so a caller can put real values
 * back into the arguments a tool writes to disk and nowhere else.
 *
 * With `shell` (the value is a shell tool's input), a top-level `command`
 * that is restored gets the shell-aware rule of `shell-restore.ts`
 * (`restoreShellField`); the placeholders it leaves masked are listed in
 * `shellKeptMasked`. */
export function restoreValue(
  np: NullPii,
  value: unknown,
  sessionId: string,
  fields?: readonly string[],
  shell = false,
): RestoredValue {
  const acc = newRestoreAccumulator();
  const keptMasked: string[] = [];
  const restoreField = (key: string, field: unknown): unknown =>
    shell && key === SHELL_COMMAND_FIELD
      ? restoreShellField(np, field, sessionId, acc, keptMasked)
      : restoreJsonValue(np, field, sessionId, acc);
  const obj = isRecord(value) ? value : undefined;
  let out: unknown;
  if (obj === undefined || (fields === undefined && !shell)) {
    out = restoreJsonValue(np, value, sessionId, acc);
  } else {
    const restored: Record<string, unknown> = { ...obj };
    for (const key of fields ?? Object.keys(obj)) {
      if (Object.hasOwn(obj, key)) restored[key] = restoreField(key, obj[key]);
    }
    out = restored;
  }
  return {
    value: out,
    replacements: acc.replacements,
    replacementsByLabel: acc.byLabel,
    unknownPlaceholders: acc.unknown,
    foreignPlaceholders: acc.foreign,
    ...(shell && { shellKeptMasked: [...new Set(keptMasked)] }),
  };
}

/** Add one restore result's counts to `acc`. Takes the result of
 * `np.restore()` or of `RestoreStream.end()`; values are never kept. */
export function tallyRestore(acc: RestoreAccumulator, r: RestoreResult): void {
  acc.replacements += r.replacements;
  for (const [lbl, count] of Object.entries(r.replacementsByLabel)) {
    acc.byLabel[lbl] = (acc.byLabel[lbl] ?? 0) + (count ?? 0);
  }
  acc.unknown += r.unknownPlaceholders.length;
  acc.foreign += r.foreignPlaceholders.length;
}

/** Restore the placeholders in one string, tallying counts into `acc`. */
export function restoreString(
  np: NullPii,
  text: string,
  sessionId: string,
  acc: RestoreAccumulator,
): string {
  const r = np.restore(text, sessionId);
  tallyRestore(acc, r);
  return r.restored;
}

/** Restore every string leaf of a parsed JSON value, and every object key
 * that holds a placeholder (the request walk masks keys too). */
export function restoreJsonValue(
  np: NullPii,
  value: unknown,
  sessionId: string,
  acc: RestoreAccumulator,
): unknown {
  if (typeof value === 'string') return restoreString(np, value, sessionId, acc);
  if (Array.isArray(value)) return value.map((v) => restoreJsonValue(np, v, sessionId, acc));
  if (!isRecord(value)) return value;
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(value)) {
    const key = countPlaceholders(k) > 0 ? restoreString(np, k, sessionId, acc) : k;
    out[key] = restoreJsonValue(np, v, sessionId, acc);
  }
  return out;
}

/**
 * Restore a tool call's input. For a tool a shell runs (`runsInShell`),
 * the top-level `command` gets the shell-aware restore
 * (`restoreShellField`): each placeholder is put back only when its value
 * is safe where it stands. Every other field, and every field of any
 * other tool, gets its real values back as usual.
 */
export function restoreToolInput(
  np: NullPii,
  input: unknown,
  sessionId: string,
  acc: RestoreAccumulator,
  runsInShell: boolean,
): unknown {
  if (!runsInShell || !isRecord(input)) return restoreJsonValue(np, input, sessionId, acc);
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(input)) {
    out[key] =
      key === SHELL_COMMAND_FIELD
        ? restoreShellField(np, value, sessionId, acc)
        : restoreJsonValue(np, value, sessionId, acc);
  }
  return out;
}

/**
 * Shell-aware restore of a shell tool's `command`: a string is a script
 * (`restoreShellText`), an array of strings an argv the program gets
 * without a shell (`restoreShellArgv`). Any other shape keeps every
 * placeholder, counted as unsafe: there is no telling how it is run.
 */
export function restoreShellField(
  np: NullPii,
  command: unknown,
  sessionId: string,
  acc: RestoreAccumulator,
  keptMasked?: string[],
): unknown {
  if (typeof command === 'string') return restoreShellText(np, command, sessionId, acc, keptMasked);
  if (Array.isArray(command) && command.every((w) => typeof w === 'string')) {
    const r = restoreShellArgv(np, command, sessionId);
    tallyShell(acc, r, keptMasked);
    return r.argv;
  }
  const text = JSON.stringify(command) ?? '';
  acc.unsafeShell += countPlaceholders(text);
  keptMasked?.push(...placeholdersIn(text));
  return command;
}

/** Shell-aware restore of one command string (see `shell-restore.ts`),
 * tallying counts into `acc` and, when given, appending the placeholders
 * it left masked to `keptMasked`. */
export function restoreShellText(
  np: NullPii,
  command: string,
  sessionId: string,
  acc: RestoreAccumulator,
  keptMasked?: string[],
): string {
  const r = restoreShellCommand(np, command, sessionId);
  tallyShell(acc, r, keptMasked);
  return r.command;
}

/** Add a shell restore's counts to `acc`, and the placeholders it left
 * masked to `keptMasked` when given. */
function tallyShell(
  acc: RestoreAccumulator,
  r: { readonly results: readonly RestoreResult[]; readonly keptMasked: readonly string[] },
  keptMasked?: string[],
): void {
  for (const result of r.results) tallyRestore(acc, result);
  acc.unsafeShell += r.keptMasked.length;
  keptMasked?.push(...r.keptMasked);
}

/**
 * Restore a JSON document held as a string: tool-call arguments, or the
 * tool input a stream assembles from `input_json_delta` shards. It is
 * parsed and only its string leaves are restored, then re-serialized, so
 * a restored value holding a quote, a backslash or a newline is escaped
 * instead of breaking the JSON. A string that does not parse (input cut
 * off mid-stream) is restored as plain text rather than dropped; one with
 * nothing to restore is returned exactly as it came.
 *
 * With `runsInShell`, the input's `command` gets the shell-aware restore
 * (`restoreToolInput`), and input that does not parse keeps every
 * placeholder: without its JSON structure there is no telling which part
 * a shell would run.
 *
 * @param acc - restore counts are added here.
 */
export function restoreJsonText(
  np: NullPii,
  text: string,
  sessionId: string,
  acc: RestoreAccumulator,
  runsInShell = false,
): string {
  const parsed = parseJson(text);
  if (parsed === undefined && runsInShell) {
    acc.unsafeShell += countPlaceholders(text);
    return text;
  }
  if (parsed === undefined) return restoreString(np, text, sessionId, acc);
  const restored = restoreToolInput(np, parsed.value, sessionId, acc, runsInShell);
  const next = JSON.stringify(restored);
  return next === JSON.stringify(parsed.value) ? text : next;
}

/**
 * Parse `text` as JSON. Wrapped in `{ value }` so a JSON `null` is told
 * apart from a parse failure, which returns `undefined`.
 */
export function parseJson(text: string): { value: unknown } | undefined {
  try {
    return { value: JSON.parse(text) as unknown };
  } catch {
    // Deliberate: not-JSON is an expected input here (tool arguments cut
    // off mid-stream, an SSE payload that is not a chunk). Every caller
    // has a fallback for it.
    return undefined;
  }
}

/** True for a non-null, non-array object. */
export function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}
