// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import { ANSI, visibleLen } from './ansi.js';
import type { GatewayConfig } from './config.js';

function pkgVersion(): string {
  // Resolve relative to the compiled module URL — robust under pnpm
  // hoisting / nested `node_modules/.pnpm/...` layouts where the
  // CommonJS `require.resolve` path heuristic from `createRequire`
  // would miss the workspace `package.json`.
  const url = new URL('../package.json', import.meta.url);
  const pkg = JSON.parse(readFileSync(url, 'utf8')) as { version: string };
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
