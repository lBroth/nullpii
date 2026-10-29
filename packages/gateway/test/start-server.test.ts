// SPDX-License-Identifier: Apache-2.0
//
// `startServer` itself, with an engine whose warmup does nothing: the
// shutdown route reaches only a gateway started with
// `NULLPII_SIDECAR_SHUTDOWN=on`, which the docs promise.

import type { FastifyInstance } from 'fastify';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { startServer } from '../src/server.js';
import { BASE_TEST_CONFIG } from './fixtures.js';

vi.mock('nullpii', async (importOriginal) => {
  const real = await importOriginal<typeof import('nullpii')>();
  /** The real engine, but no model is fetched or loaded. */
  class NoModelNullPii extends real.NullPii {
    override async warmup(): Promise<void> {}
  }
  return { ...real, NullPii: NoModelNullPii };
});

const TOKEN = 'c'.repeat(64);
const AUTH = { authorization: `Bearer ${TOKEN}` };

const apps: FastifyInstance[] = [];
afterEach(async () => {
  await Promise.all(apps.map((a) => a.close()));
  apps.length = 0;
});

async function started(sidecarShutdown: boolean): Promise<FastifyInstance> {
  const app = await startServer({ ...BASE_TEST_CONFIG, sidecarToken: TOKEN, sidecarShutdown });
  apps.push(app);
  return app;
}

describe('startServer · shutdown route', () => {
  it('is there, and reported, only when the config asks for it', async () => {
    const app = await started(true);
    const res = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    expect(res.json()).toMatchObject({ features: { shutdown: true } });
  });

  it('is not there otherwise', async () => {
    const app = await started(false);
    const status = await app.inject({ method: 'GET', url: '/v1/sidecar/status', headers: AUTH });
    expect(status.json()).toMatchObject({ features: { shutdown: false } });
    const res = await app.inject({ method: 'POST', url: '/v1/sidecar/shutdown', headers: AUTH });
    expect(res.statusCode).toBe(404);
  });
});
