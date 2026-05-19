// SPDX-License-Identifier: Apache-2.0

import { createRequire } from 'node:module';
import type { GatewayConfig } from './config.js';

const ANSI = {
  reset: '\x1b[0m',
  bold: '\x1b[1m',
  dim: '\x1b[2m',
  cyan: '\x1b[36m',
  green: '\x1b[32m',
  yellow: '\x1b[33m',
};

// biome-ignore lint/suspicious/noControlCharactersInRegex: ESC (0x1B) is the SGR introducer for ANSI color codes — required.
const ANSI_RE = /\[[0-9;]*m/g;

function visibleLen(s: string): number {
  return s.replace(ANSI_RE, '').length;
}

function pkgVersion(): string {
  const require = createRequire(import.meta.url);
  const pkg = require('../package.json') as { version: string };
  return pkg.version;
}

/**
 * Boxed Claude-Code-style startup banner. Writes to stdout. ANSI
 * sequences only — no colour dep. Caller fires once after
 * `app.listen`.
 */
export function printBanner(config: GatewayConfig, mode: 'dev' | 'prod' = 'prod'): void {
  const baseUrl = `http://${config.host}:${config.port}`;
  const version = pkgVersion();
  const modeTag = mode === 'dev' ? ` ${ANSI.yellow}[dev]${ANSI.reset}` : '';
  const rows = [
    `${ANSI.bold}${ANSI.cyan}✻ nullpii gateway${ANSI.reset}  ${ANSI.dim}v${version}${ANSI.reset}${modeTag}`,
    '',
    `${ANSI.green}✓${ANSI.reset} listening  ${ANSI.bold}${baseUrl}${ANSI.reset}`,
    `${ANSI.green}✓${ANSI.reset} upstream   ${config.upstreamBaseUrl}`,
    `${ANSI.green}✓${ANSI.reset} backend    ${config.backend}`,
    ...(config.logTraffic
      ? [
          `${ANSI.yellow}●${ANSI.reset} traffic    ${ANSI.yellow}wire dump on (placeholders only)${ANSI.reset}`,
        ]
      : []),
    '',
    `${ANSI.dim}point your client:${ANSI.reset}`,
    `  ${ANSI.bold}export ANTHROPIC_BASE_URL=${baseUrl}${ANSI.reset}`,
  ];
  const inner = 64;
  const top = `${ANSI.cyan}╭${'─'.repeat(inner)}╮${ANSI.reset}`;
  const bot = `${ANSI.cyan}╰${'─'.repeat(inner)}╯${ANSI.reset}`;
  const body = rows
    .map((r) => {
      const pad = ' '.repeat(Math.max(0, inner - 2 - visibleLen(r)));
      return `${ANSI.cyan}│${ANSI.reset} ${r}${pad} ${ANSI.cyan}│${ANSI.reset}`;
    })
    .join('\n');
  process.stdout.write(`\n${top}\n${body}\n${bot}\n\n`);
}
