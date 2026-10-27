// SPDX-License-Identifier: Apache-2.0

/**
 * The `/pii` command's arguments: what a user can change about what
 * nullpii masks, read into a new policy file for the sidecar
 * (`PUT /v1/sidecar/policy`), and the one-line descriptions `/pii help`
 * and the command's menu entries share. Pure functions, no I/O.
 */

import type { Policy } from './policy.ts';

/** What happens to one category (the policy file's `categories`). */
export type Mode = 'mask' | 'ask' | 'off';

/** The word each category command takes, and the mode of the policy file it
 * sets: `allow` leaves a category readable, which the file calls `off`. */
const VERB_MODES: Readonly<Record<string, Mode>> = { mask: 'mask', ask: 'ask', allow: 'off' };
/** The command word of each mode, for a command the menu builds. */
export const MODE_VERBS: Readonly<Record<Mode, string>> = {
  mask: 'mask',
  ask: 'ask',
  off: 'allow',
};

/** Every category, by the short name `/pii` takes. */
const CATEGORY_NAMES: Readonly<Record<string, string>> = {
  person: 'private_person',
  email: 'private_email',
  phone: 'private_phone',
  address: 'private_address',
  url: 'private_url',
  ip: 'private_ip',
  mac: 'private_mac',
  location: 'private_geolocation',
  passport: 'private_passport',
  license: 'private_driver_license',
  vehicle: 'private_vehicle_id',
  account: 'account_number',
  secret: 'secret',
  date: 'private_date',
  organization: 'private_organization',
  occupation: 'private_occupation',
  demographic: 'private_demographic',
  sensitive: 'private_sensitive',
  title: 'private_title',
};

const ALL_CATEGORIES: readonly string[] = Object.values(CATEGORY_NAMES);

/** Whether `label` is one of the policy's known category identifiers. */
export function isPiiCategoryLabel(label: string): boolean {
  return ALL_CATEGORIES.includes(label);
}

/** The categories by the name `/pii` takes, in the order the menu lists
 * them and the order they read in. */
export const CATEGORY_SHORT_NAMES: readonly string[] = Object.keys(CATEGORY_NAMES);

/** The presets: `agent` is nullpii's default (what is dangerous to hand to
 * a model), `secrets` masks secrets alone, `all` every category. */
const PRESETS = ['agent', 'secrets', 'all'] as const;
type Preset = (typeof PRESETS)[number];

/** One `/pii` command: what the person types after `/pii`, and the one
 * line that says what it does. `/pii help` prints the line, and the
 * command's menu entry says the same text, so there is one copy. */
export interface PiiCommandLine {
  /** The arguments, as typed (`''` for `/pii` itself). */
  readonly args: string;
  readonly description: string;
}

/** Every `/pii` command, in the order `/pii help` lists them, and the one
 * place their descriptions live. */
export const PII_COMMANDS: readonly PiiCommandLine[] = [
  {
    args: '',
    description: 'Open this menu: pick a command, and the same code runs as if you typed it',
  },
  { args: 'status', description: 'Show what nullpii masked, and the policy in effect' },
  {
    args: 'doctor',
    description: 'Check the sidecar, release, model, backend, token, policy and mod',
  },
  {
    args: 'try <text>',
    description: 'Preview masking locally; keep only the masked sample and close its session',
  },
  {
    args: 'preset agent',
    description: 'Preset: agent (the default: names, contacts, ids and secrets)',
  },
  {
    args: 'preset secrets',
    description: 'Preset: secrets only (keys, tokens, passwords, private keys)',
  },
  { args: 'preset all', description: 'Preset: everything (every category masked)' },
  { args: 'mask <category…>', description: 'Mask a category: the ones you choose' },
  {
    args: 'ask <category…>',
    description: 'Ask first about a category: ask about each value in your prompt',
  },
  { args: 'allow <category…>', description: 'Leave a category readable: the ones you choose' },
  { args: 'reset', description: 'Reset to the default (the agent preset)' },
  { args: 'pause', description: 'Pause masking for this session' },
  { args: 'resume', description: 'Turn masking back on' },
  { args: 'help', description: 'Help: every command and what it does' },
];

/** The description of the command `/pii <args>` takes: its `/pii help`
 * row and the text of its menu entry. Fails loud on an argument no
 * command takes, which only the mod's own menu can ask for. */
export function piiCommandDescription(args: string): string {
  const line = PII_COMMANDS.find((c) => c.args === args);
  if (line === undefined) throw new Error(`no /pii command takes "${args}"`);
  return line.description;
}

/** The width of the widest command, so the help table's columns line up. */
const HELP_COLUMN = Math.max(...PII_COMMANDS.map((c) => c.args.length));

/** The `/pii help` table: every command with the line that describes it. */
export function formatPiiHelp(): string {
  return [
    'The /pii commands:',
    ...PII_COMMANDS.map((c) => `  /pii ${c.args.padEnd(HELP_COLUMN)}  ${c.description}`),
    `Categories: ${CATEGORY_SHORT_NAMES.join(', ')}`,
  ].join('\n');
}

/** The usage line `/pii` answers an unreadable argument with. */
export const PII_USAGE = `Usage: /pii · /pii status|doctor · /pii try <text> · /pii preset agent|secrets|all · /pii mask|ask|allow <category…> · /pii reset · /pii pause|resume · /pii help. Categories: ${CATEGORY_SHORT_NAMES.join(', ')}`;

export type PiiCommand =
  | { readonly kind: 'menu' }
  | { readonly kind: 'status' }
  | { readonly kind: 'doctor' }
  | { readonly kind: 'try'; readonly sample: string }
  | { readonly kind: 'help' }
  | { readonly kind: 'preset'; readonly preset: Preset }
  | { readonly kind: 'set'; readonly mode: Mode; readonly categories: readonly string[] }
  | { readonly kind: 'pause' }
  | { readonly kind: 'resume' }
  | { readonly kind: 'error'; readonly message: string };

/** Read `/pii`'s arguments. Category names are the short ones
 * (`CATEGORY_NAMES`) or the full ones (`private_url`); `reset` is the
 * `agent` preset; `pause` and `resume` stand alone. No arguments at all
 * (`/pii`) is the menu. */
export function parsePiiCommand(args: string): PiiCommand {
  const input = args.trimStart();
  const separator = input.search(/\s/);
  const first = (separator === -1 ? input : input.slice(0, separator)).toLowerCase();
  if (first === 'try') {
    return { kind: 'try', sample: separator === -1 ? '' : input.slice(separator + 1) };
  }
  const words = args
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter((w) => w !== '');
  const [verb, ...rest] = words;
  if (verb === undefined) return { kind: 'menu' };
  if (verb === 'status' && rest.length === 0) return { kind: 'status' };
  if (verb === 'doctor' && rest.length === 0) return { kind: 'doctor' };
  if (verb === 'help' && rest.length === 0) return { kind: 'help' };
  if (verb === 'reset' && rest.length === 0) return { kind: 'preset', preset: 'agent' };
  if (verb === 'pause' && rest.length === 0) return { kind: 'pause' };
  if (verb === 'resume' && rest.length === 0) return { kind: 'resume' };
  if (verb === 'preset') {
    const preset = PRESETS.find((p) => p === rest[0]);
    if (preset === undefined || rest.length !== 1) return { kind: 'error', message: PII_USAGE };
    return { kind: 'preset', preset };
  }
  const mode = Object.hasOwn(VERB_MODES, verb) ? VERB_MODES[verb] : undefined;
  if (mode === undefined || rest.length === 0) return { kind: 'error', message: PII_USAGE };
  const categories: string[] = [];
  for (const word of rest) {
    const category = CATEGORY_NAMES[word] ?? (ALL_CATEGORIES.includes(word) ? word : undefined);
    if (category === undefined) {
      return { kind: 'error', message: `Unknown category "${word}". ${PII_USAGE}` };
    }
    categories.push(category);
  }
  return { kind: 'set', mode, categories };
}

/** The policy file `config` with `command` applied. A preset replaces the
 * category settings (`disabledCategories` and `categories`) and keeps the
 * rest (thresholds, URL allowlist, restore tools); `set` changes only the
 * categories it names. */
export function applyPiiCommand(
  config: Readonly<Record<string, unknown>>,
  command: Exclude<
    PiiCommand,
    | { kind: 'menu' }
    | { kind: 'status' }
    | { kind: 'doctor' }
    | { kind: 'try' }
    | { kind: 'help' }
    | { kind: 'pause' }
    | { kind: 'resume' }
    | { kind: 'error' }
  >,
): Record<string, unknown> {
  const { disabledCategories, categories, ...rest } = config;
  if (command.kind === 'preset') {
    if (command.preset === 'agent') return rest;
    const mode = (c: string): Mode => (command.preset === 'all' || c === 'secret' ? 'mask' : 'off');
    return { ...rest, categories: Object.fromEntries(ALL_CATEGORIES.map((c) => [c, mode(c)])) };
  }
  const current =
    typeof categories === 'object' && categories !== null
      ? (categories as Record<string, Mode>)
      : {};
  const next = { ...current };
  for (const category of command.categories) next[category] = command.mode;
  return {
    ...rest,
    ...(disabledCategories !== undefined && { disabledCategories }),
    categories: next,
  };
}

/** Policy keys whose change is spelled out, with values, below. */
const SPELLED_OUT: ReadonlySet<string> = new Set([
  'categories',
  'disabledCategories',
  'restoreTools',
  'threshold',
  'categoryThresholds',
  'urlAllowlist',
]);

/** How readable a URL on a host stays, least first; a host the policy
 * does not name counts as the most readable, so a change is never
 * reported as safer than it may be. */
const URL_RELEASE_RANK: Readonly<Record<string, number>> = { mask: 0, host: 1, full: 2 };
const UNNAMED_HOST_RANK = 2;
/** Hosts listed by name in a change; the rest are counted. */
const MAX_HOSTS_LISTED = 5;

type Config = Readonly<Record<string, unknown>>;

/**
 * What changed from `before` to `now`, for the user: category modes, the
 * tools that get real values back, the confidence cuts and the URL hosts
 * with their old and new values, and any other setting by name. The values
 * shown are validated policy (modes, tool names, numbers in [0, 1], DNS
 * host names), never text from a prompt or a file.
 */
export function describePolicyChange(before: Policy, now: Policy): string {
  const parts: string[] = [];
  const was = before.categories ?? {};
  const is = now.categories ?? {};
  for (const category of [...new Set([...Object.keys(was), ...Object.keys(is)])].sort()) {
    if (was[category] !== is[category]) {
      parts.push(`${shortName(category)} ${was[category] ?? 'unset'} → ${is[category] ?? 'unset'}`);
    }
  }
  const added = now.restoreTools.filter((t) => !before.restoreTools.includes(t));
  const removed = before.restoreTools.filter((t) => !now.restoreTools.includes(t));
  if (added.length > 0) parts.push(`real values now go back into ${added.join(', ')}`);
  if (removed.length > 0) parts.push(`no longer into ${removed.join(', ')}`);
  parts.push(...cutChanges(before.config, now.config).map((c) => c.text));
  parts.push(
    ...urlChanges(before.config, now.config).flatMap((c) => (c.text === '' ? [] : [c.text])),
  );
  const keys = new Set([...Object.keys(before.config), ...Object.keys(now.config)]);
  const other = [...keys]
    .filter((k) => !SPELLED_OUT.has(k))
    .filter((k) => JSON.stringify(before.config[k]) !== JSON.stringify(now.config[k]))
    .sort();
  if (other.length > 0) parts.push(`${other.join(', ')} changed`);
  return parts.length > 0 ? parts.join('; ') : 'settings changed';
}

/**
 * Why the change from `before` to `now` may mask less, in plain words, or
 * nothing when it does not: a category left readable, tools that get real
 * values, a confidence cut raised or reset, URLs made more readable. A
 * change whose effect depends on a default counts as masking less.
 */
export function policyLoosening(before: Policy, now: Policy): string[] {
  const reasons: string[] = [];
  const was = before.categories ?? {};
  const is = now.categories ?? {};
  const opened = Object.keys(is).filter((c) => is[c] === 'off' && was[c] !== 'off');
  if (opened.length > 0) reasons.push(`${opened.map(shortName).join(', ')} left readable`);
  const added = now.restoreTools.filter((t) => !before.restoreTools.includes(t));
  if (added.length > 0) reasons.push(`real values go into ${added.join(', ')}`);
  if (cutChanges(before.config, now.config).some((c) => c.less)) {
    reasons.push('a confidence cut is higher or back to its default, so detections can be dropped');
  }
  if (urlChanges(before.config, now.config).some((c) => c.less)) {
    reasons.push('URLs on some hosts become more readable');
  }
  return reasons;
}

interface Change {
  readonly text: string;
  /** May mask less. */
  readonly less: boolean;
}

/** `threshold` and `categoryThresholds`, old → new. Only a cut lowered
 * from one number to another surely masks more. */
function cutChanges(before: Config, now: Config): Change[] {
  const out: Change[] = [];
  const cut = (name: string, was: number | undefined, is: number | undefined) => {
    if (was === is) return;
    const lower = was !== undefined && is !== undefined && is < was;
    out.push({ text: `${name} ${was ?? 'default'} → ${is ?? 'default'}`, less: !lower });
  };
  cut('threshold', numberOf(before.threshold), numberOf(now.threshold));
  const was = numbersOf(before.categoryThresholds);
  const is = numbersOf(now.categoryThresholds);
  for (const category of [...new Set([...Object.keys(was), ...Object.keys(is)])].sort()) {
    cut(`${shortName(category)} cut`, was[category], is[category]);
  }
  return out;
}

/** `urlAllowlist`, old → new: all URLs masked or not, the hosts whose
 * release changed (a few by name), and the built-in readable hosts. */
function urlChanges(before: Config, now: Config): Change[] {
  const was = before.urlAllowlist;
  const is = now.urlAllowlist;
  if (JSON.stringify(was) === JSON.stringify(is)) return [];
  if (is === 'none') return [{ text: 'every URL masked', less: false }];
  const out: Change[] = [];
  if (was === 'none') out.push({ text: 'URLs no longer all masked', less: true });
  const wasHosts = hostsOf(was);
  const isHosts = hostsOf(is);
  const hosts = [...new Set([...Object.keys(wasHosts), ...Object.keys(isHosts)])]
    .sort()
    .filter((h) => wasHosts[h] !== isHosts[h]);
  const rank = (release: string | undefined) =>
    release === undefined ? UNNAMED_HOST_RANK : (URL_RELEASE_RANK[release] ?? UNNAMED_HOST_RANK);
  for (const [i, h] of hosts.entries()) {
    const less = rank(isHosts[h]) > rank(wasHosts[h]) || isHosts[h] === undefined;
    const text =
      i < MAX_HOSTS_LISTED
        ? `URLs on ${h} ${wasHosts[h] ?? 'default'} → ${isHosts[h] ?? 'default'}`
        : '';
    out.push({ text, less });
  }
  if (hosts.length > MAX_HOSTS_LISTED) {
    out.push({ text: `${hosts.length - MAX_HOSTS_LISTED} more URL hosts changed`, less: false });
  }
  const wasReplaces = replacesDefaults(was);
  const isReplaces = replacesDefaults(is);
  if (wasReplaces !== isReplaces) {
    out.push(
      isReplaces
        ? { text: 'built-in readable URL hosts dropped', less: false }
        : { text: 'built-in readable URL hosts back', less: true },
    );
  }
  return out.filter((c) => c.text !== '' || c.less);
}

function numberOf(value: unknown): number | undefined {
  return typeof value === 'number' ? value : undefined;
}

function numbersOf(value: unknown): Record<string, number> {
  if (typeof value !== 'object' || value === null) return {};
  const out: Record<string, number> = {};
  for (const [k, v] of Object.entries(value)) if (typeof v === 'number') out[k] = v;
  return out;
}

function hostsOf(allowlist: unknown): Record<string, string> {
  if (typeof allowlist !== 'object' || allowlist === null) return {};
  const hosts = (allowlist as { hosts?: unknown }).hosts;
  if (typeof hosts !== 'object' || hosts === null) return {};
  const out: Record<string, string> = {};
  for (const [h, release] of Object.entries(hosts))
    if (typeof release === 'string') out[h] = release;
  return out;
}

function replacesDefaults(allowlist: unknown): boolean {
  return (
    typeof allowlist === 'object' &&
    allowlist !== null &&
    (allowlist as { replaceDefaults?: unknown }).replaceDefaults === true
  );
}

/** The short name of `category` (`private_url` → `url`). */
export function shortName(category: string): string {
  return Object.entries(CATEGORY_NAMES).find(([, full]) => full === category)?.[0] ?? category;
}

/** The categories of the placeholders in `text` whose mode is `ask`,
 * with each placeholder once. A placeholder names its category in upper
 * case: `{{PII_PRIVATE_URL_0_…}}` is `private_url`. */
export function placeholdersToAsk(
  text: string,
  modes: Readonly<Record<string, string>> | undefined,
): { readonly placeholder: string; readonly category: string }[] {
  if (modes === undefined) return [];
  const found = new Map<string, string>();
  for (const m of text.matchAll(/\{\{PII_([A-Z_]+?)_\d+_[0-9a-f]+\}\}/g)) {
    const category = (m[1] ?? '').toLowerCase();
    if (modes[category] === 'ask') found.set(m[0], category);
  }
  return [...found].map(([placeholder, category]) => ({ placeholder, category }));
}
