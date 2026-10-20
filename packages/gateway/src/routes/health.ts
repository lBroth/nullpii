// SPDX-License-Identifier: Apache-2.0

import type { FastifyInstance } from 'fastify';

/** Register `GET /health`, a liveness probe that touches no engine. */
export async function registerHealthRoute(app: FastifyInstance): Promise<void> {
  app.get('/health', async () => ({ status: 'ok' }));
}
