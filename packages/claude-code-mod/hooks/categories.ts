// SPDX-License-Identifier: Apache-2.0

/**
 * The `/pii` command's arguments: what a user can change about what
 * nullpii masks, read into a new policy file for the sidecar
 * (`PUT /v1/sidecar/policy`). Pure functions, no I/O.
 */

import type { Policy } from './policy.ts';

/** What happens to one category (the policy file's `categories`). */
export type Mode = 'mask' | 'ask' | 'off';

const MODES: ReadonlySet<string> = new Set(['mask', 'ask', 'off']);

/** Every category, by the short name `/pii` takes. */
export const CATEGORY_NAMES: Readonly<Record<string, string>> = {
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

/** The presets: `agent` is nullpii's default (what is dangerous to hand to
 * a model), `secrets` masks secrets alone, `all` every category. */
export const PRESETS = ['agent', 'secrets', 'all'] as const;
export type Preset = (typeof PRESETS)[number];

/** The usage line `/pii` answers an unreadable argument with. */
export const PII_USAGE = `Usage: /pii · /pii preset agent|secrets|all · /pii mask|ask|off <category…> · /pii reset. Categories: ${Object.keys(CATEGORY_NAMES).join(', ')}`;

export type PiiCommand =
  | { readonly kind: 'status' }
  | { readonly kind: 'preset'; readonly preset: Preset }
  | { readonly kind: 'set'; readonly mode: Mode; readonly categories: readonly string[] }
  | { readonly kind: 'error'; readonly message: string };

/** Read `/pii`'s arguments. Category names are the short ones
 * (`CATEGORY_NAMES`) or the full ones (`private_url`); `reset` is the
 * `agent` preset. */
export function parsePiiCommand(args: string): PiiCommand {
  const words = args
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter((w) => w !== '');
  const [verb, ...rest] = words;
  if (verb === undefined) return { kind: 'status' };
  if (verb === 'reset' && rest.length === 0) return { kind: 'preset', preset: 'agent' };
  if (verb === 'preset') {
    const preset = PRESETS.find((p) => p === rest[0]);
    if (preset === undefined || rest.length !== 1) return { kind: 'error', message: PII_USAGE };
    return { kind: 'preset', preset };
  }
  if (!MODES.has(verb) || rest.length === 0) return { kind: 'error', message: PII_USAGE };
  const categories: string[] = [];
  for (const word of rest) {
    const category = CATEGORY_NAMES[word] ?? (ALL_CATEGORIES.includes(word) ? word : undefined);
    if (category === undefined) {
      return { kind: 'error', message: `Unknown category "${word}". ${PII_USAGE}` };
    }
    categories.push(category);
  }
  return { kind: 'set', mode: verb as Mode, categories };
}

/** The policy file `config` with `command` applied. A preset replaces the
 * category settings (`disabledCategories` and `categories`) and keeps the
 * rest (thresholds, URL allowlist, restore tools); `set` changes only the
 * categories it names. */
export function applyPiiCommand(
  config: Readonly<Record<string, unknown>>,
  command: Exclude<PiiCommand, { kind: 'status' } | { kind: 'error' }>,
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

/** Policy keys whose change the category modes already show. */
const SHOWN_AS_MODES: ReadonlySet<string> = new Set([
  'categories',
  'disabledCategories',
  'restoreTools',
]);

/** What changed from `before` to `now`, for the user: category modes, the
 * tools that get real values back, and the other settings by name. Names
 * only, never values. */
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
  const keys = new Set([...Object.keys(before.config), ...Object.keys(now.config)]);
  const other = [...keys]
    .filter((k) => !SHOWN_AS_MODES.has(k))
    .filter((k) => JSON.stringify(before.config[k]) !== JSON.stringify(now.config[k]))
    .sort();
  if (other.length > 0) parts.push(`${other.join(', ')} changed`);
  return parts.length > 0 ? parts.join('; ') : 'settings changed';
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
