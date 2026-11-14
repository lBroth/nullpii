// SPDX-License-Identifier: Apache-2.0

/**
 * Words written where a credential goes but standing in for one: masks
 * (`xxx`, `****`), placeholders (`your_password`, `api_key_here`), type
 * names and keywords (`string`, `null`), and stand-in words (`password`,
 * `changeme`). One list for every recognizer that masks a credential by
 * its place rather than its shape: the password in a URL's userinfo
 * (`core:url-userinfo-password`) and the value after a credential-named
 * key (`credential-fields.ts`).
 */

/** A mask or a filler: `xxx`, `****`, `...`, `___`, `###`. */
const MASK = /^[xX*.#_-]+$/;
/** A placeholder: `your_password`, `my-token`, `the_secret`, `some_key`, `api_key_here`. */
const PLACEHOLDER = /^(?:your|my|the|some)[_-]?\w*$|_here$/i;
/** Trailing `?` or `!` of a type or a keyword (`string?`, `bool!`). */
const TYPE_SUFFIX = /[?!]+$/;
/** Type names, keywords and stand-ins written where a value goes. */
const TYPE_WORDS: ReadonlySet<string> = new Set([
  'string',
  'str',
  'bytes',
  'number',
  'int',
  'integer',
  'boolean',
  'bool',
  'none',
  'null',
  'nil',
  'true',
  'false',
  'undefined',
  'required',
  'optional',
  'any',
  'object',
  'secretstr',
  'text',
  'varchar',
  'password',
  'token',
  'secret',
  'hidden',
  'redacted',
  'masked',
  'changeme',
  'example',
  'value',
  'env',
  'type',
  'char',
  'function',
  'func',
  'lambda',
  'self',
  'this',
  'new',
  'await',
  'return',
  'get',
  'set',
  'default',
  'buffer',
  'uuid',
  'date',
  'datetime',
  'list',
  'dict',
]);

/** True when `value` is a mask, a placeholder, a type name, a keyword or
 * a stand-in word, not a credential. */
export function isStandInValue(value: string): boolean {
  if (MASK.test(value) || PLACEHOLDER.test(value)) return true;
  return TYPE_WORDS.has(value.toLowerCase().replace(TYPE_SUFFIX, ''));
}
