// SPDX-License-Identifier: Apache-2.0
//
// Dev-mode entrypoint. `tsx watch` keeps the file open and respawns
// the process whenever a source file changes. The ONNX engine inside
// `NullPii` is lazy — it only loads the model on the first
// `sanitize()` call, so each respawn boots in ~100 ms and pays the
// model-load cost once on the first request after the reload.
//
// Run from the gateway package:
//
//   npm run dev
//
// or from the repo root:
//
//   npm run gateway:dev
//
// Env vars (see `src/config.ts` for the full list):
//   NULLPII_MODEL_DIR=/abs/path/to/local/gliner-onnx   # skip HF fetch
//   NULLPII_UPSTREAM=https://api.anthropic.com
//   NULLPII_LOG_LEVEL=debug                            # see every request
//
// Pre-cache the model once with `npx nullpii prefetch` (or by mounting
// the cache dir used by `cli/prefetch`) so the first-request latency
// is sub-second.

import { printBanner } from './banner.js';
import { loadConfig } from './config.js';
import { startServer } from './server.js';

const config = loadConfig();
const app = await startServer(config);
printBanner(config, 'dev');

async function shutdown(signal: NodeJS.Signals): Promise<void> {
  process.stdout.write(`\n[dev] ${signal} received, closing server\n`);
  await app.close();
  process.exit(0);
}

process.on('SIGINT', () => void shutdown('SIGINT'));
process.on('SIGTERM', () => void shutdown('SIGTERM'));
