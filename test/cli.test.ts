import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildProgram } from '../src/cli/index.js';

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CLI: buildProgram', () => {
  it('exposes scan, sanitize, models, prefetch, doctor commands', () => {
    const program = buildProgram();
    const names = program.commands.map((c) => c.name());
    expect(names).toEqual(
      expect.arrayContaining(['scan', 'sanitize', 'models', 'prefetch', 'doctor']),
    );
  });

  it('does not expose restore — vault is process-local, cross-process restore was always broken', () => {
    const program = buildProgram();
    const names = program.commands.map((c) => c.name());
    expect(names).not.toContain('restore');
  });

  it('does not expose a benchmark subcommand', () => {
    const program = buildProgram();
    const names = program.commands.map((c) => c.name());
    expect(names).not.toContain('benchmark');
  });

  it('has a version flag', () => {
    const program = buildProgram();
    expect(program.version()).toMatch(/\d+\.\d+\.\d+/);
  });

  it('--help does not throw on the top-level program', () => {
    const program = buildProgram();
    program.exitOverride();
    expect(() => {
      try {
        program.parse(['node', 'nullpii', '--help']);
      } catch (e) {
        // commander throws CommanderError on --help — that's expected.
        if (e instanceof Error && 'exitCode' in e && (e as { exitCode?: number }).exitCode === 0) {
          return;
        }
        throw e;
      }
    }).not.toThrow();
  });
});

// Real-ONNX integration tests live in `test/e2e/` and run via
// `npm run test:e2e` (gated on `NULLPII_E2E=1` + `NULLPII_MODEL_DIR`).
// The default `npm test` suite stays mock-free of ONNX.
