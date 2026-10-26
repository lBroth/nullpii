// SPDX-License-Identifier: Apache-2.0

import { DEFAULT_RESTORE_TOOLS } from 'nullpii';
import type { GatewayConfig } from '../src/config.js';

/** The default local tools plus the made-up tools these tests call. */
export const TEST_RESTORE_TOOLS: ReadonlySet<string> = new Set([
  ...DEFAULT_RESTORE_TOOLS,
  'send',
  'send_email',
  'note',
  'weather',
  'lookup',
  'lookup_user',
  'write_file',
]);

/** A gateway config for in-process tests; spread and override per suite. */
export const BASE_TEST_CONFIG: GatewayConfig = {
  host: '127.0.0.1',
  port: 0,
  upstreamBaseUrl: 'https://upstream.test',
  openaiUpstreamBaseUrl: 'https://openai.test',
  vaultTtlMs: 60_000,
  backend: 'cpu',
  logLevel: 'fatal',
  bodyLimitBytes: 10 * 1024 * 1024,
  logTraffic: false,
  sidecarMaxSessions: 64,
  policy: {},
  policyFile: '/nonexistent/nullpii/config.json',
  policyLoaded: false,
  restoreTools: TEST_RESTORE_TOOLS,
  appendHint: true,
};
