// SPDX-License-Identifier: Apache-2.0
import { existsSync, statSync } from 'node:fs';
import { freemem, totalmem } from 'node:os';
import chalk from 'chalk';
import type { Command } from 'commander';
import { CudaBackend } from '../../backend/cuda-backend.js';
import { MpsBackend } from '../../backend/mps-backend.js';
import { ModelManager, defaultCacheDir } from '../../model-manager.js';

export function registerDoctor(program: Command): void {
  program
    .command('doctor')
    .description('probe environment + model cache + backends; exit 0 if healthy')
    .action(runDoctor);
}

async function runDoctor(): Promise<void> {
  let exit = 0;
  for (const check of CHECKS) {
    const ok = await check();
    if (!ok) exit = 1;
  }
  process.exit(exit);
}

const CHECKS: ReadonlyArray<() => Promise<boolean>> = [
  checkNodeVersion,
  checkCacheDir,
  checkModelArtifacts,
  checkMemory,
  checkBackends,
];

function ok(label: string, msg: string): true {
  process.stdout.write(`${chalk.green('✔')} ${label}  ${chalk.dim(msg)}\n`);
  return true;
}
function warn(label: string, msg: string): true {
  process.stdout.write(`${chalk.yellow('!')} ${label}  ${chalk.dim(msg)}\n`);
  return true;
}
function fail(label: string, msg: string): false {
  process.stdout.write(`${chalk.red('✖')} ${label}  ${chalk.dim(msg)}\n`);
  return false;
}

async function checkNodeVersion(): Promise<boolean> {
  const major = Number.parseInt(process.versions.node.split('.')[0] ?? '0', 10);
  return major >= 22
    ? ok('node version', `${process.version}`)
    : fail('node version', `${process.version} — need >=22`);
}

async function checkCacheDir(): Promise<boolean> {
  const dir = defaultCacheDir();
  return existsSync(dir)
    ? ok('cache dir', dir)
    : warn('cache dir', `${dir} (will be created on first download)`);
}

async function checkModelArtifacts(): Promise<boolean> {
  const dir = new ModelManager().modelDir;
  if (!existsSync(dir))
    return warn('model artifacts', 'not yet downloaded — run `nullpii prefetch`');
  const tok = `${dir}/tokenizer.json`;
  return existsSync(tok)
    ? ok('model artifacts', `${dir}`)
    : fail('model artifacts', `${dir} present but tokenizer.json missing`);
}

async function checkMemory(): Promise<boolean> {
  const free = Math.round(freemem() / 1024 / 1024);
  const total = Math.round(totalmem() / 1024 / 1024);
  return free >= 1024
    ? ok('free memory', `${free} MB / ${total} MB`)
    : warn('free memory', `${free} MB free — model load may swap`);
}

async function checkBackends(): Promise<boolean> {
  const probes: ReadonlyArray<readonly [string, () => Promise<boolean>]> = [
    ['cpu (always)', () => Promise.resolve(true)],
    ['mps (Apple)', () => new MpsBackend('/').isAvailable()],
    ['cuda (NVIDIA)', () => new CudaBackend('/').isAvailable()],
  ];
  let any = false;
  for (const [label, probe] of probes) {
    if (await probe()) {
      ok(`backend ${label}`, 'available');
      any = true;
    } else warn(`backend ${label}`, 'unavailable on this host');
  }
  return any;
}

const _ = statSync; // satisfy noUnusedLocals on conditional import paths
void _;
