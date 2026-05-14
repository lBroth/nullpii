// SPDX-License-Identifier: Apache-2.0
import { fileURLToPath } from 'node:url';
import { defineConfig } from 'vitest/config';

// Real-ONNX E2E lives under `test/e2e/` and is opt-in via `npm run test:e2e`
// (which sets `NULLPII_E2E=1`). The default `npm test` excludes that folder
// so CI stays ONNX-free and fast; the e2e script flips the env so the same
// vitest config picks the folder back up.
const E2E_ON = process.env.NULLPII_E2E === '1';

export default defineConfig({
  // The subpackages under `packages/recognizers-*/` import from `'nullpii'`
  // to honour the published consumer surface. In this repo there is no
  // `node_modules/nullpii` (we ARE nullpii), so resolve the import to the
  // local source. Mirrors the `paths` entry in `tsconfig.json`.
  resolve: {
    alias: {
      nullpii: fileURLToPath(new URL('./src/index.ts', import.meta.url)),
    },
  },
  test: {
    globals: false,
    include: E2E_ON ? ['test/e2e/**/*.test.ts'] : ['test/**/*.test.ts'],
    exclude: E2E_ON
      ? ['**/node_modules/**', '**/dist/**']
      : ['**/node_modules/**', '**/dist/**', 'test/e2e/**'],
    coverage: {
      provider: 'v8',
      include: ['src/**/*.ts'],
      exclude: [
        '**/*.test.ts',
        '**/*.d.ts',
        // Pure-type modules — erased at compile time, not imported at runtime
        'src/types/spans.ts',
        'src/types/vault.ts',
        'src/types/results.ts',
        'src/types/config.ts',
        'src/types/backend.ts',
        // Re-export barrels — verified by surface tests, not coverage
        'src/index.ts',
        'src/types/index.ts',
        // Network I/O — exercised by integration runs, not unit coverage
        'src/hf-hub.ts',
        // Hardware-gated backends — covered by gated runners (Linux+GPU)
        'src/backend/cuda-backend.ts',
        // CLI — thin layer over public API; exercised by CLI smoke tests
        'src/cli/**',
        'bin/**',
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
