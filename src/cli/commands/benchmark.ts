import { performance } from 'node:perf_hooks';
import chalk from 'chalk';
import type { Command } from 'commander';
import { selectBackend } from '../../router.js';
import type { BackendName, BackendProvider, ModelVariant } from '../../types/index.js';

const SEQ_LENGTHS = [128, 256, 512] as const;
const RUNS = 3;

const CANDIDATES: ReadonlyArray<{ backend: Exclude<BackendName, 'auto'>; variant: ModelVariant }> =
  [
    { backend: 'cpu', variant: 'int4' },
    { backend: 'mps', variant: 'int4' },
    { backend: 'cuda', variant: 'int4' },
  ];

export function registerBenchmark(program: Command): void {
  program
    .command('benchmark')
    .description('run a tokens/sec benchmark on every available backend')
    .option('--model-dir <path>', 'override the cached model directory')
    .action((options: { modelDir?: string }) => runBenchmark(options.modelDir));
}

async function runBenchmark(modelDir: string | undefined): Promise<void> {
  if (modelDir === undefined || modelDir === '') {
    process.stderr.write(chalk.yellow('warning: --model-dir is required\n'));
    return;
  }
  process.stdout.write('| backend | seq_len | avg_ms | tok/s |\n');
  process.stdout.write('| ------- | ------- | ------ | ----- |\n');
  for (const c of CANDIDATES) {
    await tryBenchOne(c.backend, c.variant, modelDir);
  }
}

async function tryBenchOne(
  backendName: Exclude<BackendName, 'auto'>,
  variant: ModelVariant,
  modelDir: string,
): Promise<void> {
  try {
    const backend = await selectBackend(modelDir, { backend: backendName, variant });
    if (!(await backend.isAvailable())) return;
    await backend.init();
    for (const seqLen of SEQ_LENGTHS) await printRow(backend, backendName, seqLen);
    await backend.dispose();
  } catch (err) {
    if (err instanceof Error) {
      process.stderr.write(chalk.dim(`${backendName} unavailable: ${err.message}\n`));
    }
  }
}

async function printRow(
  backend: BackendProvider,
  backendName: string,
  seqLen: number,
): Promise<void> {
  const ids = BigInt64Array.from(new Array(seqLen).fill(1n));
  const mask = BigInt64Array.from(new Array(seqLen).fill(1n));
  await backend.infer({ inputIds: ids, attentionMask: mask });
  let total = 0;
  for (let r = 0; r < RUNS; r++) {
    const t0 = performance.now();
    await backend.infer({ inputIds: ids, attentionMask: mask });
    total += performance.now() - t0;
  }
  const avg = total / RUNS;
  process.stdout.write(
    `| ${backendName} | ${seqLen} | ${avg.toFixed(1)} | ${((seqLen / avg) * 1000).toFixed(0)} |\n`,
  );
}
