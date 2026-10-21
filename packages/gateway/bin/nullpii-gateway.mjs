#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0

import { loadConfig, printBanner, startServer } from '../dist/index.js';

let config;
try {
  config = loadConfig();
} catch (err) {
  // A bad variable or policy file: say which, without a stack trace.
  process.stderr.write(`nullpii-gateway: ${err instanceof Error ? err.message : String(err)}\n`);
  process.exit(1);
}
const app = await startServer(config);
printBanner(config, 'prod');

const shutdown = async (signal) => {
  app.log.info({ signal }, 'gateway.shutdown');
  await app.close();
  process.exit(0);
};

process.on('SIGINT', () => void shutdown('SIGINT'));
process.on('SIGTERM', () => void shutdown('SIGTERM'));
