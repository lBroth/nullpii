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
  CATEGORY_SHORT_NAMES,
  type Mode,
  type PiiCommand,
  applyPiiCommand,
  describePolicyChange,
  formatPiiHelp,
  parsePiiCommand,
  piiCommandDescription,
  placeholdersToAsk,
  policyLoosening,
  shortName,
} from './categories.ts';
import { PADLOCK_COLUMNS, PADLOCK_ROWS, type PadlockTone, padlockCells } from './padlock.ts';
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
/** The answers of the dialog that asks before masking is paused: keeping
 * it comes first, so a quick confirm keeps masking on. */
const KEEP_MASKING = 'Keep masking';
const PAUSE_MASKING = 'Pause masking';
/** The question that asks before masking is paused. */
const PAUSE_QUESTION =
  'Everything you send until nullpii is turned on again reaches Claude unmasked. Pause masking for this session?';
/** What any pause request that is not the person's own is told: only
 * their own typed command or the band's toggle can pause masking. */
const PAUSE_REFUSED = 'nullpii pauses masking only when you ask for it yourself at the prompt.';
/** The band's pause toggle, beside the padlock. */
const TOGGLE_KEY = 'nullpii-toggle';
/** The padlock's key, in the band. */
const LOCK_KEY = 'nullpii-lock';
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
  'nullpii-gateway did not answer at the sidecar address: start it with NULLPII_SIDECAR_TOKEN set (with npx, or the Docker image: start Docker first), or turn on the "Start the sidecar" option';
const NOT_JSON = 'the sidecar answered with something that is not JSON';
/** One phase of the start of a sidecar this session started: its packages
 * installing, the model downloading, the model loading. While the mod is
 * in one, nothing is sent (fail closed) and the band shows it. */
type StartupPhase = 'installing' | 'downloading' | 'loading';
/** How the band names each phase of the start. */
const PHASE_WORDS: Readonly<Record<StartupPhase, string>> = {
  installing: 'installing its packages',
  downloading: 'downloading the model',
  loading: 'loading the model',
};
/** The prefix of the band's phase line, and the whole line's shape. */
const STARTING_PREFIX = 'starting nullpii-gateway for this session';
const PHASE_LINE = /^starting nullpii-gateway for this session \(.*\)$/;
/** A file name the sidecar reports for the model download, shown in the
 * band only when it is a plain short one; anything else is left out. */
const SAFE_FILE_NAME = /^[\w.-]{1,64}$/;
const NOT_STARTED = 'the nullpii-gateway this session started did not answer in time';
/** The give-up lines for a sidecar this session started, which name the
 * phase it was in: dynamic texts the mod itself writes. */
const EXITED_LINE =
  /^the nullpii-gateway this session started exited while [a-z ]+: run its npx command \(README, Set up\) in a terminal to see why$/;
const WARMUP_FAILED_LINE =
  /^the nullpii-gateway this session started failed while [a-z ]+: run its npx command \(README, Set up\) in a terminal to see why$/;
const NOT_READY_LINE =
  /^the nullpii-gateway this session started did not get the model ready in time \(still [a-z ]+\)$/;
const NO_POLICY =
  'the sidecar reported no policy version: run nullpii-gateway 0.5.0 or later there';
/** The release of the packages the mod starts the sidecar from, and the
 * ONNX runtime that release is built and tested with, at exact versions
 * (their own dependencies are resolved by npx at the time). */
const GATEWAY_RELEASE = '0.5.2';
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
  NOT_STARTED,
  NO_POLICY,
]);
/** SidecarError's text, the one with a variable part. */
const SIDECAR_STATUS = /^nullpii sidecar answered \d{3}$/;
/** The other variable texts this mod writes: a start-up phase line, or a
 * give-up line that names the phase. */
function ownLine(text: string): boolean {
  return (
    PHASE_LINE.test(text) ||
    EXITED_LINE.test(text) ||
    WARMUP_FAILED_LINE.test(text) ||
    NOT_READY_LINE.test(text)
  );
}
/** The band's line while a sidecar this session started comes up: which
 * phase it is in, with the bytes of the model download when it reports
 * them. Every word is the mod's own. */
function phaseLine(): string {
  if (phase === 'downloading' && download !== undefined) {
    const whole = download.total !== undefined ? ` / ${mb(download.total)}` : '';
    const file = SAFE_FILE_NAME.test(download.file) ? `, ${download.file}` : '';
    return `${STARTING_PREFIX} (${PHASE_WORDS.downloading} · ${mb(download.received)}${whole} MB${file})`;
  }
  return `${STARTING_PREFIX} (${PHASE_WORDS[phase ?? 'installing']})`;
}
/** `bytes` as whole megabytes, for the band (`640 / 1,160`). */
function mb(bytes: number): string {
  return Math.round(bytes / 1e6).toLocaleString('en-US');
}
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
/** The refusal for the mod's own dialog when putting the question failed:
 * the asking code reports it (and never fails open over it), and nothing
 * else is blocked, since no value was masked or restored for the dialog. */
const DIALOG_FAILED = 'nullpii could not put its question to you.';

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
// The start-up phase of a sidecar this session started: undefined once
// its model is ready, or when the mod started none. While it is set
// nothing is sent (fail closed), and the band shows the phase.
let phase: StartupPhase | undefined;
// The file downloading and its bytes so far, while `phase` is
// `downloading`, as the sidecar's status reports them.
let download:
  | { readonly file: string; readonly received: number; readonly total?: number }
  | undefined;
// The session (re)opening in flight, which every hook that needs one awaits.
let opening: Promise<void> | undefined;
// Whether the user paused masking for this session: everything they send
// then reaches Claude unmasked, until they turn it on again or the session
// ends. This session's state alone, in memory: never the policy file, and
// a paused session whose sidecar is not up still sends nothing (fail
// closed, through `problem`).
let paused = false;
// What to do with a prompt sent while the sidecar this session started is
// still coming up (the `while_starting` option): ask the person, always
// wait, or always send it unprotected.
let whileStarting: 'ask' | 'block' | 'pass' = 'ask';
// The person said to send unprotected until this start-up is ready: the
// answer holds for this start only.
let startPass = false;
// The review of a policy changed elsewhere, which every call the sidecar
// refused for it awaits.
let reviewing: Promise<void> | undefined;
// The questions the mod is putting to the user, while it waits for the
// answers: the dialogs whose tool calls this mod's tool.call hook leaves
// alone. An answer comes back to the mod, and masking it would lose it (the
// result names the question, which shows the real value being asked about)
// or wait on the same policy review.
const ownQuestions = new Set<string>();

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
  try {
    // Putting the policy back comes first, so a quick confirm keeps it.
    answer = await askUser($, question, [REVERT_POLICY, KEEP_POLICY]);
  } catch (err) {
    $.ui.log(`nullpii: no answer about a policy change (${errorName(err)}); putting it back`, {
      to: 'debug',
    });
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
  // A band drawn before the session opened (a hot reload draws it at once,
  // from the module's starting state) would keep showing that state.
  redraw($);
}

/** Mask every string in `value`. A session the sidecar dropped (restart or
 * idle TTL) is opened again: nothing restores into it, but masking works.
 * While a sidecar this session started comes up, nothing is sent at all:
 * the call fails closed with the band's phase line. */
async function sanitize($, value: unknown): Promise<Sanitized> {
  if (phase !== undefined) throw new Error(phaseLine());
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
  redraw($);
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
  return OWN_REASONS.has(message) || SIDECAR_STATUS.test(message) || ownLine(message)
    ? message
    : HIDDEN_REASON;
}

/** Turn the band red with why `event` failed, and log the same to the
 * debug log, with only the length of a text that is not shown. */
function blocked($, event: string, failure: Failure): string {
  // While the sidecar this session started comes up, say which phase it is
  // in, not that no sidecar runs (which would send the user off to start a
  // second one).
  const reason =
    started === 'running' && failure.message === UNREACHABLE ? phaseLine() : shownReason(failure);
  problem = reason;
  const withheld =
    reason === HIDDEN_REASON && failure.message !== undefined
      ? ` (${failure.message.length} characters withheld)`
      : '';
  $.ui.log(`nullpii: ${event} failed (${failure.kind}): ${reason}${withheld}`, { to: 'debug' });
  redraw($);
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

/** One step of the sidecar's own start-up, as its status reports it (the
 * `startup` field, nullpii-gateway 0.5.1 and later): a model file downloading, the
 * model loading, or the model ready. */
interface StartupReport {
  readonly phase?: unknown;
  readonly file?: unknown;
  readonly received?: unknown;
  readonly total?: unknown;
  readonly while?: unknown;
}

/** The give-up lines, which name the phase the start was in when it ended
 * (or, for a failed warmup, the phase the sidecar says failed). */
function exitedLine(): string {
  return `the nullpii-gateway this session started exited while ${PHASE_WORDS[phase ?? 'installing']}: run its npx command (README, Set up) in a terminal to see why`;
}
function warmupFailedLine(while_: 'downloading' | 'loading'): string {
  return `the nullpii-gateway this session started failed while ${PHASE_WORDS[while_]}: run its npx command (README, Set up) in a terminal to see why`;
}
function notReadyLine(): string {
  return `the nullpii-gateway this session started did not get the model ready in time (still ${PHASE_WORDS[phase ?? 'installing']})`;
}

/** A sidecar this session started did not come up: the band says why
 * (`message`), and later prompts take the normal path again — masking
 * works once some gateway answers, and until one does, fail closed. */
function gaveUp($, message: string): void {
  started = undefined;
  phase = undefined;
  download = undefined;
  problem = message;
  $.ui.log(`nullpii: the sidecar this session started did not come up: ${message}`, {
    to: 'debug',
  });
  redraw($);
}

/** Wait for the sidecar this session started to be ready: its status says
 * which phase it is in (the model download's bytes among them), the band
 * shows each one, and the session opens once the model is ready. A
 * gateway with no `startup` field (0.5) counts as ready. Gives up after
 * `STARTUP_WAIT_MS`, or at once when the process exits or the warmup
 * fails, saying which phase it was in. */
async function waitForSidecar($): Promise<void> {
  const deadline = (await $.clock.now()) + STARTUP_WAIT_MS;
  while ((await $.clock.now()) < deadline) {
    await $.clock.sleep(STARTUP_POLL_MS);
    let status: unknown;
    try {
      status = await request($, 'GET', STATUS_PATH);
    } catch (err) {
      if (!(err instanceof Error) || err.message !== UNREACHABLE) {
        // The status request itself failed: show why, and take the normal
        // path again.
        const reason = blocked($, 'sidecar start', failureOf(err));
        gaveUp($, reason);
        return;
      }
      // Nothing answers yet: npx is still installing the packages. The
      // process being gone already (no package found, port taken) ends
      // the wait at once, as before.
      if (started === 'exited') {
        gaveUp($, exitedLine());
        return;
      }
      continue;
    }
    const startup = (status as { startup?: StartupReport }).startup;
    // No field: an old gateway, already ready once it answers; `ready`:
    // the model is loaded. Either way the session opens as before.
    if (startup === undefined || startup.phase === 'ready') {
      started = undefined;
      phase = undefined;
      download = undefined;
      await openSession($);
      problem = undefined;
      startPass = false;
      redraw($);
      $.ui.toast('nullpii is on');
      return;
    }
    if (startup.phase === 'failed') {
      gaveUp($, warmupFailedLine(startup.while === 'loading' ? 'loading' : 'downloading'));
      return;
    }
    if (startup.phase === 'downloading') {
      phase = 'downloading';
      download = {
        file: typeof startup.file === 'string' ? startup.file : '',
        received: typeof startup.received === 'number' ? startup.received : 0,
        ...(typeof startup.total === 'number' && { total: startup.total }),
      };
    } else if (startup.phase === 'loading') {
      phase = 'loading';
      download = undefined;
    } else {
      // A phase a newer gateway reports and this mod does not know: keep
      // the last one shown; the deadline still ends the wait.
      continue;
    }
    problem = phaseLine();
    redraw($);
  }
  // Nothing ever answered (`installing`, the phase the start began in), or
  // the model was not ready in time.
  gaveUp($, phase === 'installing' || phase === undefined ? NOT_STARTED : notReadyLine());
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
    answer = await askUser($, `nullpii would mask ${listed.join(', ')} in your prompt. Mask?`, [
      ASK_MASK,
      ASK_READABLE,
      ASK_ALWAYS_READABLE,
    ]);
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

/** Put `question` to the user in the mod's own dialog, which the mod's
 * tool.call hook then leaves alone (`isOwnQuestion`). A multi-select
 * answer comes back with its labels joined with commas. */
async function askUser(
  $,
  question: string,
  options: readonly string[],
  multiSelect = false,
): Promise<string> {
  ownQuestions.add(question);
  const dialog = multiSelect
    ? { header: DIALOG_HEADER, options, multiSelect: true }
    : { header: DIALOG_HEADER, options };
  try {
    return await $.ui.ask(question, dialog);
  } finally {
    ownQuestions.delete(question);
  }
}

/** The line pinned under the prompt, always there: the state in a few
 * words, as the band above the prompt has it in full. */
function statusLine(): string {
  if (paused) return '[nullpii] paused · what you send is not masked';
  if (startPass && starting()) return '[nullpii] not protected yet · starting';
  if (starting()) return '[nullpii] starting';
  if (problem !== undefined) return '[nullpii] blocking';
  return counts.masked === 0 ? '[nullpii] on' : `[nullpii] on · ${counts.masked} masked`;
}

/** Draw the band again and pin the status line, after any change of state. */
function redraw($): void {
  $.ui.invalidate('ui.render');
  $.ui.status(statusLine());
}

/** Whether the sidecar this session started is still coming up. */
function starting(): boolean {
  return started === 'running' && problem?.startsWith(STARTING_PREFIX) === true;
}

/** Whether what is sent goes to Claude as it is: masking paused with the
 * sidecar up, or the person chose to send unprotected while it starts. */
function bypassing(): boolean {
  return (paused && problem === undefined) || (startPass && starting());
}

/** The band's line: while the person sends unprotected through a start-up,
 * it says so and keeps the phase; otherwise the usual line. */
function bandText(): string {
  if (startPass && starting() && problem !== undefined) {
    const detail = problem.slice(STARTING_PREFIX.length).replace(/^ \((.*)\)$/, '$1');
    return `nullpii · not protected yet · ${detail}`;
  }
  return formatBand(counts, problem, paused);
}

/** The band's colour: red for a pause or a fault, amber while nullpii
 * starts (progress, not a fault), green when it is on. */
function bandColor(): 'red' | 'yellow' | 'green' {
  if (paused) return 'red';
  if (starting()) return 'yellow';
  return problem !== undefined ? 'red' : 'green';
}

/** The padlock for the current state, as its `open` and tone: closed teal
 * when on, open amber while starting, open red while paused, closed grey
 * when broken. */
function padlockLook(): [boolean, PadlockTone] {
  if (paused) return [true, 'red'];
  if (starting()) return [true, 'amber'];
  return problem !== undefined ? [false, 'grey'] : [false, 'teal'];
}

/** The answers of the dialog put to the person who sends a prompt while
 * nullpii is still starting. */
const WAIT_FOR_NULLPII = 'Wait for nullpii (the prompt is sent masked when it is ready)';
const SEND_UNPROTECTED = 'Send it now, unprotected';
const SEND_UNPROTECTED_UNTIL_READY = 'Send now, and do not ask again until nullpii is ready';
const STARTING_QUESTION =
  'nullpii is still starting, so this prompt would not be protected: what you send reaches Claude as you typed it. Wait for nullpii, or send it now?';

/** How long a prompt is held for a sidecar still coming up, and how often
 * the hold looks: past it the prompt goes back to the person, as before. */
const HOLD_MAX_MS = 5 * 60 * 1000;
const HOLD_POLL_MS = 1_000;

/** Hold the prompt while the sidecar this session started comes up. True
 * once it is ready, so the prompt goes on to be masked and sent; false when
 * the start gave up or took longer than `HOLD_MAX_MS`. */
async function holdUntilReady($): Promise<boolean> {
  const deadline = (await $.clock.now()) + HOLD_MAX_MS;
  while (starting() && (await $.clock.now()) < deadline) await $.clock.sleep(HOLD_POLL_MS);
  return !starting() && problem === undefined;
}

/** Whether a prompt the person typed goes out unprotected while nullpii
 * starts: their answer to the dialog, or the `while_starting` option. A
 * dialog dismissed, or one no one can answer (`claude -p`), waits. */
async function sendUnprotectedWhileStarting($): Promise<boolean> {
  if (!starting()) return false;
  if (startPass) return true;
  if (whileStarting === 'block') return false;
  if (whileStarting === 'pass') {
    startPass = true;
    redraw($);
    return true;
  }
  let answer: string;
  try {
    answer = await askUser($, STARTING_QUESTION, [
      WAIT_FOR_NULLPII,
      SEND_UNPROTECTED,
      SEND_UNPROTECTED_UNTIL_READY,
    ]);
  } catch (err) {
    $.ui.log(`nullpii: no answer to the start-up dialog (${errorName(err)}); waits`, {
      to: 'debug',
    });
    return false;
  }
  if (answer === SEND_UNPROTECTED_UNTIL_READY) {
    startPass = true;
    redraw($);
  }
  return answer === SEND_UNPROTECTED || answer === SEND_UNPROTECTED_UNTIL_READY;
}

/** The origins a pause may come from: the person's own typed command, at
 * the prompt (the engine's stamp for their gesture) or through their Remote
 * Control client. Everything else — the model or a hook issuing the command
 * in their name, an SDK run, an MCP relay, one the engine could not attest —
 * is not the person's, and a pause from it is refused. */
const PERSON_ORIGINS: ReadonlySet<string> = new Set(['composer', 'bridge']);

/** Turn masking off for this session, once the person has said so in the
 * mod's own dialog: a dialog dismissed, or one no one can answer (`claude
 * -p`), keeps masking on. A paused session whose sidecar is not up still
 * sends nothing (fail closed, through `problem`). */
async function pauseMasking($): Promise<boolean> {
  let answer: string;
  try {
    // Keeping it comes first, so a quick confirm keeps masking on.
    answer = await askUser($, PAUSE_QUESTION, [KEEP_MASKING, PAUSE_MASKING]);
  } catch (err) {
    $.ui.log(`nullpii: no answer to the pause dialog (${errorName(err)}); kept masked`, {
      to: 'debug',
    });
    return false;
  }
  if (answer !== PAUSE_MASKING) return false;
  paused = true;
  redraw($);
  return true;
}

/** Turn masking back on for this session. */
function resumeMasking($): void {
  paused = false;
  redraw($);
}

/** Whether `call` is a question the mod is putting right now (its text and
 * header), and no other dialog. */
function isOwnQuestion(call: Readonly<Record<string, unknown>>): boolean {
  if (call.tool !== DIALOG_TOOL) return false;
  const questions = call.questions;
  if (!Array.isArray(questions) || questions.length !== 1) return false;
  const [only] = questions as { question?: unknown; header?: unknown }[];
  return (
    typeof only?.question === 'string' &&
    ownQuestions.has(only.question) &&
    only.header === DIALOG_HEADER
  );
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

/** A `/pii` run: every command but the menu itself. */
type RunnablePiiCommand = Exclude<PiiCommand, { kind: 'menu' }>;

/** One entry of the menu: the text it shows, and the command it runs. */
interface MenuEntry {
  readonly label: string;
  readonly command: PiiCommand;
}

/** The entry that runs `/pii <args>`: its text is the command's own
 * description (`PII_COMMANDS`), and the command is the one a typed
 * `/pii <args>` parses to, so both run the same code. */
function menuEntry(args: string): MenuEntry {
  return { label: piiCommandDescription(args), command: parsePiiCommand(args) };
}

/** The menu `/pii` opens with no arguments. The engine's dialog takes at
 * most four options, so the commands are grouped: the state and the
 * presets, a category, and the rest. Every entry runs what its typed
 * command runs, guards included. */
const MENU_QUESTION = 'nullpii: what do you want to do?';
const MENU_PRESETS = 'Preset: agent, secrets or all…';
const MENU_CATEGORIES = 'A category: mask, ask or off…';
const MENU_MORE = 'More: pause, reset, help…';
const MENU_PRESET_QUESTION = 'nullpii: which preset?';
const MENU_MODE_QUESTION = 'nullpii: what should happen to a category?';
const MENU_CATEGORY_QUESTION: Readonly<Record<Mode, string>> = {
  mask: 'nullpii: which categories should be masked?',
  ask: 'nullpii: which categories should nullpii ask you about in your prompts?',
  off: 'nullpii: which categories should be left readable?',
};
const MENU_MORE_QUESTION = 'nullpii: what else?';
/** The entry that opens the next page of the category list. */
const MENU_CATEGORY_MORE = 'More categories…';
/** The categories one dialog lists: it takes four options, and the fourth
 * opens the next page, so a page holds `MENU_CATEGORY_PAGE` of them. */
const MENU_CATEGORY_PAGE = 3;
const MENU_DIALOG_OPTIONS = 4;

/** The menu's first page: the state, and the three groups below it. */
const MENU_TOP: readonly string[] = [
  piiCommandDescription('status'),
  MENU_PRESETS,
  MENU_CATEGORIES,
  MENU_MORE,
];
/** The presets, each entry running its own `/pii preset …`. */
const MENU_PRESET_ENTRIES: readonly MenuEntry[] = [
  menuEntry('preset agent'),
  menuEntry('preset secrets'),
  menuEntry('preset all'),
];
/** The rest: the session's masking, the default, and the commands. */
const MENU_MORE_ENTRIES: readonly MenuEntry[] = [
  menuEntry('pause'),
  menuEntry('resume'),
  menuEntry('reset'),
  menuEntry('help'),
];
/** The three ways a category can be set. */
const MENU_MODES: readonly { readonly mode: Mode; readonly label: string }[] = [
  { mode: 'mask', label: piiCommandDescription('mask <category…>') },
  { mode: 'ask', label: piiCommandDescription('ask <category…>') },
  { mode: 'off', label: piiCommandDescription('off <category…>') },
];

/** One question of the menu: the label the person chose, or undefined when
 * they dismissed the dialog, or no one could answer it (`claude -p`). A
 * menu answer that names nothing runs nothing. */
function askMenu(
  $,
  question: string,
  options: readonly string[],
  multiSelect = false,
): Promise<string | undefined> {
  return askUser($, question, options, multiSelect).catch((err) => {
    logDebug($, `nullpii: no answer to the menu (${errorName(err)})`);
    return undefined;
  });
}

/** One line in the debug log, which never changes what the mod does: the
 * host refuses `$.ui.log` in some contexts (a nested run), and a lost
 * debug line must not turn into a failed command. */
function logDebug($, text: string): void {
  try {
    $.ui.log(text, { to: 'debug' });
  } catch {
    // Nowhere to write the line: it is dropped, and nothing else changes.
  }
}

/** The command a menu answer names: the entry that carries its text, else
 * (the dialog's own "Other") what the person typed after `/pii`, which
 * the parser reads as the command it is. An empty "Other", or one that
 * names only blanks, names no command at all. */
function menuCommand(
  entries: readonly MenuEntry[],
  answer: string,
): RunnablePiiCommand | undefined {
  const command = entries.find((c) => c.label === answer)?.command ?? parsePiiCommand(answer);
  return command.kind === 'menu' ? undefined : command;
}

/** The category list, page by page: the last page holds what is left, from
 * `MENU_CATEGORY_PAGE` to `MENU_DIALOG_OPTIONS` of them. */
function categoryPages(): readonly (readonly string[])[] {
  const pages: string[][] = [];
  for (let at = 0; at < CATEGORY_SHORT_NAMES.length; at += MENU_CATEGORY_PAGE) {
    const left = CATEGORY_SHORT_NAMES.slice(at);
    pages.push(left.length > MENU_DIALOG_OPTIONS ? left.slice(0, MENU_CATEGORY_PAGE) : [...left]);
  }
  return pages;
}

/** The categories the person picks, page by page, or undefined when they
 * dismissed a page. A page's answer is the labels they chose, joined with
 * commas (`$.ui.ask`), `MENU_CATEGORY_MORE` among them where they asked
 * for the next page. */
async function chooseCategories($, mode: Mode): Promise<readonly string[] | undefined> {
  const pages = categoryPages();
  const chosen: string[] = [];
  for (const [index, page] of pages.entries()) {
    const more = index < pages.length - 1 ? [MENU_CATEGORY_MORE] : [];
    const answer = await askMenu($, MENU_CATEGORY_QUESTION[mode], [...page, ...more], true);
    if (answer === undefined) return undefined;
    const labels = answer.split(',').map((label) => label.trim());
    chosen.push(...labels.filter((label) => label !== '' && label !== MENU_CATEGORY_MORE));
    if (!labels.includes(MENU_CATEGORY_MORE)) break;
  }
  return chosen;
}

/** The command the person picked through the category list: the mode they
 * chose, over the categories of every page they went through. Read by the
 * same parser as a typed `/pii mask|ask|off <category…>`, so an unknown
 * name is answered with the usage as it is there. */
async function chooseCategory($): Promise<RunnablePiiCommand | undefined> {
  const answer = await askMenu(
    $,
    MENU_MODE_QUESTION,
    MENU_MODES.map((m) => m.label),
  );
  const mode = MENU_MODES.find((m) => m.label === answer)?.mode;
  if (mode === undefined) return answer === undefined ? undefined : menuCommand([], answer);
  const categories = await chooseCategories($, mode);
  if (categories === undefined) return undefined;
  return menuCommand([], [mode, ...categories].join(' '));
}

/** The command one page of the menu names, or undefined when the dialog
 * was dismissed. */
async function chooseEntry(
  $,
  question: string,
  entries: readonly MenuEntry[],
): Promise<RunnablePiiCommand | undefined> {
  const answer = await askMenu(
    $,
    question,
    entries.map((c) => c.label),
  );
  return answer === undefined ? undefined : menuCommand(entries, answer);
}

/** The menu `/pii` opens with no arguments: the command the person picked,
 * or undefined when they dismissed the dialog, or no one could answer it
 * (`claude -p`). */
async function chooseFromMenu($): Promise<RunnablePiiCommand | undefined> {
  const answer = await askMenu($, MENU_QUESTION, MENU_TOP);
  if (answer === undefined) return undefined;
  if (answer === MENU_PRESETS) return chooseEntry($, MENU_PRESET_QUESTION, MENU_PRESET_ENTRIES);
  if (answer === MENU_CATEGORIES) return chooseCategory($);
  if (answer === MENU_MORE) return chooseEntry($, MENU_MORE_QUESTION, MENU_MORE_ENTRIES);
  return menuCommand([menuEntry('status')], answer);
}

/** The policy as the sidecar has it now, a change made elsewhere settled
 * first; without an answer, the last one this session saw. */
async function refreshedPolicy($): Promise<void> {
  if (policy === undefined) return;
  await reviewPolicy($).catch((err) =>
    $.ui.log(`nullpii: policy not read again: ${shownReason(failureOf(err))}`, { to: 'debug' }),
  );
}

/** What `/pii` prints where the menu cannot be answered: the status, and
 * every command, as `/pii` printed the status alone before the menu. */
async function statusAndHelp($): Promise<string> {
  await refreshedPolicy($);
  return [formatReport(counts, problem, policy, paused), formatPiiHelp()].join('\n');
}

/**
 * Run the `/pii` command `command`, typed or picked in the menu: one code
 * path, so every guard holds either way — a change that masks less is put
 * to the person, and a pause asks first and only comes from the person's
 * own run (`PERSON_ORIGINS`). `origin` is the kind the run came from.
 */
async function runPiiCommand(
  $,
  command: RunnablePiiCommand,
  origin: string,
): Promise<{ text: string }> {
  if (command.kind === 'help') return { text: formatPiiHelp() };
  if (command.kind === 'error') return { text: command.message };
  if (command.kind === 'status') {
    await refreshedPolicy($);
    return { text: formatReport(counts, problem, policy, paused) };
  }
  if (command.kind === 'pause' || command.kind === 'resume') {
    // Only the person's own run pauses or resumes masking: one the model,
    // a hook or another plugin issued in their name is refused, and the
    // band's toggle is the other way to pause.
    if (!PERSON_ORIGINS.has(origin)) return { text: PAUSE_REFUSED };
    if (command.kind === 'resume') {
      resumeMasking($);
      return { text: 'Masking is on.' };
    }
    return {
      text: (await pauseMasking($))
        ? 'Masking is paused: everything you send reaches Claude unmasked until you turn it on again (/pii resume, or the band toggle).'
        : 'Masking stays on.',
    };
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
}

export function register(on, options) {
  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'pii',
      description: 'Show what nullpii masked and its policy, or change it: /pii opens a menu',
      argumentHint: '[status|preset|mask|ask|off|reset|pause|resume|help]',
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
    // A session starts masked: a pause was the session before it's alone.
    paused = false;
    startPass = false;
    const asked = optionString(options, 'while_starting');
    whileStarting = asked === 'block' || asked === 'pass' ? asked : 'ask';
    // The band was drawn under the old state: draw it under this one.
    redraw($);
    try {
      await openSession($);
    } catch (err) {
      // No sidecar answers: start one for this session when allowed. The
      // band says so, and prompts wait (they are refused) until it answers.
      const unreachable = err instanceof Error && err.message === UNREACHABLE;
      if (unreachable && optionFlag(options, 'autostart', true) && sidecarUrl && token) {
        started = 'running';
        startSidecar($, sidecarUrl, token);
        // The band shows each phase of the start as it goes through it:
        // the packages installing, the model downloading (its bytes, once
        // the sidecar answers its status), the model loading.
        phase = 'installing';
        download = undefined;
        problem = phaseLine();
        redraw($);
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
    // Masking paused for this session, with the sidecar up: the prompt goes
    // to Claude as the person typed it. A paused session whose sidecar is
    // not up still sends nothing (fail closed, below).
    if (bypassing()) return next(e);
    // Still starting: a prompt the person typed asks them (or follows the
    // option); one the engine made waits like any other.
    if (e.isMeta !== true && (await sendUnprotectedWhileStarting($))) return next(e);
    // Not sent unprotected: it waits for the sidecar, then goes masked.
    if (e.isMeta !== true && starting()) await holdUntilReady($);
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
    const fix = reason.startsWith(STARTING_PREFIX)
      ? 'Send it again once nullpii is on.'
      : 'Start nullpii-gateway with its sidecar token set (npx, or Docker: ghcr.io/lbroth/nullpii-gateway:0.5, and start Docker itself first), turn on the mod option "Start the sidecar", or disable the nullpii mod.';
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
    if (bypassing()) return next(e);
    return next({ ...e, text: String(await masked($, e.text)) });
  }).catch(async ($, e, next) => {
    blocked($, 'prompt.attachment', next.error);
    return next.called ? next(e) : { text: null };
  });

  // The first message's context: CLAUDE.md files and the user's email. A
  // rewritten CLAUDE.md block no longer matches its instruction files, so
  // that list is left out, as the event requires.
  on('prompt.context', async ($, e, next) => {
    if (paused && problem === undefined) return next(e);
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
    // A sidecar this session started is still coming up: nothing restores
    // and nothing is sent, so the call is refused up front.
    if (phase !== undefined) return { deny: CALL_NOT_RUN };
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
    // Masking paused for this session, with the sidecar up: what came out
    // of the tool goes to Claude as it is. The placeholders already in the
    // conversation were still put back before it ran, and the call is still
    // refused above when it could change the policy file.
    if (bypassing()) {
      if (out.deny !== undefined) return { deny: String(out.deny) };
      if (out.isError === true) return { deny: String(out.text ?? '') };
      return { result: out.result, ...(out.context !== undefined && { context: out.context }) };
    }
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
    // The mod's own dialog: nothing was masked or restored for it, so it
    // blocks nothing; the ask itself reports the failure to the mod.
    if (isOwnQuestion(e)) return { deny: DIALOG_FAILED };
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
    const origin = e.origin?.kind ?? '';
    const command = parsePiiCommand(e.args ?? '');
    if (command.kind !== 'menu') return runPiiCommand($, command, origin);
    // `/pii` with no arguments: the menu, whose every choice runs the same
    // code as the typed command. Where no dialog can be answered (a
    // dismissal, or a `claude -p` run with no one to ask), the status and
    // the help are printed, which is what `/pii` printed before the menu.
    const chosen = await chooseFromMenu($);
    if (chosen === undefined) return { text: await statusAndHelp($) };
    return runPiiCommand($, chosen, origin);
  });

  // The transcript shows real values; what Claude reads keeps the
  // placeholders. If the sidecar fails, the hook is skipped and the row is
  // drawn as stored, with placeholders: nothing leaks either way.
  on('ui.render', { component: ['AssistantMessage', 'UserMessage'] }, async ($, e, next) => {
    if (!PLACEHOLDER.test(e.props.text)) return next(e);
    const text = await restoredForDisplay($, e.props.text);
    return next({ ...e, props: { ...e.props, text } });
  });

  // The band: the padlock and the pause toggle beside its line. The padlock
  // is closed and teal while masking is on, open while the sidecar comes up
  // or masking is paused, and red only while masking is paused. The toggle
  // pauses masking behind the mod's dialog, or turns it back on at once;
  // it has no hotkey, so a bare digit in an empty prompt never pauses.
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const elements = $.ui.resolve(e);
    const { Box, Text, Button } = elements;
    // `Raster` is terminal-only: a session on another surface gets the
    // toggle and the line alone.
    const Raster = 'Raster' in elements ? elements.Raster : undefined;
    const theirs = await next(e);
    const line = Text({
      color: bandColor(),
      children: [bandText()],
    });
    const toggle = Button({
      key: TOGGLE_KEY,
      label: paused ? 'off' : 'on',
      onPress: () => (paused ? resumeMasking($) : void pauseMasking($)),
    });
    const row = Box({
      flexDirection: 'row',
      gap: 1,
      children: [
        ...(Raster !== undefined
          ? [
              Raster({
                key: LOCK_KEY,
                columns: PADLOCK_COLUMNS,
                rows: PADLOCK_ROWS,
                cells: padlockCells(...padlockLook()),
              }),
            ]
          : []),
        toggle,
        line,
      ],
    });
    return Box({ flexDirection: 'column', children: theirs ? [theirs, row] : [row] });
  });
}
