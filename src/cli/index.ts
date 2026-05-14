// SPDX-License-Identifier: Apache-2.0

import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { Command } from 'commander';
import { NullPiiError } from '../errors.js';
import { registerDoctor } from './commands/doctor.js';
import { registerModels } from './commands/models.js';
import { registerPrefetch } from './commands/prefetch.js';
import { registerSanitize } from './commands/sanitize.js';
import { registerScan } from './commands/scan.js';

function readPackageVersion(): string {
  // fileURLToPath, not URL.pathname — the latter yields "/C:/..." on Windows.
  const here = dirname(fileURLToPath(import.meta.url));
  const pkgPath = join(here, '..', '..', 'package.json');
  const pkg = JSON.parse(readFileSync(pkgPath, 'utf-8')) as { version?: string };
  if (!pkg.version) throw new Error(`package.json at ${pkgPath} missing 'version' field`);
  return pkg.version;
}

export function buildProgram(): Command {
  const program = new Command();
  program
    .name('nullpii')
    .description('Sanitize PII from text locally with a reversible vault.')
    .version(readPackageVersion(), '-v, --version', 'print the nullpii version');

  registerScan(program);
  registerSanitize(program);
  registerModels(program);
  registerPrefetch(program);
  registerDoctor(program);
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
