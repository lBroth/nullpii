// SPDX-License-Identifier: Apache-2.0
//
// Pure helpers for the nullpii mod: which tool arguments are sent for a
// restore, which calls touch the masking-policy file, and how the counts
// and the policy are shown. No mods API calls live here, so
// `claude plugin validate` reads every `$` call from register.ts.

import { shortName } from './categories.ts';

/**
 * Arguments that may get their real values back, per built-in tool that
 * acts on this machine. Whether a tool gets any is not decided here: the
 * sidecar restores only into the tools its policy lists (`restoreTools`
 * in the shared config file), so the mod and the gateway follow one list.
 * A tool missing from this table sends every argument it has.
 */
const RESTORE_FIELDS: Readonly<Record<string, readonly string[]>> = {
  Bash: ['command'],
  Read: ['file_path'],
  Edit: ['file_path', 'old_string', 'new_string'],
  MultiEdit: ['file_path', 'edits'],
  Write: ['file_path', 'content'],
  NotebookEdit: ['notebook_path', 'new_source'],
  Grep: ['pattern', 'path', 'glob'],
  Glob: ['pattern', 'path'],
};

/** Keys of a `tool.call` event that are not the tool's own arguments. */
const RESERVED_KEYS: ReadonlySet<string> = new Set(['tool', 'tool_use_id', 'agentId', 'consent']);

/** `{{PII_<LABEL>_<index>_<16 hex session prefix>}}`, nullpii's
 * `PLACEHOLDER_REGEX` without the global flag. */
export const PLACEHOLDER = /\{\{PII_[A-Z_]+_\d+_[0-9a-f]{16}\}\}/;

/** The arguments of a tool call to send for a restore: the listed fields
 * of a built-in tool, else every argument. */
export function restorableArgs(call: Readonly<Record<string, unknown>>): Record<string, unknown> {
  const tool = typeof call.tool === 'string' ? call.tool : '';
  const fields = RESTORE_FIELDS[tool];
  return Object.fromEntries(
    Object.entries(call).filter(([key]) =>
      fields === undefined ? !RESERVED_KEYS.has(key) : fields.includes(key),
    ),
  );
}

/** A plugin option's value when it is a non-empty string, else undefined
 * (an unset option, or an empty one the dialog saved). */
export function optionString(
  options: Readonly<Record<string, unknown>> | undefined,
  key: string,
): string | undefined {
  const value = options?.[key];
  return typeof value === 'string' && value !== '' ? value : undefined;
}

/** The boolean option `key`, else `fallback` (an option left unset). */
export function optionFlag(
  options: Readonly<Record<string, unknown>> | undefined,
  key: string,
  fallback: boolean,
): boolean {
  const value = options?.[key];
  return typeof value === 'boolean' ? value : fallback;
}

/** The sidecar speaks plain HTTP: it listens on this machine only. */
const SIDECAR_PROTOCOL = 'http:';
/** The host names the sidecar answers to: it refuses a request whose
 * `Host` is any other, so a URL naming another host is never the sidecar.
 * `URL` writes `127.1`, `0x7f000001` and `LOCALHOST` in these forms. */
/** Literal loopback addresses only: `localhost` can resolve to `[::1]`
 * while the gateway listens on 127.0.0.1, and another local process
 * bound to the other address could relay the challenge to the real
 * sidecar and then receive the token and the text. */
const LOOPBACK_HOSTNAMES: ReadonlySet<string> = new Set(['127.0.0.1', '[::1]']);
/** The sidecar's routes sit at the root of its address. */
const ROOT_PATH = '/';

/**
 * The origin of a sidecar address (`http://127.0.0.1:8787`), or undefined
 * when `raw` is not one: anything but `http:` on 127.0.0.1 or
 * [::1] (any port), or an address with a user name, a password, a path, a
 * query or a fragment. The mod sends its token and the text it masks to
 * this address, so nothing else is accepted.
 */
export function sidecarOrigin(raw: string): string | undefined {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    // Not a URL at all: the caller reports the address as refused.
    return undefined;
  }
  const loopback = url.protocol === SIDECAR_PROTOCOL && LOOPBACK_HOSTNAMES.has(url.hostname);
  const bare =
    url.username === '' &&
    url.password === '' &&
    url.pathname === ROOT_PATH &&
    url.search === '' &&
    url.hash === '';
  return loopback && bare ? url.origin : undefined;
}

/** Prefixed to the nonce the sidecar signs; the gateway's
 * `CHALLENGE_CONTEXT`. */
const CHALLENGE_CONTEXT = 'nullpii-sidecar-challenge-v1\n';
/** SHA-256 block size in bytes, the HMAC key length. */
const SHA256_BLOCK_BYTES = 64;
const HMAC_INNER_PAD = 0x36;
const HMAC_OUTER_PAD = 0x5c;
const NONCE_BYTES = 32;
const HEX_RADIX = 16;
const HEX_BYTE_WIDTH = 2;

function toHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(HEX_RADIX).padStart(HEX_BYTE_WIDTH, '0')).join('');
}

async function sha256(...parts: Uint8Array[]): Promise<Uint8Array> {
  const joined = new Uint8Array(parts.reduce((n, part) => n + part.length, 0));
  let at = 0;
  for (const part of parts) {
    joined.set(part, at);
    at += part.length;
  }
  return new Uint8Array(await crypto.subtle.digest('SHA-256', joined));
}

/** HMAC-SHA256 (RFC 2104) in lower-case hex. A mod has only
 * `crypto.subtle.digest`, so the construction is spelled out. */
export async function hmacSha256Hex(key: string, message: string): Promise<string> {
  const encoder = new TextEncoder();
  let keyBytes = encoder.encode(key);
  if (keyBytes.length > SHA256_BLOCK_BYTES) keyBytes = await sha256(keyBytes);
  const inner = new Uint8Array(SHA256_BLOCK_BYTES).map(
    (_, i) => (keyBytes[i] ?? 0) ^ HMAC_INNER_PAD,
  );
  const outer = new Uint8Array(SHA256_BLOCK_BYTES).map(
    (_, i) => (keyBytes[i] ?? 0) ^ HMAC_OUTER_PAD,
  );
  return toHex(await sha256(outer, await sha256(inner, encoder.encode(message))));
}

/** A fresh challenge nonce: 32 random bytes in lower-case hex. */
export function challengeNonce(): string {
  return toHex(crypto.getRandomValues(new Uint8Array(NONCE_BYTES)));
}

/** The proof a sidecar holding `token` answers for `nonce`. */
export function expectedProof(token: string, nonce: string): Promise<string> {
  return hmacSha256Hex(token, CHALLENGE_CONTEXT + nonce);
}

/** Compare two strings in time that depends only on their length. */
export function sameText(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** Whether any string in `value` holds a placeholder. */
export function hasPlaceholder(value: unknown): boolean {
  return PLACEHOLDER.test(JSON.stringify(value) ?? '');
}

/** Every placeholder in a text, for a replace. */
const PLACEHOLDER_ALL = new RegExp(PLACEHOLDER.source, 'g');

/** `value` with the placeholders `values` names replaced by their real
 * values, and how many were replaced. */
export interface Substituted {
  readonly value: unknown;
  readonly replacements: number;
  /** Each string or key the replace changed, as it reads now, mapped to
   * the text it was (with its placeholders): what puts a restored text
   * that comes back in a result to the form Claude wrote it in. */
  readonly changed: ReadonlyMap<string, string>;
}

/**
 * `value` with each placeholder that `values` maps replaced by its real
 * value, in every string and every object key, as the sidecar's restore
 * walks a value; every other placeholder is left as it is. The values the
 * user was asked about, and only those, so nothing the vault learns later
 * goes out unasked. One pass per string: a real value that reads like a
 * placeholder is not replaced again.
 */
export function substitutePlaceholders(
  value: unknown,
  values: ReadonlyMap<string, string>,
): Substituted {
  let replacements = 0;
  const changed = new Map<string, string>();
  const inText = (text: string) => {
    const out = text.replace(PLACEHOLDER_ALL, (placeholder) => {
      const real = values.get(placeholder);
      if (real === undefined) return placeholder;
      replacements += 1;
      return real;
    });
    if (out !== text && !changed.has(out)) changed.set(out, text);
    return out;
  };
  const walk = (one: unknown): unknown => {
    if (typeof one === 'string') return inText(one);
    if (Array.isArray(one)) return one.map(walk);
    if (one === null || typeof one !== 'object') return one;
    return Object.fromEntries(Object.entries(one).map(([key, sub]) => [inText(key), walk(sub)]));
  };
  const out = walk(value);
  return { value: out, replacements, changed };
}

/** The placeholders in `masked` that `original` does not hold, each once,
 * in order: the ones the sidecar put in, not a placeholder text the tool
 * wrote itself, which the sidecar passes through. */
export function addedPlaceholders(original: string, masked: string): string[] {
  const before = new Set(original.match(PLACEHOLDER_ALL) ?? []);
  return [...new Set(masked.match(PLACEHOLDER_ALL) ?? [])].filter((one) => !before.has(one));
}

/** Every string and object key in `value`. */
export function textsOf(value: unknown): Set<string> {
  const texts = new Set<string>();
  const walk = (one: unknown): void => {
    if (typeof one === 'string') texts.add(one);
    else if (Array.isArray(one)) one.forEach(walk);
    else if (one !== null && typeof one === 'object') {
      for (const [key, sub] of Object.entries(one)) {
        texts.add(key);
        walk(sub);
      }
    }
  };
  walk(value);
  return texts;
}

/** The field of an `AskUserQuestion` result that holds the user's answers,
 * keyed by question. */
const ANSWERS_FIELD = 'answers';

/** `QuestionEchoError`'s text: fixed, it quotes nothing of the result. */
export const QUESTION_ECHO =
  "Claude's question came back with a value sent in clear in a form nullpii cannot put back";

/** An `AskUserQuestion` result that still holds a real value the user sent
 * in clear, outside the user's own answers and outside any text Claude
 * wrote: the question in a form the mod did not send. The result is
 * withheld rather than masked by detection alone. */
export class QuestionEchoError extends Error {
  constructor() {
    super(QUESTION_ECHO);
    this.name = 'QuestionEchoError';
  }
}

/** A value the user sent in clear, and the placeholder Claude wrote for it. */
export interface SentValue {
  readonly value: string;
  readonly placeholder: string;
}

/** Characters a regular expression reads as syntax. */
const REGEX_SYNTAX = /[.*+?^${}()|[\]\\]/g;

/** `text` with every occurrence of each value in `sent` replaced by its
 * placeholder: longest value first, in one pass, so a shorter value is
 * never found again inside a placeholder or a longer value. */
function maskSentValues(text: string, sent: readonly SentValue[]): string {
  if (sent.length === 0) return text;
  const byValue = new Map(sent.map((one) => [one.value, one.placeholder]));
  const longestFirst = [...byValue.keys()].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(
    longestFirst.map((one) => one.replace(REGEX_SYNTAX, '\\$&')).join('|'),
    'g',
  );
  return text.replace(pattern, (found) => byValue.get(found) ?? found);
}

/**
 * The result of Claude's own `AskUserQuestion` after the user sent real
 * values into its question, as Claude may read it. It does not rest on the
 * sidecar detecting the values again (a short value, or one joined to a
 * word, it may miss):
 *
 * - every text the mod restored in the call (`changed`) is put back, whole,
 *   to the text Claude wrote, so the questions the result echoes and the
 *   keys of its answers read as Claude wrote them;
 * - in the user's answers (the values under `answers`, and anything inside
 *   them), every occurrence of a value in `sent` is replaced by its
 *   placeholder, so labels the user picked, joined by Claude Code (`a, b`),
 *   or text they typed carry no sent value;
 * - anywhere else, a text that still holds a sent value and is not one
 *   Claude wrote (`written`, every text of the masked call) throws
 *   `QuestionEchoError`: the question came back in a form the mod did not
 *   send, and the result is withheld.
 */
export function questionResultAsWritten(
  result: unknown,
  changed: ReadonlyMap<string, string>,
  written: ReadonlySet<string>,
  sent: readonly SentValue[],
): unknown {
  const leaks = (text: string) =>
    !written.has(text) && sent.some((one) => text.includes(one.value));
  // `top`: the result itself; `answers`: its answers, keyed by question;
  // `answer`: what the user answered; `inner`: anything else.
  type Where = 'top' | 'inner' | 'answers' | 'answer';
  const text = (one: string, where: Where): string => {
    if (where === 'answer') return maskSentValues(one, sent);
    const back = changed.get(one) ?? one;
    if (leaks(back)) throw new QuestionEchoError();
    return back;
  };
  const walk = (one: unknown, where: Where): unknown => {
    if (typeof one === 'string') return text(one, where);
    if (Array.isArray(one))
      return one.map((item) => walk(item, where === 'answer' ? 'answer' : 'inner'));
    if (one === null || typeof one !== 'object') return one;
    return Object.fromEntries(
      Object.entries(one).map(([key, sub]) => {
        const next: Where =
          where === 'answers' || where === 'answer'
            ? 'answer'
            : where === 'top' && key === ANSWERS_FIELD
              ? 'answers'
              : 'inner';
        return [text(key, where), walk(sub, next)];
      }),
    );
  };
  return walk(result, 'top');
}

/** One object key the sidecar masked: the key as the tool wrote it, which
 * carries a value of its own, and the key as it came back, which holds the
 * placeholder that stands for that value. */
export interface MaskedKey {
  readonly key: string;
  readonly masked: string;
}

/** `ResultShapeError`'s text: fixed, it quotes nothing of the result, so
 * the mod shows it as written. */
export const RESULT_SHAPE_MISMATCH =
  'the sidecar answered a masked tool result that does not have the shape of the result';

/** A masked tool result that does not have the shape of what the sidecar
 * was sent (`asSent`). The sidecar answers every entry it was sent, each
 * key either as it was or with a placeholder in it, so this is a fault,
 * never a case to work around: no key can be matched, and the result is
 * not let through. */
export class ResultShapeError extends Error {
  constructor() {
    super(RESULT_SHAPE_MISMATCH);
    this.name = 'ResultShapeError';
  }
}

/**
 * `value` as the sidecar receives it inside a request body `{ value }`:
 * through `JSON.stringify`, which drops an `undefined` or function
 * property, turns a `Date` into a string and a `Buffer` into an object of
 * its own. The sidecar's answer has this shape, not the in-memory one, so
 * the mod pairs keys against it. `undefined` when JSON has no form for
 * `value` at all (the body then carries no `value`).
 */
export function asSent(value: unknown): unknown {
  const body = JSON.stringify({ value });
  return (JSON.parse(body) as { value?: unknown }).value;
}

/** The object keys of `value`; `undefined` for anything but a plain object
 * (an array has number keys, which never mask). */
function keysOf(value: unknown): string[] | undefined {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return undefined;
  return Object.keys(value);
}

/** The items of two arrays side by side; `undefined` when neither is an
 * array. Throws `ResultShapeError` when only one is, or their lengths
 * differ. */
function pairedItems(original: unknown, masked: unknown): [unknown, unknown][] | undefined {
  const isList = Array.isArray(original);
  if (!isList && !Array.isArray(masked)) return undefined;
  if (!isList || !Array.isArray(masked) || original.length !== masked.length) {
    throw new ResultShapeError();
  }
  return original.map((one, at) => [one, masked[at]]);
}

/** One entry of an object and the entry the sidecar answered in its place. */
interface PairedEntry {
  readonly key: string;
  readonly value: unknown;
  readonly maskedKey: string;
  readonly maskedValue: unknown;
}

/**
 * The entries of two objects side by side; `undefined` when neither is a
 * plain object. Pairing is by key, never by position: an object lists its
 * integer-like keys (`"1"`, `"2125551234"`) first, in numeric order, so a
 * masked integer-like key (now a placeholder, a string key) moves behind
 * the integer-like keys left as they were. So:
 *
 * 1. a key found in both objects pairs with itself;
 * 2. the keys of `original` missing from `masked` pair, in their order,
 *    with the keys of `masked` missing from `original`, in theirs. The
 *    first list is in the order the sidecar walked `original` (it parsed
 *    the same JSON); the second holds placeholders, never an integer-like
 *    key, so it stays in the order the sidecar inserted them: the same.
 *
 * Throws `ResultShapeError` when only one is a plain object, when the key
 * counts differ, or when a key on the second list holds no placeholder.
 */
function pairedEntries(original: unknown, masked: unknown): PairedEntry[] | undefined {
  const from = keysOf(original);
  const to = keysOf(masked);
  if (from === undefined && to === undefined) return undefined;
  if (from === undefined || to === undefined || from.length !== to.length) {
    throw new ResultShapeError();
  }
  const source = original as Readonly<Record<string, unknown>>;
  const answer = masked as Readonly<Record<string, unknown>>;
  const changedFrom = from.filter((key) => !Object.hasOwn(answer, key));
  const changedTo = to.filter((key) => !Object.hasOwn(source, key));
  if (changedFrom.length !== changedTo.length) throw new ResultShapeError();
  // Each changed key, paired in order, must hold a placeholder its original
  // did not: a placeholder text the tool wrote itself passes through.
  changedFrom.forEach((key, at) => {
    if (addedPlaceholders(key, changedTo[at] as string).length === 0) throw new ResultShapeError();
  });
  return from.map((key) => {
    const at = changedFrom.indexOf(key);
    const maskedKey = at === -1 ? key : (changedTo[at] as string);
    return { key, value: source[key], maskedKey, maskedValue: answer[maskedKey] };
  });
}

/**
 * The object keys of `original` that came back masked in `masked`, in the
 * order the walk meets them. `original` is the value as the sidecar was
 * sent it (`asSent`). Keys pair by name, then the masked ones in their
 * order (`pairedEntries`); where the two do not pair up, `ResultShapeError`
 * is thrown. The values under the keys stay masked.
 */
export function maskedKeys(original: unknown, masked: unknown): readonly MaskedKey[] {
  const items = pairedItems(original, masked);
  if (items !== undefined) return items.flatMap(([one, other]) => maskedKeys(one, other));
  const entries = pairedEntries(original, masked);
  if (entries === undefined) return [];
  return entries.flatMap(({ key, value, maskedKey, maskedValue }) => [
    ...(maskedKey === key ? [] : [{ key, masked: maskedKey }]),
    ...maskedKeys(value, maskedValue),
  ]);
}

/**
 * `masked` with `original`'s object keys put back: every key that was
 * replaced by a placeholder is the key the tool wrote again, and every
 * value stays as it came back masked. A key carries a value of its own, so
 * the caller puts them back only on the user's word. Throws
 * `ResultShapeError` where the two do not walk in step.
 */
export function unmaskKeys(original: unknown, masked: unknown): unknown {
  const items = pairedItems(original, masked);
  if (items !== undefined) return items.map(([one, other]) => unmaskKeys(one, other));
  const entries = pairedEntries(original, masked);
  if (entries === undefined) return masked;
  return Object.fromEntries(
    entries.map(({ key, value, maskedValue }) => [key, unmaskKeys(value, maskedValue)]),
  );
}

/**
 * Where the real values go when the user sends them in clear to a tool
 * outside the policy's `restoreTools`, as the mod's question says it:
 *
 * - `model`: Claude Code runs the tool through a Claude model (`WebSearch`
 *   searches server-side; `WebFetch` hands the page and its prompt to a
 *   model), so that model reads the real values;
 * - `mcp`: an MCP tool, whose server gets the real values and can send them
 *   off this machine;
 * - `user`: `AskUserQuestion`, Claude's own question to the user, shown on
 *   this machine; the user's answer goes back to Claude masked, with the
 *   question as its key (`asksAboutResultKeys`);
 * - `internal`: another of Claude Code's own tools. The mod masks what it
 *   returns, but has no hook on what it hands on inside Claude Code (a
 *   subagent's prompt, a message to another agent), which can reach a
 *   Claude model unmasked;
 * - `unknown`: any other tool; the mod does not know where it sends them.
 */
export type ClearDestination = 'model' | 'mcp' | 'user' | 'internal' | 'unknown';

/** Claude Code's tools that run through a Claude model. */
const MODEL_RUN_TOOLS: ReadonlySet<string> = new Set(['WebFetch', 'WebSearch']);
/** The prefix Claude Code gives every MCP tool's name. */
const MCP_TOOL_PREFIX = 'mcp__';
/** Claude Code's tool that puts Claude's own question to the user. */
const USER_QUESTION_TOOL = 'AskUserQuestion';
/** Claude Code's own tools, other than the ones above, that talk only to
 * Claude, its subagents or the user. */
const INTERNAL_TOOLS: ReadonlySet<string> = new Set([
  'TodoWrite',
  'Agent',
  'Task',
  'ExitPlanMode',
  'SendMessage',
  'Skill',
]);

/**
 * The closed rule for a call to a tool outside `restoreTools` that holds a
 * placeholder the session knows: every such tool is asked about first
 * (Block / Send once / Allow all), Claude Code's own tools and tools the
 * mod does not know included, and this names where the values would go. A
 * shell tool never gets here (its call is refused), and a tool in
 * `restoreTools` gets its values with no question.
 */
export function clearDestination(tool: string): ClearDestination {
  if (MODEL_RUN_TOOLS.has(tool)) return 'model';
  if (tool.startsWith(MCP_TOOL_PREFIX)) return 'mcp';
  if (tool === USER_QUESTION_TOOL) return 'user';
  if (INTERNAL_TOOLS.has(tool)) return 'internal';
  return 'unknown';
}

/**
 * Whether the mod asks before the masked object keys of `tool`'s result
 * go to Claude in clear: yes for every tool outside `restoreTools`, except
 * `AskUserQuestion`. Its result is keyed by the question Claude wrote, so
 * a masked key there is Claude's own placeholder coming back: it goes to
 * Claude masked, as Claude wrote it, with the user's answer under it.
 * Asking would put the real value in what Claude reads (Send once) or
 * lose the user's answer (Block).
 */
export function asksAboutResultKeys(
  tool: string,
  restoreTools: readonly string[] | undefined,
): boolean {
  if (tool === USER_QUESTION_TOOL) return false;
  return restoreTools?.includes(tool) !== true;
}

/** File tools and the argument that names the file they write. */
const WRITE_PATH_FIELDS: Readonly<Record<string, string>> = {
  Write: 'file_path',
  Edit: 'file_path',
  MultiEdit: 'file_path',
  NotebookEdit: 'notebook_path',
};
/** The default location's tail, on a path `normalizePath` produced. */
const POLICY_PATH_TAIL = '/nullpii/config.json';
/** In a shell command: a `nullpii` directory, a `config.json`, the
 * variable that names another policy file. Best effort, as any reading of
 * a shell command is. */
const NULLPII_WORD = /nullpii/i;
const CONFIG_FILE_WORD = /config\.json/i;
const POLICY_VARIABLE = /NULLPII_CONFIG/i;
/** The sidecar route that replaces the policy, which the token alone
 * reaches; the mod also notices a change it did not make (`register.ts`). */
const POLICY_ROUTE = /sidecar\/+policy/i;
/** A path that starts at a root: `/`, `~`, or a Windows drive. */
const ABSOLUTE_PATH = /^(?:[\\/~]|[A-Za-z]:)/;

/**
 * `path` in one comparable form: forward slashes, `.` and `..` segments
 * and repeated separators resolved, lower case (macOS and Windows disks
 * ignore case by default). A relative path is resolved against `cwd`.
 */
function normalizePath(path: string, cwd: string | undefined): string {
  const joined = ABSOLUTE_PATH.test(path) || cwd === undefined ? path : `${cwd}/${path}`;
  const segments: string[] = [];
  for (const segment of joined.replace(/\\/g, '/').split('/')) {
    if (segment === '..') segments.pop();
    else if (segment !== '' && segment !== '.') segments.push(segment);
  }
  const lead = joined.startsWith('/') || joined.startsWith('\\') ? '/' : '';
  return (lead + segments.join('/')).toLowerCase();
}

/**
 * Whether a tool call may change the masking-policy file: a file tool
 * writing `policyFile` or any `…/nullpii/config.json` (case, `./`, `../`
 * and repeated separators ignored; a relative path is resolved against
 * `cwd`), or a shell command that names a `nullpii` directory together
 * with a `config.json`, the policy file, or `NULLPII_CONFIG`. Such a call
 * is put to the user, so text Claude read cannot quietly loosen what gets
 * masked. Best effort: a command can reach the file in ways no pattern
 * names.
 */
export function touchesPolicyFile(
  tool: string,
  input: unknown,
  policyFile: string | undefined,
  cwd?: string,
): boolean {
  if (input === null || typeof input !== 'object') return false;
  const args = input as Readonly<Record<string, unknown>>;
  if (tool === 'Bash') {
    const command = typeof args.command === 'string' ? args.command : '';
    return commandNamesPolicy(command, policyFile);
  }
  const field = WRITE_PATH_FIELDS[tool];
  const path = field === undefined ? undefined : args[field];
  if (typeof path !== 'string') return false;
  const target = normalizePath(path, cwd);
  return (
    target.endsWith(POLICY_PATH_TAIL) ||
    (policyFile !== undefined && target === normalizePath(policyFile, undefined))
  );
}

function commandNamesPolicy(command: string, policyFile: string | undefined): boolean {
  if (POLICY_VARIABLE.test(command) || POLICY_ROUTE.test(command)) return true;
  if (NULLPII_WORD.test(command) && CONFIG_FILE_WORD.test(command)) return true;
  return policyFile !== undefined && command.toLowerCase().includes(policyFile.toLowerCase());
}

/** The masking policy the sidecar runs with (`GET /v1/sidecar/status`). */
export interface Policy {
  /** Changes with every change of the policy, the same for the same policy. */
  version?: string;
  file: string;
  loaded: boolean;
  config: Readonly<Record<string, unknown>>;
  /** The categories left readable, defaults included (absent from an
   * older sidecar). */
  disabledCategories?: readonly string[];
  /** The mode of every category: `mask`, `ask` or `off` (absent from an
   * older sidecar). */
  categories?: Readonly<Record<string, string>>;
  restoreTools: readonly string[];
}

const LABEL_PREFIX = 'private_';

export interface Counts {
  masked: number;
  restored: number;
  /** Placeholders kept in calls to tools outside `restoreTools`. */
  held: number;
  byLabel: Record<string, number>;
  /** Values sent in clear on the user's word, by the tool they went to and
   * their category. Never a value or a short form of one: the report's text
   * may reach the model. */
  sent: Record<string, Record<string, number>>;
}

export function emptyCounts(): Counts {
  // `sent` is keyed by tool names, which a model picks: no prototype to hit.
  return { masked: 0, restored: 0, held: 0, byLabel: {}, sent: Object.create(null) };
}

/** Count a value sent in clear on the user's word, under its tool and
 * category. */
export function addSent(counts: Counts, tool: string, category: string): void {
  let byCategory = counts.sent[tool];
  if (byCategory === undefined) {
    byCategory = Object.create(null);
    counts.sent[tool] = byCategory;
  }
  byCategory[category] = (byCategory[category] ?? 0) + 1;
}

/** Add one sidecar sanitize response to the session's counts. */
export function addMasked(
  counts: Counts,
  captured: number,
  byLabel: Readonly<Record<string, number>>,
): void {
  counts.masked += captured;
  for (const [label, n] of Object.entries(byLabel)) {
    counts.byLabel[label] = (counts.byLabel[label] ?? 0) + n;
  }
}

function shortLabel(label: string): string {
  return label.startsWith(LABEL_PREFIX) ? label.slice(LABEL_PREFIX.length) : label;
}

/** Labels by count, largest first: `person 5 · email 3`. */
function formatLabels(byLabel: Readonly<Record<string, number>>, limit: number): string {
  return Object.entries(byLabel)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([label, n]) => `${shortLabel(label)} ${n}`)
    .join(' · ');
}

/** The one line shown above the prompt. Blocking comes first: a paused
 * nullpii whose sidecar is not up sends nothing anyway (fail closed). */
export function formatBand(counts: Counts, problem: string | undefined, paused: boolean): string {
  if (problem !== undefined) return `blocking: ${problem}`;
  if (paused) return 'paused: everything you send reaches Claude unmasked';
  if (counts.masked === 0) return 'nothing masked yet';
  const labels = formatLabels(counts.byLabel, 4);
  return `${counts.masked} masked (${labels}) · ${counts.restored} restored to local tools`;
}

/** The categories under `mode`, by short name, or `none`. */
function categoriesIn(modes: Readonly<Record<string, string>>, mode: string): string {
  const names = Object.keys(modes)
    .filter((c) => modes[c] === mode)
    .map(shortName);
  return names.length > 0 ? names.join(', ') : 'none';
}

/** `threshold` and `categoryThresholds` as set, or `defaults`. */
function formatCuts(config: Readonly<Record<string, unknown>>): string {
  const parts: string[] = [];
  if (typeof config.threshold === 'number') parts.push(`all ${config.threshold}`);
  const per = config.categoryThresholds;
  if (typeof per === 'object' && per !== null) {
    for (const [category, cut] of Object.entries(per))
      parts.push(`${shortName(category)} ${String(cut)}`);
  }
  return parts.length > 0 ? `${parts.join(', ')} (others at their defaults)` : 'defaults';
}

/** The policy's `urlAllowlist`, in short. */
function formatUrlAllowlist(allowlist: unknown): string {
  if (allowlist === 'none') return 'none (every URL masked)';
  if (typeof allowlist !== 'object' || allowlist === null) return 'the built-in hosts';
  const { hosts, replaceDefaults } = allowlist as { hosts?: unknown; replaceDefaults?: unknown };
  const named =
    typeof hosts === 'object' && hosts !== null
      ? Object.entries(hosts).map(([h, release]) => `${h} ${String(release)}`)
      : [];
  if (replaceDefaults === true) return named.length > 0 ? `only ${named.join(', ')}` : 'none';
  return named.length > 0 ? `the built-in hosts, plus ${named.join(', ')}` : 'the built-in hosts';
}

/** The system prompt section that tells Claude what the placeholders are:
 * values to copy as they are, which `restoreTools` (unknown before the
 * sidecar answers) fill in, and which no shell command gets. */
export function placeholderGuide(restoreTools: readonly string[] | undefined): string {
  return [
    'nullpii masks personal data and secrets in this session before you read them.',
    "Text such as `{{PII_PRIVATE_EMAIL_<n>_<hex>}}` is a placeholder for a real value that stays on the user's machine.",
    'Use a placeholder as you would use its value, and copy it exactly and in full, hex part included.',
    'Do not ask the user for the real value, and do not tell them it is hidden: nullpii shows them the real values.',
    restoringTools(restoreTools),
    otherTools(restoreTools),
    'A call the user does not agree to is refused, and so is every such call when no one can answer (claude -p) unless the user allowed all for the session; a placeholder nothing stands behind is passed as written.',
    'A shell command that holds a placeholder is refused.',
  ].join(' ');
}

/** Tools the guide names as examples of the ones that ask, besides MCP
 * tools: each only while `restoreTools` does not list it. */
const GUIDE_EXAMPLE_TOOLS: readonly string[] = [
  'TodoWrite',
  'Agent',
  'AskUserQuestion',
  'WebFetch',
];

/** The guide's sentence on the tools outside `restoreTools`, with examples
 * that are true for this policy. */
function otherTools(restoreTools: readonly string[] | undefined): string {
  const examples = GUIDE_EXAMPLE_TOOLS.filter((tool) => restoreTools?.includes(tool) !== true);
  const named = [...examples, 'MCP tools'].join(', ');
  return `Every other tool, Claude Code's own included (such as ${named}), gets the real values only when the user agrees in a dialog nullpii puts to them.`;
}

function restoringTools(restoreTools: readonly string[] | undefined): string {
  if (restoreTools === undefined) {
    return 'The file tools that run on this machine put the real values back before they run, so a file they write holds the real values.';
  }
  if (restoreTools.length === 0) return 'No tool gets the real values back on its own.';
  return `These tools put the real values back before they run: ${restoreTools.join(', ')}. So a file they write holds the real values.`;
}

/** The categories of `policy`, grouped by mode, on one line. An older
 * sidecar reports no per-category mode: then the readable ones alone. */
function formatCategories(policy: Policy): string {
  const modes = policy.categories;
  if (modes === undefined) {
    const disabled = policy.disabledCategories ?? policy.config.disabledCategories;
    const off = Array.isArray(disabled) && disabled.length > 0 ? disabled.join(', ') : 'none';
    return `Left readable: ${off}`;
  }
  return [
    `Masked: ${categoriesIn(modes, 'mask')}`,
    `Ask first in your prompts: ${categoriesIn(modes, 'ask')}`,
    `Left readable: ${categoriesIn(modes, 'off')}`,
  ].join(' · ');
}

/** The policy file and what it sets, on one line. */
function formatSettings(policy: Policy): string {
  return [
    `Policy file: ${policy.file} (${policy.loaded ? 'loaded' : 'not present: built-in defaults'})`,
    `Confidence cuts: ${formatCuts(policy.config)}`,
    `URLs left readable: ${formatUrlAllowlist(policy.config.urlAllowlist)}`,
    `Tools that get real values back: ${policy.restoreTools.join(', ')}`,
  ].join(' · ');
}

/** How both the status and a policy change end: where the commands are. */
const PII_MENU_POINTER = 'Type /pii for the menu, or /pii help for every command';

/** The policy lines of the reply to a change: the categories by mode, the
 * settings, and the pointer to the menu. */
export function formatPolicy(policy: Policy | undefined): string[] {
  if (policy === undefined) return ['Policy: unknown (the sidecar has not answered)'];
  return [formatCategories(policy), formatSettings(policy), PII_MENU_POINTER];
}

/** The report's lines of values sent in clear on the user's word: one per
 * tool and category with its count. None while none were sent. */
function formatSent(counts: Counts): string[] {
  return Object.entries(counts.sent)
    .sort((a, b) => a[0].localeCompare(b[0]))
    .flatMap(([tool, byCategory]) =>
      Object.entries(byCategory)
        .sort((a, b) => a[0].localeCompare(b[0]))
        .map(
          ([category, n]) => `Sent in clear on your word: ${tool} · ${shortName(category)} ${n}`,
        ),
    );
}

/** The `/pii` status: the state, the session's counts on one line, the
 * values sent in clear one line per tool and category, the categories by
 * mode, the policy, and where the commands are. Short on purpose: `/pii
 * help` lists them. */
export function formatReport(
  counts: Counts,
  problem: string | undefined,
  policy: Policy | undefined,
  paused: boolean,
): string {
  const labels = formatLabels(counts.byLabel, Number.POSITIVE_INFINITY);
  return [
    problem !== undefined
      ? `Status: blocking (${problem})`
      : paused
        ? 'Status: paused (everything you send reaches Claude unmasked)'
        : 'Status: on',
    [
      `Masked before Claude read them: ${counts.masked}${labels === '' ? '' : ` (${labels})`}`,
      `Real values put back into local tool calls: ${counts.restored}`,
      `Placeholders kept in calls to other tools: ${counts.held}`,
    ].join(' · '),
    ...formatSent(counts),
    ...(policy === undefined
      ? ['Policy: unknown (the sidecar has not answered)']
      : [formatCategories(policy), formatSettings(policy)]),
    PII_MENU_POINTER,
  ].join('\n');
}
