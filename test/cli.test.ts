import { afterEach, describe, expect, it, vi } from 'vitest';
import { buildProgram } from '../src/cli/index.js';
import { HAS_TEST_ARTIFACTS, TEST_MODEL_DIR } from './_env.js';

const ARTIFACT_MODEL_DIR = TEST_MODEL_DIR;
const itIfArtifacts = HAS_TEST_ARTIFACTS ? it : it.skip;

afterEach(() => {
  vi.restoreAllMocks();
});

describe('CLI: buildProgram', () => {
  it('exposes scan, sanitize, restore, models, benchmark commands', () => {
    const program = buildProgram();
    const names = program.commands.map((c) => c.name());
    expect(names).toEqual(
      expect.arrayContaining(['scan', 'sanitize', 'restore', 'models', 'benchmark']),
    );
  });

  it('has a version flag', () => {
    const program = buildProgram();
    expect(program.version()).toMatch(/\d+\.\d+\.\d+/);
  });
});

function captureStdout<T>(fn: () => Promise<T>): Promise<{ result: T; output: string }> {
  const chunks: string[] = [];
  const original = process.stdout.write.bind(process.stdout);
  process.stdout.write = ((data: string | Uint8Array) => {
    chunks.push(typeof data === 'string' ? data : Buffer.from(data).toString('utf-8'));
    return true;
  }) as typeof process.stdout.write;
  return fn()
    .then((result) => ({ result, output: chunks.join('') }))
    .finally(() => {
      process.stdout.write = original;
    });
}

describe('CLI end-to-end (gated on artifacts/model)', () => {
  itIfArtifacts(
    'scan --format json emits valid JSON',
    async () => {
      const program = buildProgram();
      program.exitOverride();
      const { output } = await captureStdout(async () => {
        await program.parseAsync([
          'node',
          'nullpii',
          'scan',
          'My name is John Smith',
          '--format',
          'json',
          '--model-dir',
          ARTIFACT_MODEL_DIR,
          '--backend',
          'cpu',
          '--variant',
          'int4',
        ]);
      });
      const parsed = JSON.parse(output) as { spans: ReadonlyArray<unknown> };
      expect(Array.isArray(parsed.spans)).toBe(true);
    },
    180_000,
  );

  itIfArtifacts(
    'sanitize prints text without the original PII value (--format json)',
    async () => {
      const program = buildProgram();
      program.exitOverride();
      const { output } = await captureStdout(async () => {
        await program.parseAsync([
          'node',
          'nullpii',
          'sanitize',
          'Hi, my name is John Smith and my email is john@example.com.',
          '--format',
          'json',
          '--model-dir',
          ARTIFACT_MODEL_DIR,
          '--backend',
          'cpu',
          '--variant',
          'int4',
        ]);
      });
      const parsed = JSON.parse(output) as { sanitized: string; spans: ReadonlyArray<unknown> };
      expect(parsed.spans.length).toBeGreaterThan(0);
      expect(parsed.sanitized).not.toContain('John Smith');
    },
    180_000,
  );
});
