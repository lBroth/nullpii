// SPDX-License-Identifier: Apache-2.0

/**
 * UUIDs the model labels `account_number`.
 *
 * Software mints UUIDs for requests, sessions, resources and temporary
 * directories (`/tmp/42721e36-…/out.log`). They are not account numbers,
 * which this schema keeps for bank, card and customer accounts, and the
 * AB-1 annotation spec lists them as text to keep. The model labels them
 * `account_number` anyway. Masked, they break an agent's work: a path or
 * a command argument that holds one reaches the model as a placeholder,
 * and the Claude Code mod refuses a shell command that holds a
 * placeholder.
 *
 * A UUID can be a credential, though: a Heroku API key, a client secret,
 * a bearer token. So a model span labelled `account_number` whose text is
 * a UUID is:
 * - relabelled `secret` right after a credential-named key on its line
 *   (`api_key=`, `"token": "`, `Authorization: Bearer `);
 * - dropped anywhere else, so the UUID stays readable.
 * A UUID with any other label is left as it is.
 *
 * Call this on raw decoder output, before any dedupe and before the
 * recognizers see the model's spans: a recognizer defers to a model span
 * it overlaps, so a span dropped later could leave a secret in the clear.
 */

/** A UUID (any version), with the stray punctuation span boundaries carry. */
const UUID_SHAPE = /^\W*[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\W*$/i;

/** A credential-named key, with its quote and separator, right before a
 * value: `api_key=`, `"client_secret": "`, `X-Auth-Token: `, `Bearer `. */
const CREDENTIAL_KEY_BEFORE =
  /(?:key|token|secret|pass(?:w(?:or)?d)?|pwd|credentials?|auth\w*|bearer)["']?\s*(?::|=>?)?\s*["']?$/i;

/** How far back on its line a span's credential key is looked for. */
const KEY_WINDOW_CHARS = 48;

const ACCOUNT_LABEL = 'account_number';
const SECRET_LABEL = 'secret';

/**
 * Resolve model-emitted `account_number` spans whose text is a UUID:
 * `secret` after a credential-named key, else dropped. Spans of every
 * other label pass through untouched.
 *
 * @param spans - decoded model spans
 * @param text - the text the span offsets index into
 */
export function resolveUuidAccountNumbers<T extends { label: string; start: number; end: number }>(
  spans: T[],
  text: string,
): T[] {
  const out: T[] = [];
  for (const s of spans) {
    if (s.label !== ACCOUNT_LABEL || !UUID_SHAPE.test(text.slice(s.start, s.end))) {
      out.push(s);
    } else if (followsCredentialKey(text, s.start)) {
      out.push({ ...s, label: SECRET_LABEL });
    }
  }
  return out;
}

/** True when the text before `start`, on its line, ends in a credential-named key. */
function followsCredentialKey(text: string, start: number): boolean {
  const lineStart = text.lastIndexOf('\n', start - 1) + 1;
  const before = text.slice(Math.max(lineStart, start - KEY_WINDOW_CHARS), start);
  return CREDENTIAL_KEY_BEFORE.test(before);
}
