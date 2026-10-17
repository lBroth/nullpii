// SPDX-License-Identifier: Apache-2.0
//
// nullpii mod: every prompt and every tool result goes through the local
// nullpii sidecar (`nullpii-gateway` with NULLPII_SIDECAR_TOKEN set) before
// Claude reads it, so personal data and secrets reach the model as
// placeholders. Real values go back only into the arguments of tools that
// run on this machine (policy.ts), so files and commands see what the user
// has, and nothing masked leaves through a web or MCP tool.
//
// Fail closed: when the sidecar cannot be reached, a prompt is handed back
// to the user and a tool call is refused, instead of going out unmasked.
// The vault lives in the sidecar's memory; this mod keeps counts only.

import { RESTORE_FIELDS, addMasked, emptyCounts, formatBand, formatReport } from './policy.ts';

const DEFAULT_SIDECAR_URL = 'http://127.0.0.1:8787';
const SESSIONS_PATH = '/v1/sidecar/sessions/';
const SESSION_NOT_FOUND = 404;
const NO_TOKEN = 'NULLPII_SIDECAR_TOKEN is not set';

interface Sanitized {
  value: unknown;
  captured: number;
  capturedByLabel: Record<string, number>;
}

interface Restored {
  value: Record<string, unknown>;
  replacements: number;
}

// `{{PII_<LABEL>_<index>_<session prefix>}}` (nullpii's PLACEHOLDER_TEMPLATE).
const PLACEHOLDER = /\{\{PII_[A-Z0-9_]+\}\}/;
// Display-only restores, keyed by the masked text. In memory only, bounded,
// and cleared when the session ends.
const SHOWN_MAX = 256;
const shown = new Map<string, string>();

const counts = emptyCounts();
let sidecarUrl = DEFAULT_SIDECAR_URL;
let token: string | undefined;
let sessionKey = '';
// Why the mod is blocking, shown above the prompt; undefined while healthy.
let problem: string | undefined = NO_TOKEN;

class SidecarError extends Error {
  constructor(readonly status: number) {
    super(`nullpii sidecar answered ${status}`);
  }
}

async function sidecar($, method: string, path: string, body?: unknown): Promise<unknown> {
  if (token === undefined) throw new Error(NO_TOKEN);
  // A JSON content type with no body is a 400, so PUT and DELETE send neither.
  const json = body === undefined ? {} : { 'content-type': 'application/json' };
  const res = await $.http.fetch(
    sidecarUrl + SESSIONS_PATH + encodeURIComponent(sessionKey) + path,
    {
      method,
      headers: { authorization: `Bearer ${token}`, ...json },
      ...(body !== undefined && { body: JSON.stringify(body) }),
    },
  );
  if (!res.ok) throw new SidecarError(res.status);
  return res.text === '' ? {} : JSON.parse(res.text);
}

async function openSession($): Promise<void> {
  await sidecar($, 'PUT', '');
  problem = undefined;
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

export function register(on) {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'pii',
      description: 'Show what nullpii masked in this session',
    });
    sidecarUrl = (await $.env.get('NULLPII_SIDECAR_URL')) ?? DEFAULT_SIDECAR_URL;
    token = await $.env.get('NULLPII_SIDECAR_TOKEN');
    sessionKey = await $.session.id();
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
      drop: `nullpii could not mask this prompt, so it was not sent (${blocked($, next.error.message)}). Start nullpii-gateway with NULLPII_SIDECAR_TOKEN set, or disable the nullpii mod.`,
    };
  });

  on('tool.call', async ($, e, next) => {
    const args = Object.fromEntries(
      (RESTORE_FIELDS[e.tool] ?? []).filter((f) => f in e).map((f) => [f, e[f]]),
    );
    let call = e;
    if (Object.keys(args).length > 0) {
      const r = (await sidecar($, 'POST', '/restore', { value: args })) as Restored;
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

  on('command.run', { command: 'pii' }, async () => ({ text: formatReport(counts, problem) }));

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
