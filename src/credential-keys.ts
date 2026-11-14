// SPDX-License-Identifier: Apache-2.0

/**
 * The closed list of words that make a key name a credential's: the one
 * vocabulary of the UUID filter (`uuid-filter.ts`, which keeps a UUID
 * after such a key masked) and of the field recognizers
 * (`credential-fields.ts`, which mask the literal after one).
 *
 * A key names a credential when its last word, or its last two, are on
 * the list: `db_password`, `DB_PASSWORD`, `dbPassword` and
 * `spring.datasource.password` end in `password`; `x-api-key` and
 * `apiKey` in `api key`. A key's words are split at `_`, `-`, `.` and
 * camelCase humps.
 */

/** What the value after a credential key is, for the field recognizers. */
export type CredentialValue = 'password' | 'token';

interface CredentialKeyWord {
  /** The key's last words, lowercase. */
  readonly words: readonly string[];
  /** The value the field recognizers expect after it: a password, a
   * token, or none (the word marks a credential for the UUID filter
   * only: a bare `key` names anything in a YAML file). */
  readonly value: CredentialValue | null;
  /** A UUID after it is a credential, not an id. */
  readonly uuid: boolean;
  /** For the UUID filter, any word that starts with it counts too
   * (`authorization`, `authtoken`). */
  readonly stem?: true;
}

/** The list. `session` names a session token for the field
 * recognizers, but a UUID after it is a session id, and stays readable.
 * `sid` is not on it: Windows SIDs and Twilio SIDs are ids. */
export const CREDENTIAL_KEY_WORDS: readonly CredentialKeyWord[] = [
  { words: ['password'], value: 'password', uuid: true },
  { words: ['passwd'], value: 'password', uuid: true },
  { words: ['pass'], value: 'password', uuid: true },
  { words: ['pwd'], value: 'password', uuid: true },
  { words: ['passphrase'], value: 'password', uuid: false },
  { words: ['secret'], value: 'token', uuid: true },
  { words: ['token'], value: 'token', uuid: true },
  { words: ['credential'], value: 'token', uuid: true },
  { words: ['credentials'], value: 'token', uuid: true },
  { words: ['auth'], value: 'token', uuid: true, stem: true },
  { words: ['apikey'], value: 'token', uuid: true },
  { words: ['api', 'key'], value: 'token', uuid: true },
  { words: ['access', 'key'], value: 'token', uuid: true },
  { words: ['private', 'key'], value: 'token', uuid: true },
  { words: ['secret', 'key'], value: 'token', uuid: true },
  { words: ['session'], value: 'token', uuid: false },
  { words: ['sessionid'], value: 'token', uuid: false },
  { words: ['session', 'id'], value: 'token', uuid: false },
  { words: ['key'], value: null, uuid: true },
  { words: ['bearer'], value: null, uuid: true },
];

/** Keys that end in a password word and name something else: a bare
 * `pass` (a pass/fail flag, a Python statement), and the shell's working
 * directory. Compared as written. */
const NOT_CREDENTIAL_KEYS: ReadonlySet<string> = new Set(['pass', 'Pass', 'PASS', 'PWD', 'OLDPWD']);

/** Words that make a key name a piece of interface text about a
 * credential, not the credential: `label_new_password`,
 * `title_change_password`, `error_wrong_password`. Its value is a
 * translation or a caption (`"Passwort"`). */
const UI_TEXT_WORDS: ReadonlySet<string> = new Set([
  'label',
  'title',
  'placeholder',
  'hint',
  'prompt',
  'caption',
  'tooltip',
  'message',
  'msg',
  'text',
  'heading',
  'button',
  'error',
  'help',
  'description',
  'desc',
]);

/** Words that make a token key name a page of results, not access:
 * `next_page_token`, `pageToken`, `continuation_token`, `cursor_token`.
 * An API hands them out to fetch the next page. */
const PAGINATION_WORDS: ReadonlySet<string> = new Set(['page', 'next', 'continuation', 'cursor']);

/** Separators between a key's words, and camelCase humps. */
const KEY_WORD_BREAK = /[_.-]+|(?<=[a-z0-9])(?=[A-Z])/;

/** Regex source of a list entry's words as written in a key: joined by
 * an optional separator (`api_key`, `api-key`, `apiKey`, `apikey`). */
function wordsSource(entry: CredentialKeyWord): string {
  return entry.words.join('[_.\\-]?');
}

/**
 * Regex source of the words, any case, that end a key whose value is a
 * `value`: the alternation the field recognizers' patterns start with.
 * Longest first, so a match does not stop inside a longer word.
 */
export function credentialKeySource(value: CredentialValue): string {
  return CREDENTIAL_KEY_WORDS.filter((e) => e.value === value)
    .map(wordsSource)
    .sort((a, b) => b.length - a.length)
    .join('|');
}

/**
 * A credential-named key, with its quote and separator, right before a
 * value (`api_key=`, `"client_secret": "`, `X-Auth-Token: `, `Bearer `),
 * for the UUID filter: the text before the value ends in one of the
 * list's UUID words (or a word starting with a stem).
 */
export const CREDENTIAL_KEY_BEFORE = new RegExp(
  `(?:${CREDENTIAL_KEY_WORDS.filter((e) => e.uuid)
    .map((e) => (e.stem === true ? `${wordsSource(e)}\\w*` : wordsSource(e)))
    .join('|')})["']?\\s*(?::|=>?)?\\s*["']?$`,
  'i',
);

/**
 * What value the key `key` (as written, with any `-` or `--` of a
 * command-line flag already removed) names, by its last words: `null`
 * when it is not a credential key, names one only for the UUID filter,
 * or names interface text about one or a page of results.
 */
export function credentialKeyValue(key: string): CredentialValue | null {
  if (NOT_CREDENTIAL_KEYS.has(key)) return null;
  const words = key
    .split(KEY_WORD_BREAK)
    .filter((w) => w.length > 0)
    .map((w) => w.toLowerCase());
  if (words.some((w) => UI_TEXT_WORDS.has(w) || PAGINATION_WORDS.has(w))) return null;
  let best: CredentialKeyWord | undefined;
  for (const entry of CREDENTIAL_KEY_WORDS) {
    const tail = words.slice(-entry.words.length);
    if (tail.length !== entry.words.length || tail.some((w, i) => w !== entry.words[i])) continue;
    if (best === undefined || entry.words.length > best.words.length) best = entry;
  }
  return best?.value ?? null;
}
