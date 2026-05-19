// SPDX-License-Identifier: Apache-2.0

import Fastify, { type FastifyInstance } from 'fastify';
import { NullPii } from 'nullpii';
import type { GatewayConfig } from './config.js';
import { registerAnthropicRoute } from './routes/anthropic.js';
import { registerHealthRoute } from './routes/health.js';
import type { Fetch } from './upstream.js';

export interface BuildServerOptions {
  readonly config: GatewayConfig;
  /** Pre-constructed `NullPii` engine. Injected so tests can pass a
   * mock that returns deterministic spans without loading ONNX. */
  readonly np: NullPii;
  /** Pluggable `fetch`. Defaults to the global. Tests inject a mock. */
  readonly fetchImpl?: Fetch;
}

export async function buildServer(opts: BuildServerOptions): Promise<FastifyInstance> {
  const { config, np } = opts;
  const fetchImpl: Fetch = opts.fetchImpl ?? ((input, init) => fetch(input, init));

  const app = Fastify({
    logger: { level: config.logLevel },
    bodyLimit: config.bodyLimitBytes,
  });

  await registerHealthRoute(app);
  await registerAnthropicRoute(app, {
    np,
    upstreamBaseUrl: config.upstreamBaseUrl,
    fetchImpl,
    logTraffic: config.logTraffic,
  });

  return app;
}

/** Convenience: build + initialise + start. Used by the CLI. */
export async function startServer(config: GatewayConfig): Promise<FastifyInstance> {
  const np = new NullPii({
    backend: config.backend,
    ...(config.modelDir !== undefined && { modelDir: config.modelDir }),
  });
  const app = await buildServer({ config, np });
  await app.listen({ host: config.host, port: config.port });
  return app;
}
