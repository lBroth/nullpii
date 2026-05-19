#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0

import { loadConfig, printBanner, startServer } from '../dist/index.js';

const config = loadConfig();
const app = await startServer(config);
printBanner(config, 'prod');

const shutdown = async (signal) => {
  app.log.info({ signal }, 'gateway.shutdown');
  await app.close();
  process.exit(0);
};

process.on('SIGINT', () => void shutdown('SIGINT'));
process.on('SIGTERM', () => void shutdown('SIGTERM'));
