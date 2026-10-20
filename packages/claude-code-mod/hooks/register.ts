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
  emptyCounts,
  formatBand,
  formatReport,
  hasPlaceholder,
  optionString,
  restorableArgs,
  touchesPolicyFile,
} from './policy.ts';

const DEFAULT_SIDECAR_URL = 'http://127.0.0.1:8787';
const SESSIONS_PATH = '/v1/sidecar/sessions/';
const STATUS_PATH = '/v1/sidecar/status';
const SESSION_NOT_FOUND = 404;
const SESSION_EXISTS = 409;
/** Proves to the sidecar that this mod opened the session. */
const SESSION_SECRET_HEADER = 'x-nullpii-session-secret';
const KEY_SUFFIX_RADIX = 36;
const NO_TOKEN =
  'no sidecar token: set it with /plugin configure (sidecar_token), or NULLPII_SIDECAR_TOKEN';
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
// Display-only restores, keyed by the masked text. In memory only, bounded,
// and cleared when the session ends.
const SHOWN_MAX = 256;
const shown = new Map<string, string>();

const counts = emptyCounts();
let sidecarUrl = DEFAULT_SIDECAR_URL;
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

class SidecarError extends Error {
  constructor(readonly status: number) {
    super(`nullpii sidecar answered ${status}`);
  }
}

/** Send one request to the sidecar at `url` (a full URL), with the
 * session secret when one is given. */
async function request(
  $,
  method: string,
  url: string,
  body?: unknown,
  secret?: string,
): Promise<unknown> {
  if (token === undefined) throw new Error(NO_TOKEN);
  // A JSON content type with no body is a 400, so PUT and DELETE send neither.
  const json = body === undefined ? {} : { 'content-type': 'application/json' };
  const owner = secret === undefined ? {} : { [SESSION_SECRET_HEADER]: secret };
  const res = await $.http.fetch(url, {
    method,
    headers: { authorization: `Bearer ${token}`, ...json, ...owner },
    ...(body !== undefined && { body: JSON.stringify(body) }),
  });
  if (!res.ok) throw new SidecarError(res.status);
  return res.text === '' ? {} : JSON.parse(res.text);
}

/** Call this session's sidecar route `path` (`/sanitize`, `/restore`). */
async function sidecar($, method: string, path: string, body?: unknown): Promise<unknown> {
  return request(
    $,
    method,
    sidecarUrl + SESSIONS_PATH + encodeURIComponent(sessionKey) + path,
    body,
    sessionSecret,
  );
}

/** Open this mod's sidecar session, or keep it alive. A live session under
 * the key whose secret this module no longer has (it was reloaded) cannot
 * be taken over, so a new one opens under a new key: placeholders from
 * before stay masked, as after a sidecar restart. */
async function putSession($): Promise<void> {
  const opened = (await sidecar($, 'PUT', '')) as { secret?: string };
  if (opened.secret !== undefined) sessionSecret = opened.secret;
}

async function openSession($): Promise<void> {
  try {
    await putSession($);
  } catch (err) {
    if (!(err instanceof SidecarError) || err.status !== SESSION_EXISTS) throw err;
    const now = await $.clock.now();
    sessionKey = `${sessionBase}.${Math.floor(now).toString(KEY_SUFFIX_RADIX)}`;
    sessionSecret = undefined;
    await putSession($);
  }
  problem = undefined;
  const status = (await request($, 'GET', sidecarUrl + STATUS_PATH)) as { policy?: Policy };
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

function blocked($, err: unknown): string {
  problem = err instanceof Error ? err.message : String(err);
  $.ui.invalidate('ui.render');
  return problem;
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
    // The token comes from the plugin's sensitive option (secure storage,
    // not exported to commands), else from the environment.
    sidecarUrl =
      (await $.env.get('NULLPII_SIDECAR_URL')) ??
      optionString(options, 'sidecar_url') ??
      DEFAULT_SIDECAR_URL;
    token = optionString(options, 'sidecar_token') ?? (await $.env.get('NULLPII_SIDECAR_TOKEN'));
    sessionBase = await $.session.id();
    sessionKey = sessionBase;
    sessionSecret = undefined;
    try {
      await openSession($);
    } catch (err) {
      $.ui.toast(`nullpii is blocking prompts and tool results: ${blocked($, err)}`);
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
      $.ui.log(`nullpii: session not closed: ${String(err)}`, { to: 'debug' });
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
      drop: `nullpii could not mask this prompt, so it was not sent (${blocked($, next.error.message)}). Start nullpii-gateway with its sidecar token set, or disable the nullpii mod.`,
    };
  });

  // Text Claude Code adds for Claude on its own: @-mentioned files, edited
  // files, memory and other reminders. Unmaskable means not sent.
  on('prompt.attachment', async ($, e, next) => {
    return next({ ...e, text: String(await masked($, e.text)) });
  }).catch(async ($, e, next) => {
    blocked($, next.error.message);
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
    blocked($, next.error.message);
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
      // the policy's `restoreTools`, and for a shell tool the shell rule
      // (SECURITY.md), which keeps a value Claude never saw masked where
      // the shell would interpret it.
      const r = (await sidecar($, 'POST', '/restore', { value: args, tool: e.tool })) as Restored;
      counts.held += r.heldForTool ?? 0;
      const kept = r.shellKeptMasked ?? [];
      if (kept.length > 0) {
        return {
          deny: `nullpii will not put the real value of ${kept.join(', ')} into this command: in that position the shell would interpret some of its characters, and the value came from data you could not read. Pass it through a file instead, or ask the user to run the command.`,
        };
      }
      // Rewrite the call only when a placeholder was replaced: a rewritten
      // call is denied in auto mode, so untouched calls must stay as written.
      if (r.replacements > 0) {
        counts.restored += r.replacements;
        call = { ...e, ...r.value };
      }
    }
    const out = await next(call);
    // A refusal can quote the arguments, which may now hold real values.
    if (out.deny !== undefined) return { deny: String(await masked($, out.deny)) };
    if (out.isError === true) return { deny: String(await masked($, out.text ?? '')) };
    // A new `{ result }` without `ref`: returning core's object would make
    // core send its own, unmasked messages to the model.
    return {
      result: await masked($, out.result),
      ...(out.context !== undefined && { context: out.context }),
    };
  }).catch(async ($, e, next) => {
    const reason = blocked($, next.error.message);
    if (next.called)
      return { deny: `nullpii could not mask this tool's result, so it was withheld (${reason}).` };
    return {
      deny: `nullpii could not reach its sidecar, so this tool call was not run (${reason}).`,
    };
  });

  // A call that may change the masking policy is put to the user (or, in
  // auto mode, to its classifier), whatever the rules would have decided.
  on('tool.check', async ($, e, next) => {
    const decided = await next(e);
    if (decided.decision === 'deny' || !touchesPolicyFile(e.tool, e.input, policy?.file)) {
      return decided;
    }
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
