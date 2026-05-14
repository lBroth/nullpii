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

  it('does not expose benchmark — legacy multi-backend abstraction removed in v0.2', () => {
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

// Integration tests against a real model are exercised by the scratch
// script `test-full-stack.mjs` — see the internal plan for the
// command. The CI suite stays mock-free + ONNX-free.
