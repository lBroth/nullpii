// SPDX-License-Identifier: Apache-2.0
/**
 * Multi-backend throughput benchmark on bundled artifacts.
 *
 * Run with: `npx tsx test/backend/benchmark.ts`
 * (requires `packages/convert/artifacts/model` to be present locally).
 */
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { CpuBackend } from '../../src/backend/cpu-backend.js';
import { MpsBackend } from '../../src/backend/mps-backend.js';
import type { BackendProvider, ModelVariant } from '../../src/types/index.js';

const MODEL_DIR = resolve(
  new URL('../../packages/convert/artifacts/model', import.meta.url).pathname,
);
const SEQ_LENGTHS = [128, 256, 512];
const RUNS_PER_LEN = 3;

if (!existsSync(MODEL_DIR)) {
  process.stderr.write(`benchmark: artifacts not found at ${MODEL_DIR}\n`);
  process.exit(1);
}

interface Bench {
  readonly label: string;
  readonly variant: ModelVariant;
  readonly factory: () => BackendProvider;
}

const benches: Bench[] = [
  { label: 'CPU int8', variant: 'int8', factory: () => new CpuBackend(MODEL_DIR, 'int8') },
];
if (process.platform === 'darwin') {
  benches.push({
    label: 'MPS fp16',
    variant: 'fp16',
    factory: () => new MpsBackend(MODEL_DIR, 'fp16'),
  });
}

async function run(b: Bench): Promise<void> {
  const backend = b.factory();
  if (!(await backend.isAvailable())) {
    process.stdout.write(`| ${b.label} | unavailable | — | — |\n`);
    return;
  }
  await backend.init();

  for (const seqLen of SEQ_LENGTHS) {
    const inputIds = BigInt64Array.from(new Array(seqLen).fill(1n));
    const attentionMask = BigInt64Array.from(new Array(seqLen).fill(1n));
    await backend.infer({ inputIds, attentionMask }); // warmup
    let total = 0;
    for (let r = 0; r < RUNS_PER_LEN; r++) {
      const t0 = performance.now();
      await backend.infer({ inputIds, attentionMask });
      total += performance.now() - t0;
    }
    const avg = total / RUNS_PER_LEN;
    const tps = (seqLen / avg) * 1000;
    process.stdout.write(`| ${b.label} | ${seqLen} | ${avg.toFixed(1)} | ${tps.toFixed(0)} |\n`);
  }

  await backend.dispose();
}

async function main(): Promise<void> {
  process.stdout.write('| backend | seq_len | avg_latency_ms | tokens/s |\n');
  process.stdout.write('| ------- | ------- | -------------- | -------- |\n');
  for (const b of benches) await run(b);
}

main().catch((err) => {
  process.stderr.write(`benchmark failed: ${err}\n`);
  process.exit(1);
});
