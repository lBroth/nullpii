// SPDX-License-Identifier: Apache-2.0

import {
  type CredentialValue,
  credentialKeySource,
  credentialKeyValue,
} from './credential-keys.js';
import { isStandInValue } from './stand-in-values.js';
import type { RecognizerSpan } from './types/index.js';

/**
 * A literal after a credential-named key (`credential-keys.ts`): the
 * password in `db_password=…`, `"passwd": "…"`, `--password …`, the
 * token in `api_key: …`, `"user_token"=>"…"`, `jwt_secret=…`. Only the
 * value is masked; the key stays readable.
 *
 * Code names credentials far more often than it holds them, so the
 * value must be a literal: never a reference (`${DB_PASSWORD}`,
 * `$PASS`, `%(password)s`, `process.env.X`, `os.environ[…]`,
 * `config.password`, `request.form[`, `DB_PASSWORD`, a variable such as
 * `hashedPassword`), a call (`getpass()`), a placeholder or a stand-in
 * (`<password>`, `⟦pw⟧`, `stand-in-values.ts`: `your_token_here`, `xxx`,
 * `****`, `string`, `null`, `changeme`), a path (`./secret.txt`,
 * `/run/secrets/db_password`), a URL, or a UUID (an id: `uuid-filter.ts`
 * keeps one after a credential key masked when the model flags it). A
 * password is at least {@link MIN_PASSWORD_CHARS} characters, a token at
 * least {@link MIN_TOKEN_CHARS} with a letter and a digit.
 */

/** Shortest literal taken for a password. */
const MIN_PASSWORD_CHARS = 6;
/** Shortest literal taken for a token, which also needs a letter and a digit. */
const MIN_TOKEN_CHARS = 16;
/** Longest key looked back for from its last word. */
const MAX_KEY_CHARS = 64;
/** A command-line flag's dashes. */
const FLAG_PREFIX = /^-{1,2}/;
const LONG_FLAG = '--';

/**
 * The key's last words, an optional closing quote or bracket, the
 * separator (`=`, `:`, `:=`, `=>`, or blanks after a `--flag`) on the
 * same line, an optional opening quote, and the value: up to a blank,
 * quote, or the punctuation that ends a value in code and URLs.
 */
function fieldPattern(value: CredentialValue): RegExp {
  return new RegExp(
    `(?<key>${credentialKeySource(value)})["'\`]?\\]?(?<sep>[ \\t]{0,16}(?::=|=>|=|:)[ \\t]{0,16}|[ \\t]{1,16})["'\`]?(?<value>[^\\s"'\`,;&#)}\\]<>]{1,256})`,
    'gi',
  );
}

/** Pattern of `core:password-field`: a value after a password-named key. */
export const PASSWORD_FIELD_PATTERN = fieldPattern('password');
/** Pattern of `core:token-field`: a value after a token-named key. */
export const TOKEN_FIELD_PATTERN = fieldPattern('token');

/** Starts of a value that is not a literal: references and templates
 * (`$`, `%`, `{`, the `⟦` of a template slot), calls and groupings, tags
 * and placeholders (`<`, `[`, `!` of a YAML tag), masks (`*`),
 * decorators and handles (`@`). */
const NOT_LITERAL_START = /^[$%{(<[*@!⟦]/;
/** A dotted reference: `config.password`, `settings.DB_PASS`, `process.env.TOKEN`. */
const DOTTED_REFERENCE = /^[A-Za-z_][\w$]*(?:\.[A-Za-z_$][\w$]*)+$/;
/** A subscript: `request.form[`, `params[`, `data["`. */
const SUBSCRIPT = /^[A-Za-z_$][\w$.]*\[/;
/** A URL: the value is where a credential lives, not the credential
 * (one in the URL's userinfo is `core:url-userinfo-password`'s). */
const URL_SCHEME = /^[A-Za-z][A-Za-z0-9+.-]*:\/\//;
/** An identifier of words, as a variable is named: letters only, with
 * `_` between words or camelCase humps (a password mixes in digits). */
const WORD_IDENTIFIER = /^[A-Za-z]+(?:_[A-Za-z]+)*$/;
/** An environment lookup written without a call (`os.environ[`). */
const ENV_LOOKUP = /^(?:os\.environ|process\.env|ENV)\b/;
/** An environment variable's name: `DB_PASSWORD`, `API_TOKEN`. */
const ENV_NAME = /^[A-Z][A-Z0-9]*_[A-Z0-9_]*$/;
/** A path: relative (`./`, `../`), home (`~/`) or a drive (`C:\`). */
const RELATIVE_PATH = /^(?:\.{1,2}|~)[/\\]|^[A-Za-z]:[/\\]/;
/** An absolute path of at least two segments. A leading `/` alone is
 * not a path: base64 can start with one. */
const ABSOLUTE_PATH = /^(?:\/[\w.-]+){2,}\/?$/;
/** A path segment as people name them: lowercase, Capitalised or
 * UPPERCASE words, digits, `.`, `_`, `-`; not random base64. */
const PATH_SEGMENT = /^(?:[a-z0-9_.-]+|[A-Z][a-z0-9_.-]*|[A-Z0-9_.-]+)$/;
/** A UUID, any version. */
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const LETTER = /[A-Za-z]/;
const DIGIT = /\d/;
/** Characters a key is written with. */
const KEY_CHAR = /[A-Za-z0-9_.-]/;

/** True when `value` is a literal, not a reference, call, placeholder, type, path, URL or UUID. */
export function isCredentialLiteral(value: string): boolean {
  if (NOT_LITERAL_START.test(value) || value.includes('(')) return false;
  if (DOTTED_REFERENCE.test(value) || SUBSCRIPT.test(value) || URL_SCHEME.test(value)) return false;
  if (ENV_LOOKUP.test(value) || ENV_NAME.test(value) || isCredentialVariable(value)) return false;
  if (isStandInValue(value) || UUID.test(value)) return false;
  return !isPathShaped(value);
}

/** True when `value` is a variable named for a credential (`hashedPassword`,
 * `new_password`, `accessToken`): code passing one on, not its value. */
function isCredentialVariable(value: string): boolean {
  return WORD_IDENTIFIER.test(value) && credentialKeyValue(value) !== null;
}

/** True when `value` reads as a file path. */
function isPathShaped(value: string): boolean {
  if (RELATIVE_PATH.test(value)) return true;
  if (!ABSOLUTE_PATH.test(value)) return false;
  return value
    .split('/')
    .filter((s) => s.length > 0)
    .every((s) => PATH_SEGMENT.test(s));
}

/** True when `value` is long enough, and varied enough, for a `kind` value. */
function fitsValue(kind: CredentialValue, value: string): boolean {
  if (kind === 'password') return value.length >= MIN_PASSWORD_CHARS;
  return value.length >= MIN_TOKEN_CHARS && LETTER.test(value) && DIGIT.test(value);
}

/** The whole key that ends with the words the pattern matched at `start`. */
function keyBefore(text: string, start: number, end: number): string {
  let i = start;
  while (i > 0 && end - i < MAX_KEY_CHARS && KEY_CHAR.test(text.charAt(i - 1))) i--;
  return text.slice(i, end);
}

/**
 * `Recognizer.span` hook of the field recognizers: the value of a match
 * of {@link fieldPattern}, or `null` when its key does not name a `kind`
 * credential, a blank separator follows anything but a `--flag`, or the
 * value is not a literal of that kind.
 */
function fieldSpan(kind: CredentialValue, m: RegExpExecArray, text: string): RecognizerSpan | null {
  const words = m.groups?.key;
  const sep = m.groups?.sep;
  const value = m.groups?.value;
  if (words === undefined || sep === undefined || value === undefined) return null;
  const rawKey = keyBefore(text, m.index, m.index + words.length);
  const key = rawKey.replace(FLAG_PREFIX, '');
  if (sep.trim() === '' && !rawKey.startsWith(LONG_FLAG)) return null;
  if (credentialKeyValue(key) !== kind) return null;
  if (!fitsValue(kind, value) || !isCredentialLiteral(value)) return null;
  const end = m.index + m[0].length;
  return { start: end - value.length, end };
}

/** `Recognizer.span` hook of `core:password-field`. */
export function passwordFieldSpan(m: RegExpExecArray, text: string): RecognizerSpan | null {
  return fieldSpan('password', m, text);
}

/** `Recognizer.span` hook of `core:token-field`. */
export function tokenFieldSpan(m: RegExpExecArray, text: string): RecognizerSpan | null {
  return fieldSpan('token', m, text);
}
