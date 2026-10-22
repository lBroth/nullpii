#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0

import { createRequire } from 'node:module';

const USAGE = `Usage: nullpii-gateway [--help | --version]

Starts the nullpii gateway on NULLPII_HOST:NULLPII_PORT (127.0.0.1:8787 by
default). Every setting is an environment variable or the shared policy
file; see https://github.com/lBroth/nullpii/tree/main/packages/gateway
`;

const VERSION_FLAGS = new Set(['--version', '-v']);
const HELP_FLAGS = new Set(['--help', '-h']);

// Answer before any configuration is read: an option never starts a server.
const args = process.argv.slice(2);
if (args.length > 0) {
  const [flag, extra] = args;
  if (extra === undefined && VERSION_FLAGS.has(flag)) {
    const { version } = createRequire(import.meta.url)('../package.json');
    process.stdout.write(`${version}\n`);
    process.exit(0);
  }
  if (extra === undefined && HELP_FLAGS.has(flag)) {
    process.stdout.write(USAGE);
    process.exit(0);
  }
  // One option at most: anything else is an error, never a server start.
  const unexpected = VERSION_FLAGS.has(flag) || HELP_FLAGS.has(flag) ? extra : flag;
  process.stderr.write(
    `nullpii-gateway: unexpected argument ${JSON.stringify(unexpected)}\n${USAGE}`,
  );
  process.exit(2);
}

// Loaded only once the arguments are known to start a server.
const { loadConfig, printBanner, startServer } = await import('../dist/index.js');

let config;
try {
  config = loadConfig();
} catch (err) {
  // A bad variable or policy file: say which, without a stack trace.
  process.stderr.write(`nullpii-gateway: ${err instanceof Error ? err.message : String(err)}\n`);
  process.exit(1);
}
let app;
try {
  app = await startServer(config);
} catch (err) {
  // A port already in use, or an address that cannot be bound: one line.
  process.stderr.write(`nullpii-gateway: ${err instanceof Error ? err.message : String(err)}\n`);
  process.exit(1);
}
printBanner(config, 'prod');

const shutdown = async (signal) => {
  app.log.info({ signal }, 'gateway.shutdown');
  await app.close();
  process.exit(0);
};

process.on('SIGINT', () => void shutdown('SIGINT'));
process.on('SIGTERM', () => void shutdown('SIGTERM'));
