// SPDX-License-Identifier: Apache-2.0

import { PLACEHOLDER_REGEX } from 'nullpii';

/**
 * Tools whose input a shell runs, as each agent names them: Claude Code's
 * `Bash` and `PowerShell`, Anthropic's `bash`, and the `shell`,
 * `exec_command`, `shell_command` and `write_stdin` tools of OpenAI-style
 * coding agents.
 *
 * None of them gets a real value back, in any field. A masked value comes
 * from data the model could not read, so put back into a command it could
 * change what the command does. An agent writes real data with its file
 * tools (`Write`, `Edit`), which get values; a command keeps its
 * placeholders.
 */
const SHELL_TOOLS: ReadonlySet<string> = new Set([
  'Bash',
  'bash',
  'shell',
  'PowerShell',
  'exec_command',
  'shell_command',
  'write_stdin',
]);

/** True when `name` is a tool whose input a shell runs (`SHELL_TOOLS`). */
export function isShellTool(name: unknown): boolean {
  return typeof name === 'string' && SHELL_TOOLS.has(name);
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
