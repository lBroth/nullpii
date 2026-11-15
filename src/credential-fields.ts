// SPDX-License-Identifier: Apache-2.0

import {
  type CredentialValue,
  credentialKeySource,
  credentialKeyValue,
  namesInterfaceTextOrPage,
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

/**
 * Pattern of `core:symmetric-key-field`: base64 after a key whose last
 * word is `key` (`--key=`, `encryption_key: `, `APP_KEY=base64:`,
 * `cipherKey = "`, `fernet_key=`). The key and the size are checked by
 * {@link symmetricKeyFieldSpan}. A value followed by `.` is a file name
 * (`client.key`), not a key.
 */
export const SYMMETRIC_KEY_FIELD_PATTERN =
  /(?<key>key|KEY|Key)["'`]?\]?(?<sep>[ \t]{0,16}(?::=|=>|=|:)[ \t]{0,16}|[ \t]{1,16})["'`]?(?<value>(?:base64:)?[A-Za-z0-9+/_-]{16,90}={0,2})(?![A-Za-z0-9+/=_.-])/g;

/** Byte lengths of a symmetric key: AES-128, -192 and -256, and a 512-bit HMAC key. */
const SYMMETRIC_KEY_BYTES = new Set([16, 24, 32, 64]);
/** The prefix Laravel writes before its base64 `APP_KEY`. */
const BASE64_PREFIX = 'base64:';
/** Base64 bits per character, bits per byte, and characters per padded quantum. */
const BASE64_CHAR_BITS = 6;
const BYTE_BITS = 8;
const BASE64_QUANTUM = 4;
const BASE64_PADDING = /=+$/;
/** The two alphabets: standard (`+`, `/`) and URL-safe (`-`, `_`). */
const BASE64_STANDARD_ONLY = /[+/]/;
const BASE64_URL_ONLY = /[-_]/;
/** `key` as the key's own last word: alone, after `_`, `.` or `-`, a
 * camelCase `Key` hump (`cipherKey`), or after an acronym (`AESKey`);
 * not the end of `monkey` or `turkey`. */
const KEY_LAST_WORD = /(?:^|[_.-])(?:key|KEY|Key)$|[a-z0-9]Key$|[A-Z]{2}Key$/;
/** Keys that name something other than a secret key: public halves,
 * database and cache keys, host, SSH and PGP keys (public, or a file's
 * name), and the WebSocket handshake's nonce (`Sec-WebSocket-Key`). */
const NOT_SECRET_KEY =
  /(?:public|pub|foreign|sort|partition|cache|idempotency|host|ssh|gpg|pgp|websocket)[ _.-]?key$/i;
/** The word before a key written with a blank (`public key:` of `wg show`). */
const WORD_BEFORE_BLANK = /([A-Za-z]{1,32}) $/;
/** Longest stretch looked back at for that word. */
const MAX_WORD_BEFORE_CHARS = 33;
/** Fewest `/`-separated parts of a value read as a path (`a/b/c`). */
const MIN_PATH_PARTS = 3;
const UPPER = /[A-Z]/;
const LOWER = /[a-z]/;

/** The number of bytes `value` decodes to, or `null` when it is not well-formed base64. */
function base64Bytes(value: string): number | null {
  const body = value.replace(BASE64_PADDING, '');
  if (body.length < value.length && value.length % BASE64_QUANTUM !== 0) return null;
  if (body.length % BASE64_QUANTUM === 1) return null;
  return Math.floor((body.length * BASE64_CHAR_BITS) / BYTE_BITS);
}

/** True when `value` reads as a random symmetric key: base64 of a key's
 * size in one alphabet, mixing upper case, lower case and digits (hex and
 * words do not). URL-safe base64 counts only padded (a Fernet key), since
 * names joined by `-` and `_` can have a key's length too. */
function isSymmetricKey(value: string): boolean {
  const body = value.startsWith(BASE64_PREFIX) ? value.slice(BASE64_PREFIX.length) : value;
  if (!UPPER.test(body) || !LOWER.test(body) || !DIGIT.test(body)) return false;
  if (BASE64_URL_ONLY.test(body) && (BASE64_STANDARD_ONLY.test(body) || !body.endsWith('='))) {
    return false;
  }
  const bytes = base64Bytes(body);
  return bytes !== null && SYMMETRIC_KEY_BYTES.has(bytes);
}

/** True when `value` reads as a path of named parts (`uploads/2024/Q3/Report1`). */
function isNamedPath(value: string): boolean {
  const parts = value.split('/');
  return parts.length >= MIN_PATH_PARTS && parts.every((p) => p === '' || PATH_SEGMENT.test(p));
}

/** The key as read with the one word before it when they are written
 * apart (`public key` → `public_key`), else the key itself. */
function keyWithWordBefore(text: string, keyStart: number, key: string): string {
  const before = text.slice(Math.max(0, keyStart - MAX_WORD_BEFORE_CHARS), keyStart);
  const word = WORD_BEFORE_BLANK.exec(before)?.[1];
  return word === undefined ? key : `${word}_${key}`;
}

/**
 * `Recognizer.span` hook of `core:symmetric-key-field`: the value of a
 * match of {@link SYMMETRIC_KEY_FIELD_PATTERN}, or `null` when `key` is
 * not the key's own last word; the key, with the word before it when
 * written apart, names a public, database, cache, host, SSH, PGP or
 * WebSocket key, interface text or a page of results, or a credential
 * `core:token-field` takes (`api_key`, `secret_key`); a blank separator
 * follows anything but a `--flag`; or the value is a path, or not base64
 * of 16, 24, 32 or 64 bytes. Laravel's `base64:` prefix stays readable.
 */
export function symmetricKeyFieldSpan(m: RegExpExecArray, text: string): RecognizerSpan | null {
  const word = m.groups?.key;
  const sep = m.groups?.sep;
  const value = m.groups?.value;
  if (word === undefined || sep === undefined || value === undefined) return null;
  const keyEnd = m.index + word.length;
  const rawKey = keyBefore(text, m.index, keyEnd);
  const key = rawKey.replace(FLAG_PREFIX, '');
  if (!KEY_LAST_WORD.test(key)) return null;
  const named = keyWithWordBefore(text, keyEnd - rawKey.length, key);
  if (NOT_SECRET_KEY.test(named) || namesInterfaceTextOrPage(named)) return null;
  if (credentialKeyValue(key) !== null) return null;
  if (sep.trim() === '' && !rawKey.startsWith(LONG_FLAG)) return null;
  if (isNamedPath(value) || !isSymmetricKey(value)) return null;
  const end = m.index + m[0].length;
  const prefix = value.startsWith(BASE64_PREFIX) ? BASE64_PREFIX.length : 0;
  return { start: end - value.length + prefix, end };
}
