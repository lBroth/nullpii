// SPDX-License-Identifier: Apache-2.0

/**
 * Shared ANSI escape codes + TTY helpers. Three caller sites
 * (`banner.ts`, `pretty-log.ts`, `traffic-log.ts`) previously kept
 * their own copies — extracted here once they crossed the abstraction
 * threshold (CLAUDE.md: "three similar lines is better than premature
 * abstraction"; three full copies is over).
 *
 * No external dep — keeps the gateway zero-dep beyond Fastify + the
 * nullpii peer.
 */

export const ANSI = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  red: '\x1b[31m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m',
  magenta: '\x1b[35m',
  cyan: '\x1b[36m',
  brightRed: '\x1b[91m',
} as const;

// biome-ignore lint/suspicious/noControlCharactersInRegex: ESC (0x1B) is the SGR introducer for ANSI color codes — required.
const ANSI_RE = /\x1b\[[0-9;]*m/g;

/** Visible (printable) length of `s` after stripping ANSI SGR sequences.
 * Used by the banner to pad lines to fixed inner width. */
export function visibleLen(s: string): number {
  return s.replace(ANSI_RE, '').length;
}

/** True when stdout is a terminal that renders ANSI colours.
 * Logs redirected to file / CI pipelines return false. */
export function useColor(): boolean {
  return process.stdout.isTTY === true;
}
