import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { Command } from 'commander';
import { NullPiiError } from '../errors.js';
import { registerBenchmark } from './commands/benchmark.js';
import { registerDoctor } from './commands/doctor.js';
import { registerModels } from './commands/models.js';
import { registerPrefetch } from './commands/prefetch.js';
import { registerRestore } from './commands/restore.js';
import { registerSanitize } from './commands/sanitize.js';
import { registerScan } from './commands/scan.js';

function readPackageVersion(): string {
  try {
    const pkgPath = join(new URL('../..', import.meta.url).pathname, 'package.json');
    const pkg = JSON.parse(readFileSync(pkgPath, 'utf-8')) as { version?: string };
    return pkg.version ?? '0.0.0';
  } catch {
    return '0.0.0';
  }
}

export function buildProgram(): Command {
  const program = new Command();
  program
    .name('nullpii')
    .description('Sanitize PII from text locally with a reversible vault.')
    .version(readPackageVersion(), '-v, --version', 'print the nullpii version');

  registerScan(program);
  registerSanitize(program);
  registerRestore(program);
  registerModels(program);
  registerPrefetch(program);
  registerDoctor(program);
  registerBenchmark(program);
  return program;
}

export async function run(argv: readonly string[] = process.argv): Promise<number> {
  const program = buildProgram();
  try {
    await program.parseAsync([...argv]);
    return 0;
  } catch (err) {
    return reportError(err);
  }
}

function reportError(err: unknown): number {
  if (err instanceof NullPiiError) {
    process.stderr.write(`error: ${err.message}\n`);
    return 1;
  }
  if (err instanceof Error) {
    process.stderr.write(`error: ${err.message}\n`);
    return 1;
  }
  process.stderr.write('error: unknown failure\n');
  return 1;
}
