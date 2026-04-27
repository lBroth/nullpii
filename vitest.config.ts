// SPDX-License-Identifier: Apache-2.0
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    globals: false,
    include: ['test/**/*.test.ts'],
    exclude: ['**/node_modules/**', '**/dist/**'],
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
        // Network I/O — covered by gated end-to-end test (NULLPII_E2E=1)
        'src/hf-hub.ts',
        // Hardware-gated backends — covered by gated runners (Linux+GPU)
        'src/backend/cuda-backend.ts',
        'src/backend/rocm-backend.ts',
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
