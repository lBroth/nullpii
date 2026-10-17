// SPDX-License-Identifier: Apache-2.0
//
// Pure helpers for the nullpii mod: which tool arguments get real values
// back, and how the counts are shown. No mods API calls live here, so
// `claude plugin validate` reads every `$` call from register.ts.

/**
 * Arguments that get their real values back before a tool runs, per tool.
 * Only tools that act on this machine are listed. A tool that sends its
 * input elsewhere (WebFetch, WebSearch, MCP tools) keeps the placeholders,
 * so a masked value never leaves the machine through a tool call.
 */
export const RESTORE_FIELDS: Readonly<Record<string, readonly string[]>> = {
  Bash: ['command'],
  Read: ['file_path'],
  Edit: ['file_path', 'old_string', 'new_string'],
  Write: ['file_path', 'content'],
  NotebookEdit: ['notebook_path', 'new_source'],
  Grep: ['pattern', 'path', 'glob'],
  Glob: ['pattern', 'path'],
};

const LABEL_PREFIX = 'private_';

export interface Counts {
  masked: number;
  restored: number;
  byLabel: Record<string, number>;
}

export function emptyCounts(): Counts {
  return { masked: 0, restored: 0, byLabel: {} };
}

/** Add one sidecar sanitize response to the session's counts. */
export function addMasked(
  counts: Counts,
  captured: number,
  byLabel: Readonly<Record<string, number>>,
): void {
  counts.masked += captured;
  for (const [label, n] of Object.entries(byLabel)) {
    counts.byLabel[label] = (counts.byLabel[label] ?? 0) + n;
  }
}

function shortLabel(label: string): string {
  return label.startsWith(LABEL_PREFIX) ? label.slice(LABEL_PREFIX.length) : label;
}

/** Labels by count, largest first: `person 5 · email 3`. */
export function formatLabels(byLabel: Readonly<Record<string, number>>, limit: number): string {
  return Object.entries(byLabel)
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, limit)
    .map(([label, n]) => `${shortLabel(label)} ${n}`)
    .join(' · ');
}

/** The one line shown above the prompt. */
export function formatBand(counts: Counts, problem: string | undefined): string {
  if (problem !== undefined) return `nullpii · blocking: ${problem}`;
  if (counts.masked === 0) return 'nullpii · on · nothing masked yet';
  const labels = formatLabels(counts.byLabel, 4);
  return `nullpii · ${counts.masked} masked (${labels}) · ${counts.restored} restored to local tools`;
}

/** The `/pii` command's reply. */
export function formatReport(counts: Counts, problem: string | undefined): string {
  const lines = [
    problem === undefined ? 'Status: on' : `Status: blocking (${problem})`,
    `Masked before Claude read them: ${counts.masked}`,
    `Real values put back into local tool calls: ${counts.restored}`,
  ];
  const labels = formatLabels(counts.byLabel, Number.POSITIVE_INFINITY);
  if (labels !== '') lines.push(`By type: ${labels}`);
  return lines.join('\n');
}

/** Tools whose restored arguments a shell interprets. */
export const SHELL_TOOLS: ReadonlySet<string> = new Set(['Bash']);

export type QuoteContext = 'none' | 'single' | 'double' | 'heredoc';

/** What a value may contain to be put back into a shell command as
 * written, by the quoting around its placeholder. A masked value comes
 * from data Claude could not read, so it must not add commands, expand
 * variables or end its quotes. */
const SHELL_SAFE: Readonly<Record<QuoteContext, RegExp>> = {
  none: /^[A-Za-z0-9@%+=:,./_-]+$/,
  single: /^[^'\n]*$/,
  double: /^[^"$`\\!\n]*$/,
  // A quoted-delimiter heredoc body is literal; only a newline could end
  // it early, with the delimiter on a line of its own.
  heredoc: /^[^\n]*$/,
};

/** Programs that run part of their arguments as code, so a value that is
 * safe for the outer shell can still inject into them. */
const NESTED_INTERPRETER =
  /\b(?:bash|sh|zsh|dash|ksh|fish)\s+(?:-\w+\s+)*-\w*c\b|\beval\b|\bssh\b|\bsu\s+-c\b|\b(?:python3?|node|perl|ruby|php|deno|bun)\s+(?:-\w+\s+)*-\w*[ce]\b/;

export function shellSafe(value: string, context: QuoteContext): boolean {
  return SHELL_SAFE[context].test(value);
}

/** The context that decides what a restored value may contain at
 * `index`: the strictest rule when the command hands code to another
 * interpreter, a heredoc body, or the shell quoting there. */
export function shellContextAt(command: string, index: number): QuoteContext {
  if (NESTED_INTERPRETER.test(command)) return 'none';
  return heredocContextAt(command, index) ?? quoteContextAt(command, index);
}

const HEREDOC_START = /<<-?\s*(['"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n/g;

/** `heredoc` inside the body of a heredoc with a quoted delimiter
 * (literal), `double` inside an unquoted one (it expands `$` and
 * backticks), `undefined` outside any heredoc body. */
export function heredocContextAt(command: string, index: number): QuoteContext | undefined {
  for (const m of command.matchAll(HEREDOC_START)) {
    const bodyStart = (m.index ?? 0) + m[0].length;
    if (index < bodyStart) continue;
    const delimiter = m[2] as string;
    const end = new RegExp(`^[\\t ]*${delimiter}[\\t ]*$`, 'm').exec(command.slice(bodyStart));
    const bodyEnd = end === null ? command.length : bodyStart + end.index;
    if (index < bodyEnd) return m[1] === '' ? 'double' : 'heredoc';
  }
  return undefined;
}

type LexState = 'none' | 'single' | 'double' | 'subst' | 'paren' | 'backtick';

/** The quoting in force at `index` of a shell command: a small stack
 * lexer for single and double quotes, backslash escapes, and command
 * substitution. Inside `$(…)` or backticks the shell runs the text as a
 * command, so it counts as unquoted even within double quotes. */
export function quoteContextAt(command: string, index: number): QuoteContext {
  const stack: LexState[] = ['none'];
  for (let i = 0; i < index; i++) {
    const top = stack[stack.length - 1] as LexState;
    const ch = command[i];
    if (top !== 'single' && ch === '\\') {
      i++;
      continue;
    }
    if (top === 'single') {
      if (ch === "'") stack.pop();
      continue;
    }
    if (ch === '$' && command[i + 1] === '(') {
      stack.push('subst');
      i++;
    } else if (ch === '`') {
      if (top === 'backtick') stack.pop();
      else stack.push('backtick');
    } else if (top === 'double') {
      if (ch === '"') stack.pop();
    } else if (ch === "'") {
      stack.push('single');
    } else if (ch === '"') {
      stack.push('double');
    } else if (ch === '(' && (top === 'subst' || top === 'paren')) {
      stack.push('paren');
    } else if (ch === ')' && (top === 'subst' || top === 'paren')) {
      stack.pop();
    }
  }
  const top = stack[stack.length - 1] as LexState;
  return top === 'single' || top === 'double' ? top : 'none';
}
