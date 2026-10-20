// SPDX-License-Identifier: Apache-2.0

import Fastify, { type FastifyInstance } from 'fastify';
import { NullPii, toEngineConfig } from 'nullpii';
import type { GatewayConfig } from './config.js';
import { registerAnthropicRoute } from './routes/anthropic.js';
import { registerHealthRoute } from './routes/health.js';
import { registerOpenAiRoute } from './routes/openai.js';
import { registerSidecarRoutes } from './routes/sidecar.js';
import type { Fetch } from './upstream.js';

export interface BuildServerOptions {
  readonly config: GatewayConfig;
  /** Pre-constructed `NullPii` engine. Injected so tests can pass a
   * mock that returns deterministic spans without loading ONNX. */
  readonly np: NullPii;
  /** Pluggable `fetch`. Defaults to the global. Tests inject a mock. */
  readonly fetchImpl?: Fetch;
  /** Clock for sidecar session expiry. Defaults to `Date.now`. Tests
   * inject a manual clock. */
  readonly now?: () => number;
  /** Destination of the JSON request log. Defaults to stdout. Tests
   * inject a sink to check what is logged (counts, never values). */
  readonly logStream?: { write(line: string): void };
}

/**
 * Build the Fastify app: the health route, the Anthropic and OpenAI
 * proxy routes, and the sidecar routes when `config.sidecarToken` is
 * set. Does not listen; `startServer` does.
 */
export async function buildServer(opts: BuildServerOptions): Promise<FastifyInstance> {
  const { config, np } = opts;
  const fetchImpl: Fetch = opts.fetchImpl ?? ((input, init) => fetch(input, init));

  const app = Fastify({
    logger: {
      level: config.logLevel,
      ...(opts.logStream !== undefined && { stream: opts.logStream }),
    },
    bodyLimit: config.bodyLimitBytes,
  });

  await registerHealthRoute(app);
  await registerAnthropicRoute(app, {
    np,
    upstreamBaseUrl: config.upstreamBaseUrl,
    fetchImpl,
    logTraffic: config.logTraffic,
    restoreTools: config.restoreTools,
    appendHint: config.appendHint,
  });
  await registerOpenAiRoute(app, {
    np,
    upstreamBaseUrl: config.openaiUpstreamBaseUrl,
    fetchImpl,
    logTraffic: config.logTraffic,
    restoreTools: config.restoreTools,
    appendHint: config.appendHint,
  });
  if (config.sidecarToken !== undefined) {
    await registerSidecarRoutes(app, {
      np,
      token: config.sidecarToken,
      ttlMs: config.vaultTtlMs,
      maxSessions: config.sidecarMaxSessions,
      restoreTools: config.restoreTools,
      policy: config.policy,
      policyFile: config.policyFile,
      policyLoaded: config.policyLoaded,
      ...(opts.now !== undefined && { now: opts.now }),
    });
  }

  return app;
}

/** Create the engine from `config` (its policy, backend and model
 * directory), build the app and listen on `config.host:config.port`. Used
 * by the `nullpii-gateway` binary. */
export async function startServer(config: GatewayConfig): Promise<FastifyInstance> {
  const np = new NullPii({
    ...toEngineConfig(config.policy),
    backend: config.backend,
    ...(config.modelDir !== undefined && { modelDir: config.modelDir }),
  });
  const app = await buildServer({ config, np });
  await app.listen({ host: config.host, port: config.port });
  return app;
}
