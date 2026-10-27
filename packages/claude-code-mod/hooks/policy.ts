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
}

export function emptyCounts(): Counts {
  return { masked: 0, restored: 0, held: 0, byLabel: {} };
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
    'Every other tool, such as a web fetch or an MCP tool, gets the placeholder itself, never the value.',
    'A shell command that holds a placeholder is refused.',
  ].join(' ');
}

function restoringTools(restoreTools: readonly string[] | undefined): string {
  if (restoreTools === undefined) {
    return 'The file tools that run on this machine put the real values back before they run, so a file they write holds the real values.';
  }
  if (restoreTools.length === 0) return 'No tool gets the real values back.';
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

/** The `/pii` status: the state, the session's counts on one line, the
 * categories by mode, the policy, and where the commands are. Short on
 * purpose: `/pii help` lists them. */
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
    ...(policy === undefined
      ? ['Policy: unknown (the sidecar has not answered)']
      : [formatCategories(policy), formatSettings(policy)]),
    PII_MENU_POINTER,
  ].join('\n');
}
