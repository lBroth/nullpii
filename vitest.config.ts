// SPDX-License-Identifier: Apache-2.0
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// Real-ONNX E2E lives under `test/e2e/` (the core) and
// `packages/gateway/test/e2e/` (the gateway on the real engine), and is
// opt-in via `npm run test:e2e` (which sets `NULLPII_E2E=1`). The default
// `npm test` excludes those folders so CI stays ONNX-free and fast; the e2e
// script flips the env so the same vitest config picks them back up.
const E2E_ON = process.env.NULLPII_E2E === '1';
const E2E_DIRS = ['test/e2e/**', 'packages/gateway/test/e2e/**'];
const MODEL_DIR_ENV = 'NULLPII_MODEL_DIR';
// Each e2e file skips without a model dir, so an e2e run without one would
// skip every suite and still pass: refuse it instead.
if (E2E_ON && !process.env[MODEL_DIR_ENV]) {
  throw new Error(`NULLPII_E2E=1 needs ${MODEL_DIR_ENV}: the directory of the pinned model`);
}

export default defineConfig({
  // The gateway (`packages/gateway/src`) imports from `'nullpii'`, its
  // published peer, and its tests run in this suite. In this repo there is
  // no `node_modules/nullpii` (we ARE nullpii), so resolve the import to the
  // local source. Mirrors the `paths` entry in `tsconfig.json`.
  resolve: {
    alias: {
      nullpii: fileURLToPath(new URL('./src/index.ts', import.meta.url)),
    },
  },
  test: {
    globals: false,
    include: E2E_ON
      ? E2E_DIRS.map((dir) => `${dir}/*.test.ts`)
      : ['test/**/*.test.ts', 'packages/gateway/test/**/*.test.ts'],
    exclude: E2E_ON
      ? ['**/node_modules/**', '**/dist/**']
      : ['**/node_modules/**', '**/dist/**', ...E2E_DIRS],
    coverage: {
      provider: 'v8',
      // Everything that ships: the core, its CLI, and the gateway.
      include: ['src/**/*.ts', 'packages/gateway/src/**/*.ts'],
      exclude: [
        '**/*.test.ts',
        '**/*.d.ts',
        // Pure-type modules — erased at compile time, not imported at runtime
        'src/types/spans.ts',
        'src/types/vault.ts',
        'src/types/results.ts',
        'src/types/config.ts',
        'src/types/backend.ts',
        'packages/gateway/src/types.ts',
        'packages/gateway/src/openai-types.ts',
        // Re-export barrels — verified by surface tests, not coverage
        'src/index.ts',
        'src/types/index.ts',
        'packages/gateway/src/index.ts',
        // Process entry points (signal handling, listen): the gateway's
        // dev runner, like the bin scripts, is wiring over tested modules
        'packages/gateway/src/dev.ts',
      ],
      reporter: ['text', 'html', 'lcov'],
      thresholds: {
        lines: 85,
        branches: 80,
        functions: 85,
        statements: 85,
      },
    },
  },
});
