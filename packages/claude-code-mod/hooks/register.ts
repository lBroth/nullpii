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
  applyPiiCommand,
  describePolicyChange,
  parsePiiCommand,
  placeholdersToAsk,
  policyLoosening,
  shortName,
} from './categories.ts';
import {
  PLACEHOLDER,
  type Policy,
  addMasked,
  challengeNonce,
  emptyCounts,
  expectedProof,
  formatBand,
  formatPolicy,
  formatReport,
  hasPlaceholder,
  optionFlag,
  optionString,
  placeholderGuide,
  restorableArgs,
  sameText,
  sidecarOrigin,
  touchesPolicyFile,
} from './policy.ts';

/** The manifest's default for `sidecar_url`, for an option saved empty. */
const DEFAULT_SIDECAR_URL = 'http://127.0.0.1:8787';
const SESSIONS_PATH = '/v1/sidecar/sessions/';
const STATUS_PATH = '/v1/sidecar/status';
const POLICY_PATH = '/v1/sidecar/policy';
/** The version of the policy this session made or accepted, sent with
 * every call: the sidecar answers 412 and does nothing once the policy has
 * changed since (the token alone can change it). */
const POLICY_VERSION_HEADER = 'x-nullpii-policy-version';
const POLICY_CHANGED = 412;
/** The answers of the dialog about a policy change this session did not make. */
const KEEP_POLICY = 'Keep the change';
const REVERT_POLICY = 'Put back the previous policy';
/** The tool `$.ui.ask` puts a question to the user through, and the
 * header the mod's own questions carry. */
const DIALOG_TOOL = 'AskUserQuestion';
const DIALOG_HEADER = 'nullpii';
/** Where the mod keeps the policy it last made or accepted, so a change
 * made between sessions is put to the user at the next one. */
const ACCEPTED_POLICY_KEY = 'acceptedPolicy';
/** The answers of the dialog that asks before masking a value in the
 * user's own prompt (a category whose mode is `ask`). */
const ASK_MASK = 'Mask';
const ASK_READABLE = 'Send readable';
const ASK_ALWAYS_READABLE = 'Always readable';
/** How much of a value the dialog shows. */
const ASK_PREVIEW_CHARS = 60;
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
const STARTING = 'starting nullpii-gateway for this session (its first start downloads the model)';
const NOT_STARTED = 'the nullpii-gateway this session started did not answer in time';
const STARTED_EXITED =
  'the nullpii-gateway this session started exited before it answered: run its npx command (README, Set up) in a terminal to see why';
const NO_POLICY =
  'the sidecar reported no policy version: run nullpii-gateway 0.5.0 or later there';
/** The release of the packages the mod starts the sidecar from, and the
 * ONNX runtime that release is built and tested with, at exact versions
 * (their own dependencies are resolved by npx at the time). */
const GATEWAY_RELEASE = '0.5.0';
const ONNXRUNTIME_RELEASE = '1.30.0';
/** The command that starts the sidecar: the release's CLI, gateway and
 * ONNX runtime, with npx (no shell). */
const GATEWAY_ARGV = [
  'npx',
  '-y',
  '-p',
  `nullpii@${GATEWAY_RELEASE}`,
  '-p',
  `onnxruntime-node@${ONNXRUNTIME_RELEASE}`,
  '-p',
  `@lbroth/nullpii-gateway@${GATEWAY_RELEASE}`,
  'nullpii-gateway',
];
/** Where npx runs: the file system root, not the session's directory, so a
 * repository's `.npmrc` cannot pick the registry the gateway, which gets
 * the token, comes from. */
const GATEWAY_CWD = '/';
/** How long a sidecar the mod started may take to answer, and how often
 * the mod checks: the first start downloads the model. */
const STARTUP_WAIT_MS = 10 * 60 * 1000;
const STARTUP_POLL_MS = 2_000;
/** The port nullpii-gateway listens on when the address names none. */
const DEFAULT_SIDECAR_PORT = '8787';
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
  STARTING,
  NOT_STARTED,
  STARTED_EXITED,
  NO_POLICY,
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
// The policy the sidecar runs with, as this session made or accepted it:
// read when the session opens, replaced by /pii and by the user's answer
// about a change made elsewhere.
let policy: Policy | undefined;
// Why the mod is blocking, shown above the prompt; undefined while healthy.
let problem: string | undefined = NO_TOKEN;
// The sidecar this session started, until it answers: `running`, or
// `exited` once its process ended first.
let started: 'running' | 'exited' | undefined;
// The session (re)opening in flight, which every hook that needs one awaits.
let opening: Promise<void> | undefined;
// The review of a policy changed elsewhere, which every call the sidecar
// refused for it awaits.
let reviewing: Promise<void> | undefined;
// The question the mod is putting about a policy change, while it waits for
// the answer: the one dialog whose tool call is not masked (its answer comes
// back to the mod, and masking it would wait on the same review).
let ownQuestion: string | undefined;

class SidecarError extends Error {
  constructor(readonly status: number) {
    super(`nullpii sidecar answered ${status}`);
  }
}

/** Send one request to the sidecar's route `path`, with the session
 * secret when one is given, and the policy version `version` (by default
 * the one this session accepted). Nothing is sent, the token included,
 * unless the sidecar's address is a loopback one and the process there
 * has just proved it holds the token: another process could have taken
 * the port since the last request (the gateway stopped, or restarted). */
async function request(
  $,
  method: string,
  path: string,
  body?: unknown,
  secret?: string,
  version: string | undefined = policy?.version,
): Promise<unknown> {
  if (sidecarUrl === undefined) throw new Error(NOT_LOOPBACK);
  if (token === undefined) throw new Error(NO_TOKEN);
  await checkSidecar($, sidecarUrl, token);
  // A JSON content type with no body is a 400, so PUT and DELETE send neither.
  const json = body === undefined ? {} : JSON_TYPE;
  const owner = secret === undefined ? {} : { [SESSION_SECRET_HEADER]: secret };
  const seen = version === undefined ? {} : { [POLICY_VERSION_HEADER]: version };
  const res = await fetchSidecar($, sidecarUrl + path, {
    method,
    headers: { authorization: `Bearer ${token}`, ...json, ...owner, ...seen },
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

function isStatus(err: unknown, status: number): boolean {
  return err instanceof SidecarError && err.status === status;
}

/** Call this session's sidecar route `path` (`/sanitize`, `/restore`),
 * always under a policy version this session accepted. A call the sidecar
 * refused because the policy changed is made again once the user has
 * settled the change. */
async function sidecar($, method: string, path: string, body?: unknown): Promise<unknown> {
  if (policy === undefined) await reviewPolicy($);
  const call = () =>
    request($, method, SESSIONS_PATH + encodeURIComponent(sessionKey) + path, body, sessionSecret);
  try {
    return await call();
  } catch (err) {
    if (!isStatus(err, POLICY_CHANGED)) throw err;
    await reviewPolicy($);
    return call();
  }
}

/** Read the policy the sidecar runs with and settle it with the user,
 * once for every call the sidecar refused meanwhile. */
function reviewPolicy($): Promise<void> {
  reviewing ??= (async () => {
    const status = (await request($, 'GET', STATUS_PATH)) as { policy?: Policy };
    await settlePolicy($, status.policy);
  })().finally(() => {
    reviewing = undefined;
  });
  return reviewing;
}

/**
 * Take `now`, the policy the sidecar runs with, as this session's. A
 * change since the policy this session made or accepted (another
 * session's /pii, a hand edit and a restart, a command holding the sidecar
 * token) is put to the user: kept on their word, else the previous policy
 * is put back, which is also what happens when no one can answer. Until
 * then the sidecar refuses this session's calls, so nothing is masked or
 * restored under a policy the user has not seen.
 */
async function settlePolicy($, now: Policy | undefined): Promise<void> {
  if (now?.version === undefined) throw new Error(NO_POLICY);
  // At a session's first look, the policy the mod accepted last time.
  const before = policy ?? ((await $.store.get(ACCEPTED_POLICY_KEY)) as Policy | undefined);
  if (before === undefined || before.version === now.version) {
    await accept($, now);
    return;
  }
  const since = policy === undefined ? 'since your last session' : "outside this session's /pii";
  const less = policyLoosening(before, now);
  const warning = less.length > 0 ? ` This change masks less: ${less.join('; ')}.` : '';
  const question = `The nullpii masking policy was changed ${since}: ${describePolicyChange(before, now)}.${warning} Keep the change?`;
  let answer = REVERT_POLICY;
  ownQuestion = question;
  try {
    answer = await $.ui.ask(question, {
      header: DIALOG_HEADER,
      // Putting the policy back comes first, so a quick confirm keeps it.
      options: [REVERT_POLICY, KEEP_POLICY],
    });
  } catch (err) {
    $.ui.log(`nullpii: no answer about a policy change (${errorName(err)}); putting it back`, {
      to: 'debug',
    });
  } finally {
    ownQuestion = undefined;
  }
  if (answer === KEEP_POLICY) {
    await accept($, now);
    return;
  }
  await accept($, await putPolicy($, before.config, now.version));
  $.ui.toast('nullpii put back the masking policy you had accepted');
}

/** Make `accepted` this session's policy, and remember it for the next. */
async function accept($, accepted: Policy): Promise<void> {
  policy = accepted;
  await $.store.set(ACCEPTED_POLICY_KEY, accepted);
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
  await reviewPolicy($);
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
  // While the sidecar this session started comes up, say so, not that no
  // sidecar runs (which would send the user off to start a second one).
  const reason =
    started === 'running' && failure.message === UNREACHABLE ? STARTING : shownReason(failure);
  problem = reason;
  const withheld =
    reason === HIDDEN_REASON && failure.message !== undefined
      ? ` (${failure.message.length} characters withheld)`
      : '';
  $.ui.log(`nullpii: ${event} failed (${failure.kind}): ${reason}${withheld}`, { to: 'debug' });
  $.ui.invalidate('ui.render');
  return reason;
}

/**
 * Start nullpii-gateway, with its sidecar, for this session's life: the
 * token and the address go to it through its environment, and it is
 * stopped with the session (or the mod). Its output, request counts
 * only, is drained and not shown.
 */
function startSidecar($, origin: string, secretToken: string): void {
  const address = new URL(origin);
  const child = $.process.spawn({
    argv: GATEWAY_ARGV,
    cwd: GATEWAY_CWD,
    env: {
      NULLPII_SIDECAR_TOKEN: secretToken,
      NULLPII_HOST: address.hostname.replace(/^\[|\]$/g, ''),
      NULLPII_PORT: address.port === '' ? DEFAULT_SIDECAR_PORT : address.port,
    },
  });
  void (async () => {
    try {
      for await (const _piece of child) {
        // Drained: the gateway logs counts, and the mod shows its own state.
      }
      $.ui.log('nullpii: the nullpii-gateway this session started has exited', { to: 'debug' });
    } catch (err) {
      $.ui.log(`nullpii: nullpii-gateway did not start (${errorName(err)})`, { to: 'debug' });
    }
    if (started === 'running') started = 'exited';
  })();
}

/** Open the session once the sidecar the mod started answers, or give up
 * after `STARTUP_WAIT_MS`; the band shows which. */
async function waitForSidecar($): Promise<void> {
  const deadline = (await $.clock.now()) + STARTUP_WAIT_MS;
  while ((await $.clock.now()) < deadline) {
    await $.clock.sleep(STARTUP_POLL_MS);
    try {
      await openSession($);
      started = undefined;
      $.ui.invalidate('ui.render');
      $.ui.toast('nullpii is on');
      return;
    } catch (err) {
      if (!(err instanceof Error) || err.message !== UNREACHABLE) {
        started = undefined;
        blocked($, 'sidecar start', failureOf(err));
        return;
      }
    }
    // Nothing answers and the process is gone (npx found no package, or
    // the port was taken): no point in waiting out the deadline.
    if (started === 'exited') {
      started = undefined;
      blocked($, 'sidecar start', { kind: THROW_KIND, message: STARTED_EXITED });
      return;
    }
  }
  started = undefined;
  blocked($, 'sidecar start', { kind: THROW_KIND, message: NOT_STARTED });
}

/** Send the policy file contents `config` to the sidecar, which writes
 * and applies it unless the policy is no longer at `version`; resolves to
 * the policy now in effect. */
async function putPolicy(
  $,
  config: Readonly<Record<string, unknown>>,
  version: string | undefined = policy?.version,
): Promise<Policy> {
  const answer = (await request($, 'PUT', POLICY_PATH, { config }, undefined, version)) as {
    policy: Policy;
  };
  return answer.policy;
}

/** Apply `change` to this session's policy and send it. A policy changed
 * meanwhile is settled with the user first, and `change` applied to the
 * policy that comes out of it, so no other change is silently undone. */
async function changePolicy(
  $,
  change: (config: Readonly<Record<string, unknown>>) => Record<string, unknown>,
): Promise<Policy> {
  const current = policy;
  if (current === undefined) throw new Error(UNREACHABLE);
  try {
    await accept($, await putPolicy($, change(current.config)));
  } catch (err) {
    if (!isStatus(err, POLICY_CHANGED)) throw err;
    await reviewPolicy($);
    const settled = policy as Policy | undefined;
    if (settled === undefined) throw err;
    await accept($, await putPolicy($, change(settled.config)));
  }
  return policy as Policy;
}

/**
 * The masked prompt `text`, after asking the user about the values of the
 * categories whose mode is `ask`: masked as they are, sent readable, or
 * sent readable with those categories left readable from now on. A dialog
 * that is dismissed, or that no one can answer (`claude -p`), keeps them
 * masked. The values are shown on this machine only.
 */
async function confirmed($, text: string): Promise<string> {
  const asked = placeholdersToAsk(text, policy?.categories);
  if (asked.length === 0) return text;
  const restored = (await sidecar($, 'POST', '/restore', {
    value: asked.map((a) => a.placeholder),
  })) as { value: string[] };
  const values = restored.value;
  const listed = asked.map((a, i) => `${shortName(a.category)} "${preview(values[i] ?? '')}"`);
  const categories = [...new Set(asked.map((a) => a.category))];
  let answer: string;
  try {
    answer = await $.ui.ask(`nullpii would mask ${listed.join(', ')} in your prompt. Mask?`, {
      header: 'nullpii',
      options: [ASK_MASK, ASK_READABLE, ASK_ALWAYS_READABLE],
    });
  } catch (err) {
    $.ui.log(`nullpii: no answer to the mask dialog (${errorName(err)}); kept masked`, {
      to: 'debug',
    });
    return text;
  }
  if (answer !== ASK_READABLE && answer !== ASK_ALWAYS_READABLE) return text;
  if (answer === ASK_ALWAYS_READABLE && policy !== undefined) {
    const command = { kind: 'set', mode: 'off', categories } as const;
    await changePolicy($, (config) => applyPiiCommand(config, command));
  }
  return asked.reduce(
    (out, a, i) => out.split(a.placeholder).join(values[i] ?? a.placeholder),
    text,
  );
}

/** Whether `call` is the question the mod is putting about a policy
 * change right now (its text and header), and no other dialog. */
function isOwnQuestion(call: Readonly<Record<string, unknown>>): boolean {
  if (ownQuestion === undefined || call.tool !== DIALOG_TOOL) return false;
  const questions = call.questions;
  if (!Array.isArray(questions) || questions.length !== 1) return false;
  const [only] = questions as { question?: unknown; header?: unknown }[];
  return only?.question === ownQuestion && only?.header === DIALOG_HEADER;
}

/** `value` cut to `ASK_PREVIEW_CHARS`, for the dialog. */
function preview(value: string): string {
  return value.length > ASK_PREVIEW_CHARS ? `${value.slice(0, ASK_PREVIEW_CHARS)}…` : value;
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
      description:
        'Show what nullpii masked and its policy; change it: /pii preset agent|secrets|all, /pii mask|ask|off <category…>, /pii reset',
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
      // No sidecar answers: start one for this session when allowed. The
      // band says so, and prompts wait (they are refused) until it answers.
      const unreachable = err instanceof Error && err.message === UNREACHABLE;
      if (unreachable && optionFlag(options, 'autostart', true) && sidecarUrl && token) {
        started = 'running';
        startSidecar($, sidecarUrl, token);
        problem = STARTING;
        $.ui.invalidate('ui.render');
        void waitForSidecar($).catch((err) => blocked($, 'sidecar start', failureOf(err)));
        return next(e);
      }
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
    // Only what the user typed is put to them; text the engine adds is not.
    const text = e.isMeta === true ? out.text : await confirmed($, out.text);
    return next({ ...e, text, ...(e.context !== undefined && { context: out.context }) });
  }).catch(async ($, e, next) => {
    if (next.called) return next(e);
    const reason = blocked($, 'prompt.submit', next.error);
    const fix =
      reason === STARTING
        ? 'Send it again once nullpii is on.'
        : 'Start nullpii-gateway with its sidecar token set, or disable the nullpii mod.';
    return { drop: `nullpii could not mask this prompt, so it was not sent (${reason}). ${fix}` };
  });

  // Tell Claude what the placeholders are. Without it Claude asks the user
  // for the real values, or says a file it wrote holds a placeholder.
  on('prompt.compose', async ($, e, next) => {
    const composed = await next(e);
    const section = {
      id: 'nullpii:placeholders',
      text: placeholderGuide(policy?.restoreTools),
      scope: 'session',
    } as const;
    return { sections: [...composed.sections, section] };
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
    if (isOwnQuestion(e)) return next(e);
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

  on('command.run', { command: 'pii' }, async ($, e) => {
    const command = parsePiiCommand(e.args ?? '');
    if (command.kind === 'error') return { text: command.message };
    if (command.kind === 'status') {
      // The policy as the sidecar has it now, a change made elsewhere
      // settled first; without an answer, the last one this session saw.
      if (policy !== undefined) {
        await reviewPolicy($).catch((err) =>
          $.ui.log(`nullpii: policy not read again: ${shownReason(failureOf(err))}`, {
            to: 'debug',
          }),
        );
      }
      return { text: formatReport(counts, problem, policy) };
    }
    if (policy === undefined) {
      return { text: 'nullpii: the sidecar has not answered, so the policy cannot change now.' };
    }
    try {
      const changed = await changePolicy($, (config) => applyPiiCommand(config, command));
      return { text: ['Policy changed.', ...formatPolicy(changed)].join('\n') };
    } catch (err) {
      return { text: `nullpii could not change the policy: ${shownReason(failureOf(err))}` };
    }
  });

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
