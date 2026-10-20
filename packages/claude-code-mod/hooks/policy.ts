// SPDX-License-Identifier: Apache-2.0
//
// Pure helpers for the nullpii mod: which tool arguments are sent for a
// restore, which calls touch the masking-policy file, and how the counts
// and the policy are shown. No mods API calls live here, so
// `claude plugin validate` reads every `$` call from register.ts.

/**
 * Arguments that may get their real values back, per built-in tool that
 * acts on this machine. Whether a tool gets any is not decided here: the
 * sidecar restores only into the tools its policy lists (`restoreTools`
 * in the shared config file), so the mod and the gateway follow one list.
 * A tool missing from this table sends every argument it has.
 */
export const RESTORE_FIELDS: Readonly<Record<string, readonly string[]>> = {
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
/** A path that starts at a root: `/`, `~`, or a Windows drive. */
const ABSOLUTE_PATH = /^(?:[\\/~]|[A-Za-z]:)/;

/**
 * `path` in one comparable form: forward slashes, `.` and `..` segments
 * and repeated separators resolved, lower case (macOS and Windows disks
 * ignore case by default). A relative path is resolved against `cwd`.
 */
export function normalizePath(path: string, cwd: string | undefined): string {
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
  if (POLICY_VARIABLE.test(command)) return true;
  if (NULLPII_WORD.test(command) && CONFIG_FILE_WORD.test(command)) return true;
  return policyFile !== undefined && command.toLowerCase().includes(policyFile.toLowerCase());
}

/** The masking policy the sidecar runs with (`GET /v1/sidecar/status`). */
export interface Policy {
  file: string;
  loaded: boolean;
  config: Readonly<Record<string, unknown>>;
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
export function formatLabels(byLabel: Readonly<Record<string, number>>, limit: number): string {
  return Object.entries(byLabel)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([label, n]) => `${shortLabel(label)} ${n}`)
    .join(' · ');
}

/** The one line shown above the prompt. */
export function formatBand(counts: Counts, problem: string | undefined): string {
  if (problem !== undefined) return `nullpii · blocking: ${problem}`;
  if (counts.masked === 0) return 'nullpii · on · nothing masked yet';
  const labels = formatLabels(counts.byLabel, 4);
  return `nullpii · ${counts.masked} masked (${labels}) · ${counts.restored} restored to local tools`;
}

/** The policy lines of the `/pii` reply. */
export function formatPolicy(policy: Policy | undefined): string[] {
  if (policy === undefined) return ['Policy: unknown (the sidecar has not answered)'];
  const disabled = policy.config.disabledCategories;
  const off = Array.isArray(disabled) && disabled.length > 0 ? disabled.join(', ') : 'none';
  return [
    `Policy file: ${policy.file} (${policy.loaded ? 'loaded' : 'not present: built-in defaults'})`,
    `Categories turned off: ${off}`,
    `Tools that get real values back: ${policy.restoreTools.join(', ')}`,
    'Changes to the file apply when nullpii-gateway restarts.',
  ];
}

/** The `/pii` command's reply. */
export function formatReport(
  counts: Counts,
  problem: string | undefined,
  policy: Policy | undefined,
): string {
  const lines = [
    problem === undefined ? 'Status: on' : `Status: blocking (${problem})`,
    `Masked before Claude read them: ${counts.masked}`,
    `Real values put back into local tool calls: ${counts.restored}`,
    `Placeholders kept in calls to other tools: ${counts.held}`,
  ];
  const labels = formatLabels(counts.byLabel, Number.POSITIVE_INFINITY);
  if (labels !== '') lines.push(`By type: ${labels}`);
  return [...lines, ...formatPolicy(policy)].join('\n');
}
