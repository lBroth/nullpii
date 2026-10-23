// SPDX-License-Identifier: Apache-2.0

import { PLACEHOLDER_REGEX, type RestoreCapable, type RestoreResult } from 'nullpii';

/**
 * Shell-aware restore for the tool calls whose input a shell runs.
 *
 * A masked value comes from data the model could not read (a file the
 * agent opened, a tool result). Put back verbatim into a shell command, it
 * could change what the command does, and no reading of shell syntax is
 * both complete and simple. So a value comes back into a shell command in
 * one place only: the body of a quoted heredoc that one of a few fixed
 * command forms writes out as data (`parseDataHeredoc`):
 *
 *     cat > notes.md <<'EOF'       a document (`DOCUMENT`), also `>>`
 *     cat <<'EOF'                  standard output
 *     git commit -F - <<'EOF'      a commit message
 *
 * on the first line, optionally after `git add …` or `mkdir -p …` joined by
 * `&&`; the body follows, and the closing line is the last line. A quoted
 * delimiter makes the body literal: the shell expands nothing in it. No
 * body line may start with the delimiter (ksh93 ends the body at such a
 * line when a closing bracket follows). A value comes back there when it
 * holds no line break or other control character but tab, no `<<` and not
 * the delimiter. Any other command, and a placeholder anywhere but in
 * that body, keeps every placeholder.
 *
 * A value restored into a file (here, or by `Write`) can be read by a
 * later command: each call is judged on its own.
 */

/** A shell tool, as its input is restored: the field the shell interprets
 * (`undefined` when no field may get a value). */
export interface ShellTool {
  readonly commandField: string | undefined;
}

/** Tools whose input a shell runs, as each agent names them: Claude Code's
 * `Bash` and Anthropic's `bash` (a POSIX shell), the `shell` tool of
 * OpenAI-style agents such as Codex (an argv array), and the tools that
 * get no value at all: Codex's `exec_command` and `shell_command`, which
 * run in a shell Codex picks (PowerShell or `cmd.exe` on Windows), its
 * `write_stdin`, which writes to a running process, and Claude Code's
 * `PowerShell`. */
const SHELL_TOOL_SPECS: ReadonlyMap<string, ShellTool> = new Map([
  ['Bash', { commandField: 'command' }],
  ['bash', { commandField: 'command' }],
  ['shell', { commandField: 'command' }],
  ['exec_command', { commandField: undefined }],
  ['shell_command', { commandField: undefined }],
  ['write_stdin', { commandField: undefined }],
  ['PowerShell', { commandField: undefined }],
]);

const WINDOWS = 'win32';
const NO_VALUE: ShellTool = { commandField: undefined };

/** The shell tool `name` is, or `undefined` for any other tool. On Windows
 * no shell tool gets a value: Git Bash, MSYS2 and Cygwin read paths, and
 * Windows shells read text, in ways this rule does not model. */
export function shellToolOf(
  name: unknown,
  platform: string = process.platform,
): ShellTool | undefined {
  const spec = typeof name === 'string' ? SHELL_TOOL_SPECS.get(name) : undefined;
  if (spec === undefined) return undefined;
  return platform === WINDOWS ? NO_VALUE : spec;
}

/** Input fields that set the directory a shell tool's command runs in: a
 * relative file the command writes lands there. */
export const WORKDIR_FIELDS: ReadonlySet<string> = new Set(['workdir', 'cwd', 'working_directory']);

/** The other input fields of a shell tool with a command field that get
 * values back: text shown to the user. Any other field (`workdir`, `env`,
 * `timeout`, or one nullpii does not know) keeps its placeholders. */
export const SHELL_TEXT_FIELDS: ReadonlySet<string> = new Set(['description', 'justification']);

/** How a shell command is judged beyond its own text. */
export interface ShellOptions {
  /** The call sets the working directory itself (`WORKDIR_FIELDS`). */
  readonly movedDir?: boolean;
  /** The call sets the command's environment itself (an `env` field), which
   * chooses what it runs or reads: nothing comes back. */
  readonly keepAll?: boolean;
}

/** Longest command read: a longer one keeps every placeholder. */
export const MAX_COMMAND_CHARS = 256 * 1024;

/** A file name or path on the command line: letters, digits and `_./@+-`,
 * not starting with `-`. No quote, space, `$`, glob or other character a
 * shell gives a meaning to. */
const PATH = String.raw`(?!-)[\w./@+-]+`;
/** `git add` with its paths, or `mkdir -p` with its directories. */
const PREFIX = String.raw`(?:git add(?: +(?:-A|--all|-u|--update|${PATH}))+|mkdir(?: +-p)?(?: +${PATH})+)`;
/** A quoted heredoc delimiter, its quote in group `q<n>` and its name in
 * group `d<n>` (one pair per form below). */
function delimiter(n: number): string {
  return String.raw`<< ?(?<q${n}>['"])(?<d${n}>\w+)\k<q${n}>`;
}
/** Options of `git commit` that run, write or read nothing else. */
const COMMIT_OPTION = String.raw`(?:-a|--all|-q|--quiet|-s|--signoff|--amend|-n|--no-verify)`;
/** The first line of a command whose heredoc body is data. Group `t1` or
 * `t2` is the file `cat` writes, when it writes one. */
const DATA_HEAD = new RegExp(
  String.raw`^(?:${PREFIX} +&& +)*(?:` +
    String.raw`cat +>>? ?(?<t1>${PATH}) +${delimiter(1)}` +
    String.raw`|cat +${delimiter(2)}(?: +>>? ?(?<t2>${PATH}))?` +
    String.raw`|git commit(?: +${COMMIT_OPTION})* +(?:-F -|-F-|--file=-|--file -) +${delimiter(3)}` +
    String.raw`) *$`,
);
/** A document: a text extension no shell, build tool or test runner reads
 * as code or input by name (not `.txt`: pip, CMake and pytest read some),
 * with no hidden directory or file on its path (`./` and `../` aside).
 * Case is ignored, as on the default macOS and Windows file systems. */
const DOCUMENT = /^(?!.*(?:^|\/)\.(?!\.?\/))[\w./+-]*\.(?:md|markdown|csv|tsv|log|rst)$/i;
/** Directories whose files something runs or reads as configuration. */
const RUN_LATER_DIR = /(?:^|\/)(?:s?bin|etc|LaunchAgents|systemd)\//i;
/** A character a body value may not hold: a line break (it could end the
 * body) or any other control character but tab. */
// biome-ignore lint/suspicious/noControlCharactersInRegex: refusing them is the point.
const UNSAFE_IN_BODY = /[\u0000-\u0008\u000a-\u001f\u007f-\u009f\u2028\u2029]/;
/** Text a body value may not hold: a heredoc operator, which an agent's
 * own reading of the command (Claude Code picks how to quote a command it
 * runs by looking for one) could take for a second heredoc. */
const HEREDOC_OPERATOR = '<<';

/** A data heredoc's body (`start`, `end`) and its delimiter. */
interface DataBody {
  readonly start: number;
  readonly end: number;
  readonly delimiter: string;
}

/** Where the data body of `command` lies, or `undefined` when `command` is
 * not one of the fixed data forms (`DATA_HEAD`) with its body after the
 * first line and its closing line last, writing standard output or a
 * document (an absolute one when `movedDir`). */
function parseDataHeredoc(command: string, movedDir: boolean): DataBody | undefined {
  const firstBreak = command.indexOf('\n');
  if (firstBreak === -1) return undefined;
  const head = DATA_HEAD.exec(command.slice(0, firstBreak))?.groups;
  if (head === undefined) return undefined;
  const target = head.t1 ?? head.t2;
  if (target !== undefined && !writableDocument(target, movedDir)) return undefined;
  const closingLine = head.d1 ?? head.d2 ?? head.d3;
  if (closingLine === undefined) return undefined;
  const start = firstBreak + 1;
  // The closing line is the first line that starts with the delimiter
  // (ksh93 also ends the body at a line that starts with it and goes on
  // with a closing bracket); it must be the delimiter alone and the last
  // line, so nothing runs after the body.
  const rest = command.endsWith('\n') ? command.slice(start, -1) : command.slice(start);
  const lines = rest.split('\n');
  const closing = lines.findIndex((line) => line.startsWith(closingLine));
  if (closing !== lines.length - 1 || lines[closing] !== closingLine) return undefined;
  const end = start + lines.slice(0, closing).reduce((n, line) => n + line.length + 1, 0);
  return { start, end, delimiter: closingLine };
}

/** True when `target` is a document `cat` may write: not in a directory
 * whose files run later, and absolute when the call moved the working
 * directory (a relative one would land there). */
function writableDocument(target: string, movedDir: boolean): boolean {
  if (!DOCUMENT.test(target) || RUN_LATER_DIR.test(target)) return false;
  return !movedDir || target.startsWith('/');
}

/** A shell command with its safe placeholders restored. */
export interface ShellRestore {
  readonly command: string;
  /** One result per placeholder restored, or found unknown or foreign
   * (left literal, and counted as such by the caller). */
  readonly results: readonly RestoreResult[];
  /** The placeholders left literal, once per occurrence. Placeholders,
   * never values. */
  readonly keptMasked: readonly string[];
}

/**
 * Restore the placeholders of a shell `command`: only in the body of a
 * data heredoc (`parseDataHeredoc`), only when every placeholder of the
 * command stands there, and only values with no line break or other
 * control character but tab, no `<<` and not the delimiter. The command
 * with the values put back must still parse the same way; otherwise every
 * placeholder stays literal.
 *
 * @param np - the engine whose vault holds `sessionId`.
 */
export function restoreShellCommand(
  np: RestoreCapable,
  command: string,
  sessionId: string,
  options: ShellOptions = {},
): ShellRestore {
  const movedDir = options.movedDir === true;
  const tooLong = command.length > MAX_COMMAND_CHARS;
  const body =
    tooLong || options.keepAll === true ? undefined : parseDataHeredoc(command, movedDir);
  const inBody = (at: number): boolean => body !== undefined && at >= body.start && at < body.end;
  const starts = [...command.matchAll(placeholderPattern())].map((m) => m.index);
  if (body === undefined || !starts.every(inBody)) {
    return restoreEach(np, command, sessionId, () => false);
  }
  const safe = (value: string): boolean =>
    !UNSAFE_IN_BODY.test(value) &&
    !value.includes(HEREDOC_OPERATOR) &&
    !value.includes(body.delimiter);
  const restored = restoreEach(np, command, sessionId, safe);
  if (parseDataHeredoc(restored.command, movedDir) !== undefined) return restored;
  return restoreEach(np, command, sessionId, () => false);
}

/** A shell `command` given as an argv array, with its safe placeholders
 * restored. */
export interface ShellArgvRestore {
  readonly argv: readonly string[];
  readonly results: readonly RestoreResult[];
  readonly keptMasked: readonly string[];
}

/** POSIX shells whose `-c` script is read as a string command. */
const POSIX_SHELLS: ReadonlySet<string> = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'mksh']);
/** The standard directories a shell named by path may sit in. */
const SHELL_DIR = /^(?:\/usr)?\/bin\//;
/** The options before a `-c` script that the rule reads. */
const SCRIPT_OPTIONS: ReadonlyArray<readonly string[]> = [['-c'], ['-lc'], ['-l', '-c']];

/**
 * Restore the placeholders of a `command` given as an argv array, as
 * Codex's `shell` tool sends it (`["bash", "-lc", "…"]`): only in the last
 * word, the script, when the array is a POSIX shell named as written (or in
 * `/bin`, `/usr/bin`) followed by `-c`, `-lc` or `-l -c`; the script is
 * judged as a string command. No other array gets a value.
 *
 * @param np - the engine whose vault holds `sessionId`.
 */
export function restoreShellArgv(
  np: RestoreCapable,
  argv: readonly string[],
  sessionId: string,
  options: ShellOptions = {},
): ShellArgvRestore {
  const script = isShellScript(argv) ? argv.length - 1 : -1;
  const results: RestoreResult[] = [];
  const keptMasked: string[] = [];
  const out = argv.map((word, position) => {
    const r =
      position === script
        ? restoreShellCommand(np, word, sessionId, options)
        : restoreEach(np, word, sessionId, () => false);
    results.push(...r.results);
    keptMasked.push(...r.keptMasked);
    return r.command;
  });
  return { argv: out, results, keptMasked };
}

/** True when `argv` is a POSIX shell running its last word as a script. */
function isShellScript(argv: readonly string[]): boolean {
  const shell = argv[0];
  if (shell === undefined || !POSIX_SHELLS.has(shell.replace(SHELL_DIR, ''))) return false;
  const options = argv.slice(1, -1);
  return SCRIPT_OPTIONS.some(
    (form) => form.length === options.length && form.every((o, k) => o === options[k]),
  );
}

/** Restore each placeholder of `text` whose real value `safe` accepts;
 * leave the others literal. An unknown placeholder stays literal and is
 * counted in its result. */
function restoreEach(
  np: RestoreCapable,
  text: string,
  sessionId: string,
  safe: (value: string) => boolean,
): ShellRestore {
  const results: RestoreResult[] = [];
  const keptMasked: string[] = [];
  let out = '';
  let last = 0;
  for (const match of text.matchAll(placeholderPattern())) {
    const start = match.index;
    const placeholder = match[0];
    const r = np.restore(placeholder, sessionId);
    const ok = r.replacements === 0 || safe(r.restored);
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
