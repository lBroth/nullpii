// SPDX-License-Identifier: Apache-2.0
//
// nullpii mod: every prompt and every tool result goes through the local
// nullpii sidecar (`nullpii-gateway` with NULLPII_SIDECAR_TOKEN set) before
// Claude reads it, so personal data and secrets reach the model as
// placeholders. Real values go back only into the arguments of the tools
// the sidecar's policy lists (`restoreTools` in the shared config file, by
// default the tools that run on this machine), so files and commands see
// what the user has, and nothing masked leaves through a web or MCP tool.
//
// Fail closed: when the sidecar cannot be reached, a prompt is handed back
// to the user and a tool call is refused, instead of going out unmasked.
// The vault lives in the sidecar's memory; this mod keeps counts only, and
// the session's secret, which never leaves this process's memory.

import {
  PLACEHOLDER,
  type Policy,
  addMasked,
  challengeNonce,
  emptyCounts,
  expectedProof,
  formatBand,
  formatReport,
  hasPlaceholder,
  optionString,
  restorableArgs,
  sameText,
  sidecarOrigin,
  touchesPolicyFile,
} from './policy.ts';

/** The manifest's default for `sidecar_url`, for an option saved empty. */
const DEFAULT_SIDECAR_URL = 'http://127.0.0.1:8787';
const SESSIONS_PATH = '/v1/sidecar/sessions/';
const STATUS_PATH = '/v1/sidecar/status';
const CHALLENGE_PATH = '/v1/sidecar/challenge';
const JSON_TYPE = { 'content-type': 'application/json' };
const SESSION_NOT_FOUND = 404;
const SESSION_EXISTS = 409;
/** Proves to the sidecar that this mod opened the session. */
const SESSION_SECRET_HEADER = 'x-nullpii-session-secret';
const KEY_SUFFIX_RADIX = 36;
const NO_TOKEN =
  'no sidecar token: set it with /plugin configure (sidecar_token), or NULLPII_SIDECAR_TOKEN';
const NOT_LOOPBACK =
  'sidecar_url is not a local sidecar address (http:// on 127.0.0.1 or [::1], the address the gateway listens on, with an optional port and nothing after it): fix it with /plugin configure';
const UNREACHABLE =
  'nullpii-gateway did not answer at the sidecar address: start it with NULLPII_SIDECAR_TOKEN set';
const NOT_JSON = 'the sidecar answered with something that is not JSON';
const NOT_SIDECAR =
  'the process at the sidecar address did not prove it holds the sidecar token, so nothing was sent to it: run nullpii-gateway 0.5 or later there, with the same NULLPII_SIDECAR_TOKEN';
const TIMED_OUT = 'the sidecar took too long to answer';
/** Shown in place of an error text this mod did not write (a tool's, a
 * hook's, the host's): such a text can quote a value restored into a tool
 * call, or a sidecar answer. */
const HIDDEN_REASON = 'an unexpected error, whose text is not shown as it may hold personal data';
/** The error texts this mod writes, which hold no value: the only ones shown. */
const OWN_REASONS: ReadonlySet<string> = new Set([
  NO_TOKEN,
  NOT_LOOPBACK,
  UNREACHABLE,
  NOT_JSON,
  NOT_SIDECAR,
]);
/** SidecarError's text, the one with a variable part. */
const SIDECAR_STATUS = /^nullpii sidecar answered \d{3}$/;
const TIMEOUT_KIND = 'timeout';
/** The refusal for a shell call that holds placeholders: no shell command
 * gets a real value (SECURITY.md). Names the placeholders, never values. */
function shellDenied(kept: readonly string[]): string {
  return `nullpii puts no real value into a shell command (${kept.join(', ')}): the value came from data you could not read, so a command could run it. Work with that data through Grep, Read, Edit or Write, which get real values back, or ask the user to run the command themselves.`;
}
const THROW_KIND = 'throw';
// What Claude reads when the mod refuses a call: fixed text, never the
// failure's own, which can quote real values. The reason is the user's.
const CALL_NOT_RUN =
  'nullpii could not prepare this tool call through its sidecar, so it was not run. The user sees why above the prompt and in /pii.';
const RESULT_WITHHELD =
  "nullpii could not mask this tool's result, so it was withheld. The user sees why above the prompt and in /pii.";
const CONTEXT_WITHHELD =
  "nullpii withheld this tool's result: a hook attached text for Claude that holds personal data, and that text cannot be masked.";
const POLICY_DENIED =
  'nullpii refused this call: with the real values put back it would change the nullpii masking policy file, which the user was not asked about. Ask the user to make that change themselves.';
const POLICY_ASK =
  'This call may change the nullpii masking policy (what gets masked, and which tools get real values back). Allow it only if you asked for that change.';

interface Sanitized {
  value: unknown;
  captured: number;
  capturedByLabel: Record<string, number>;
}

interface Restored {
  value: Record<string, unknown>;
  replacements: number;
  /** For a shell tool: placeholders the sidecar left masked in `command`,
   * because restoring them could change what the shell runs. */
  shellKeptMasked?: string[];
  /** For a tool outside the policy's `restoreTools`: the placeholders kept. */
  heldForTool?: number;
}

/** Why a hook failed: what a `.catch` handler reads as `next.error`. */
interface Failure {
  readonly kind: string;
  readonly message?: string;
}
// Module scope is how a mod's hooks share data: the mods API passes no
// context object between them. `$.state` would survive a reload of the
// module, but nothing here needs to (a reloaded mod opens a new sidecar
// session), and the session secret must stay in this process's memory.

// Display-only restores, keyed by the masked text. In memory only, bounded,
// and cleared when the session ends.
const SHOWN_MAX = 256;
const shown = new Map<string, string>();

const counts = emptyCounts();
// The sidecar's origin; undefined when `sidecar_url` is not a loopback
// address, and then nothing is sent anywhere.
let sidecarUrl: string | undefined;
let token: string | undefined;
// The Claude Code session id, and the sidecar key in use: the id, or the
// id with a suffix once the mod has had to start a new sidecar session.
let sessionBase = '';
let sessionKey = '';
// The secret the sidecar handed out for `sessionKey`: without it the
// bearer token alone (which commands may inherit) reads nothing.
let sessionSecret: string | undefined;
// The policy the sidecar runs with, read when the session opens.
let policy: Policy | undefined;
// Why the mod is blocking, shown above the prompt; undefined while healthy.
let problem: string | undefined = NO_TOKEN;
// The session (re)opening in flight, which every hook that needs one awaits.
let opening: Promise<void> | undefined;

class SidecarError extends Error {
  constructor(readonly status: number) {
    super(`nullpii sidecar answered ${status}`);
  }
}

/** Send one request to the sidecar's route `path`, with the session
 * secret when one is given. Nothing is sent, the token included, unless
 * the sidecar's address is a loopback one and the process there has just
 * proved it holds the token: another process could have taken the port
 * since the last request (the gateway stopped, or restarted). */
async function request(
  $,
  method: string,
  path: string,
  body?: unknown,
  secret?: string,
): Promise<unknown> {
  if (sidecarUrl === undefined) throw new Error(NOT_LOOPBACK);
  if (token === undefined) throw new Error(NO_TOKEN);
  await checkSidecar($, sidecarUrl, token);
  // A JSON content type with no body is a 400, so PUT and DELETE send neither.
  const json = body === undefined ? {} : JSON_TYPE;
  const owner = secret === undefined ? {} : { [SESSION_SECRET_HEADER]: secret };
  const res = await fetchSidecar($, sidecarUrl + path, {
    method,
    headers: { authorization: `Bearer ${token}`, ...json, ...owner },
    ...(body !== undefined && { body: JSON.stringify(body) }),
  });
  if (!res.ok) throw new SidecarError(res.status);
  return parseAnswer(res.text);
}

/** Ask the process at `origin` to sign a fresh nonce with the token,
 * which is not sent: only the sidecar holding the same token answers the
 * expected proof. */
async function checkSidecar($, origin: string, secretToken: string): Promise<void> {
  const nonce = challengeNonce();
  const res = await fetchSidecar($, origin + CHALLENGE_PATH, {
    method: 'POST',
    headers: JSON_TYPE,
    body: JSON.stringify({ nonce }),
  });
  const answer = res.ok ? (parseAnswer(res.text) as { proof?: unknown }) : {};
  const proof = typeof answer.proof === 'string' ? answer.proof : '';
  if (!sameText(proof, await expectedProof(secretToken, nonce))) throw new Error(NOT_SIDECAR);
}

/** `$.http.fetch`, failing with the mod's own text: the host's can carry
 * what another hook on the request answered. Its kind goes to the debug log. */
async function fetchSidecar(
  $,
  url: string,
  init: Record<string, unknown>,
): Promise<{ ok: boolean; status: number; text: string }> {
  try {
    return await $.http.fetch(url, init);
  } catch (err) {
    $.ui.log(`nullpii: sidecar request failed (${errorName(err)})`, { to: 'debug' });
    throw new Error(UNREACHABLE);
  }
}

/** A sidecar answer as JSON. A parse error quotes the text it read, which
 * can hold real values, so it is replaced by the mod's own. */
function parseAnswer(text: string): unknown {
  if (text === '') return {};
  try {
    return JSON.parse(text);
  } catch {
    throw new Error(NOT_JSON);
  }
}

function errorName(err: unknown): string {
  return err instanceof Error ? err.name : typeof err;
}

/** Call this session's sidecar route `path` (`/sanitize`, `/restore`). */
async function sidecar($, method: string, path: string, body?: unknown): Promise<unknown> {
  return request(
    $,
    method,
    SESSIONS_PATH + encodeURIComponent(sessionKey) + path,
    body,
    sessionSecret,
  );
}

/** PUT the session `key`, presenting `secret` when there is one; resolves
 * with the secret that now holds it: a new one when the sidecar created
 * the session, else the one presented. */
async function putSession($, key: string, secret: string | undefined): Promise<string | undefined> {
  const path = SESSIONS_PATH + encodeURIComponent(key);
  const opened = (await request($, 'PUT', path, undefined, secret)) as { secret?: string };
  return opened.secret ?? secret;
}

/** Open this mod's sidecar session, or keep it alive, once for every hook
 * that asks while it runs: hooks that each found the session gone (a
 * sidecar restart, its idle TTL) would otherwise each open it, and one
 * would move to a new key while the others still used the old one. */
function openSession($): Promise<void> {
  opening ??= openSessionOnce($).finally(() => {
    opening = undefined;
  });
  return opening;
}

/** A live session under the key whose secret this module no longer has
 * (it was reloaded) cannot be taken over, so a new one opens under a new
 * key: placeholders from before stay masked, as after a sidecar restart.
 * The key and its secret change together, once the sidecar holds both. */
async function openSessionOnce($): Promise<void> {
  let key = sessionKey;
  let secret: string | undefined;
  try {
    secret = await putSession($, key, sessionSecret);
  } catch (err) {
    if (!(err instanceof SidecarError) || err.status !== SESSION_EXISTS) throw err;
    const now = await $.clock.now();
    key = `${sessionBase}.${Math.floor(now).toString(KEY_SUFFIX_RADIX)}`;
    secret = await putSession($, key, undefined);
  }
  sessionKey = key;
  sessionSecret = secret;
  problem = undefined;
  const status = (await request($, 'GET', STATUS_PATH)) as { policy?: Policy };
  policy = status.policy;
}

/** Mask every string in `value`. A session the sidecar dropped (restart or
 * idle TTL) is opened again: nothing restores into it, but masking works. */
async function sanitize($, value: unknown): Promise<Sanitized> {
  try {
    return (await sidecar($, 'POST', '/sanitize', { value })) as Sanitized;
  } catch (err) {
    if (!(err instanceof SidecarError) || err.status !== SESSION_NOT_FOUND) throw err;
    await openSession($);
    return (await sidecar($, 'POST', '/sanitize', { value })) as Sanitized;
  }
}

async function masked($, value: unknown): Promise<unknown> {
  const r = await sanitize($, value);
  addMasked(counts, r.captured, r.capturedByLabel);
  $.ui.invalidate('ui.render');
  return r.value;
}

/** A caught error as a Failure, as a `.catch` handler would read it. */
function failureOf(err: unknown): Failure {
  return { kind: THROW_KIND, message: err instanceof Error ? err.message : undefined };
}

/** The text shown for a failure: the mod's own error texts as written, any
 * other replaced, since it can quote personal data. */
function shownReason(failure: Failure): string {
  const { message } = failure;
  if (message === undefined) return failure.kind === TIMEOUT_KIND ? TIMED_OUT : HIDDEN_REASON;
  return OWN_REASONS.has(message) || SIDECAR_STATUS.test(message) ? message : HIDDEN_REASON;
}

/** Turn the band red with why `event` failed, and log the same to the
 * debug log, with only the length of a text that is not shown. */
function blocked($, event: string, failure: Failure): string {
  const reason = shownReason(failure);
  problem = reason;
  const withheld =
    reason === HIDDEN_REASON && failure.message !== undefined
      ? ` (${failure.message.length} characters withheld)`
      : '';
  $.ui.log(`nullpii: ${event} failed (${failure.kind}): ${reason}${withheld}`, { to: 'debug' });
  $.ui.invalidate('ui.render');
  return reason;
}

/** The text with real values, for the screen only. */
async function restoredForDisplay($, text: string): Promise<string> {
  const cached = shown.get(text);
  if (cached !== undefined) return cached;
  const r = (await sidecar($, 'POST', '/restore', { value: text })) as { value: string };
  if (shown.size >= SHOWN_MAX) shown.delete(shown.keys().next().value as string);
  shown.set(text, r.value);
  return r.value;
}

export function register(on, options) {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'pii',
      description: 'Show what nullpii masked in this session',
    });
    // The address comes from the plugin option alone: options are read from
    // user and managed settings only, while a project's settings can set
    // environment variables, so an address taken from the environment could
    // send the token and every unmasked prompt where a repository says.
    sidecarUrl = sidecarOrigin(optionString(options, 'sidecar_url') ?? DEFAULT_SIDECAR_URL);
    // The token comes from the plugin's sensitive option (secure storage,
    // not exported to commands), else from the environment. It only ever
    // goes to the loopback address above.
    token = optionString(options, 'sidecar_token') ?? (await $.env.get('NULLPII_SIDECAR_TOKEN'));
    sessionBase = await $.session.id();
    sessionKey = sessionBase;
    sessionSecret = undefined;
    try {
      await openSession($);
    } catch (err) {
      const reason = blocked($, 'session.start', failureOf(err));
      $.ui.toast(`nullpii is blocking prompts and tool results: ${reason}`);
    }
    return next(e);
  });

  on('session.end', async ($, e, next) => {
    shown.clear();
    try {
      await sidecar($, 'DELETE', '');
      sessionSecret = undefined;
    } catch (err) {
      // The sidecar's idle TTL drops the session anyway.
      $.ui.log(`nullpii: session not closed: ${shownReason(failureOf(err))}`, { to: 'debug' });
    }
    return next(e);
  });

  on('prompt.submit', async ($, e, next) => {
    const out = (await masked($, { text: e.text, context: e.context ?? [] })) as {
      text: string;
      context: string[];
    };
    return next({ ...e, text: out.text, ...(e.context !== undefined && { context: out.context }) });
  }).catch(async ($, e, next) => {
    if (next.called) return next(e);
    return {
      drop: `nullpii could not mask this prompt, so it was not sent (${blocked($, 'prompt.submit', next.error)}). Start nullpii-gateway with its sidecar token set, or disable the nullpii mod.`,
    };
  });

  // Text Claude Code adds for Claude on its own: @-mentioned files, edited
  // files, memory and other reminders. Unmaskable means not sent.
  on('prompt.attachment', async ($, e, next) => {
    return next({ ...e, text: String(await masked($, e.text)) });
  }).catch(async ($, e, next) => {
    blocked($, 'prompt.attachment', next.error);
    return next.called ? next(e) : { text: null };
  });

  // The first message's context: CLAUDE.md files and the user's email. A
  // rewritten CLAUDE.md block no longer matches its instruction files, so
  // that list is left out, as the event requires.
  on('prompt.context', async ($, e, next) => {
    const texts = (await masked(
      $,
      e.blocks.map((b) => b.text),
    )) as string[];
    return next({ blocks: e.blocks.map((b, i) => ({ ...b, text: texts[i] })) });
  }).catch(async ($, e, next) => {
    blocked($, 'prompt.context', next.error);
    return next.called ? next(e) : { blocks: [] };
  });

  on('tool.call', async ($, e, next) => {
    // Known to be blocking: reach the sidecar again before the tool runs,
    // so the call is refused up front instead of run with its result
    // withheld, and a sidecar that is back clears the block.
    if (problem !== undefined) await openSession($);
    const args = restorableArgs(e);
    let call = e;
    if (hasPlaceholder(args)) {
      // The sidecar decides by the tool's name: nothing for a tool outside
      // the policy's `restoreTools`, and nothing for a shell tool, whose
      // placeholders it lists so the call is refused (SECURITY.md).
      const r = (await sidecar($, 'POST', '/restore', { value: args, tool: e.tool })) as Restored;
      counts.held += r.heldForTool ?? 0;
      const kept = r.shellKeptMasked ?? [];
      if (kept.length > 0) return { deny: shellDenied(kept) };
      // Rewrite the call only when a placeholder was replaced: a rewritten
      // call is denied in auto mode, so untouched calls must stay as written.
      if (r.replacements > 0) {
        const restored = { ...e, ...r.value };
        // `tool.check` judged the masked call: a policy path with a masked
        // segment (`NULLPII_CONFIG=/Users/<name>/…`) shows only now.
        const cwd = await $.session.cwd();
        const file = policy?.file;
        if (
          touchesPolicyFile(e.tool, restored, file, cwd) &&
          !touchesPolicyFile(e.tool, e, file, cwd)
        ) {
          return { deny: POLICY_DENIED };
        }
        counts.restored += r.replacements;
        call = restored;
      }
    }
    const out = await next(call);
    // A refusal can quote the arguments, which may now hold real values.
    if (out.deny !== undefined) return { deny: String(await masked($, out.deny)) };
    if (out.isError === true) return { deny: String(await masked($, out.text ?? '')) };
    // `context` is text a hook below attached for the model to read after
    // the result. The mods API keeps those entries whole, so they cannot
    // be masked: when one holds personal data, the result is withheld.
    if (out.context !== undefined && (await sanitize($, out.context)).captured > 0) {
      return { deny: CONTEXT_WITHHELD };
    }
    // A new `{ result }` without `ref`: returning core's object would make
    // core send its own, unmasked messages to the model.
    return {
      result: await masked($, out.result),
      ...(out.context !== undefined && { context: out.context }),
    };
  }).catch(async ($, e, next) => {
    // Claude reads fixed text: a failure after the restore can come from
    // the tool or a hook beneath, and its text can quote the real values.
    blocked($, 'tool.call', next.error);
    return { deny: next.called ? RESULT_WITHHELD : CALL_NOT_RUN };
  });

  // A call that may change the masking policy is put to the user (or, in
  // auto mode, to its classifier), whatever the rules would have decided.
  on('tool.check', async ($, e, next) => {
    const decided = await next(e);
    if (decided.decision === 'deny') return decided;
    const cwd = await $.session.cwd();
    if (!touchesPolicyFile(e.tool, e.input, policy?.file, cwd)) return decided;
    return { decision: 'ask', reason: POLICY_ASK };
  }).catch(async ($, e, next) => (next.called ? { decision: 'ask', reason: POLICY_ASK } : next(e)));

  on('command.run', { command: 'pii' }, async () => ({
    text: formatReport(counts, problem, policy),
  }));

  // The transcript shows real values; what Claude reads keeps the
  // placeholders. If the sidecar fails, the hook is skipped and the row is
  // drawn as stored, with placeholders: nothing leaks either way.
  on('ui.render', { component: ['AssistantMessage', 'UserMessage'] }, async ($, e, next) => {
    if (!PLACEHOLDER.test(e.props.text)) return next(e);
    const text = await restoredForDisplay($, e.props.text);
    return next({ ...e, props: { ...e.props, text } });
  });

  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const { Box, Text } = $.ui.resolve(e);
    const theirs = await next(e);
    const line = Text({
      color: problem === undefined ? 'green' : 'red',
      children: [formatBand(counts, problem)],
    });
    return Box({ flexDirection: 'column', children: theirs ? [theirs, line] : [line] });
  });
}
