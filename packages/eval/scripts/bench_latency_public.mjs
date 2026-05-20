#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Latency bench for the public `nullpii` runtime (the npm-published
// surface). Measures `np.sanitize()` wall time across input sizes,
// with a separate cold-start figure (first call, includes ONNX load).
//
// Run from repo root:
//   NULLPII_MODEL_DIR=/abs/path/to/model node packages/eval/scripts/bench_latency_public.mjs
//
// Writes `packages/eval/published-bench/latency.{json,md}`.

import { writeFileSync, readFileSync } from 'node:fs';
import { performance } from 'node:perf_hooks';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import { NullPii } from '../../../dist/index.js';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..', '..');
const OUT_DIR = join(ROOT, 'packages', 'eval', 'published-bench');

const SIZES = [100, 1000, 10000];
const N_PER_SIZE = 50;
const WARMUPS = 5;
const SEED = 42;

// Reproducible PII-bearing input padded to target length. Same PII
// pattern across sizes so detection workload is comparable; padding is
// neutral filler to keep the model honest about chunking cost.
const PII_BLOCK =
  'Email John Smith at john.smith@acme.io about invoice INV-2024-0042. ' +
  'Bob Jones replied from bob@example.com referencing Jane Doe.';
const FILLER =
  'The quarterly report covers operational metrics, cost analysis, ' +
  'and strategic alignment with the broader portfolio of initiatives. ';

function rng(seed) {
  let s = seed;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

function makeInput(targetLen, rand) {
  let s = PII_BLOCK;
  while (s.length < targetLen) {
    const chunk = rand() < 0.3 ? PII_BLOCK : FILLER;
    s += ' ' + chunk;
  }
  return s.slice(0, targetLen);
}

function pct(sorted, p) {
  const idx = Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length));
  return sorted[idx];
}

async function main() {
  const np = new NullPii({ backend: 'cpu' });
  const rand = rng(SEED);

  // Cold start: time the first sanitize end-to-end (includes model load).
  const coldInput = makeInput(1000, rand);
  const coldStart = performance.now();
  const r0 = await np.sanitize(coldInput);
  const coldMs = performance.now() - coldStart;
  np.destroySession(r0.sessionId);

  const results = {};
  for (const size of SIZES) {
    // Warmup — discard.
    for (let i = 0; i < WARMUPS; i++) {
      const t = makeInput(size, rand);
      const r = await np.sanitize(t);
      np.destroySession(r.sessionId);
    }
    const samples = [];
    for (let i = 0; i < N_PER_SIZE; i++) {
      const t = makeInput(size, rand);
      const t0 = performance.now();
      const r = await np.sanitize(t);
      const dt = performance.now() - t0;
      samples.push(dt);
      np.destroySession(r.sessionId);
    }
    samples.sort((a, b) => a - b);
    results[size] = {
      n: N_PER_SIZE,
      p50_ms: +pct(samples, 50).toFixed(1),
      p95_ms: +pct(samples, 95).toFixed(1),
      p99_ms: +pct(samples, 99).toFixed(1),
      mean_ms: +(samples.reduce((a, b) => a + b, 0) / samples.length).toFixed(1),
      min_ms: +samples[0].toFixed(1),
      max_ms: +samples[samples.length - 1].toFixed(1),
    };
  }

  await np.dispose();

  const json = {
    machine: 'M5 Pro CPU',
    backend: 'cpu',
    runtime: process.version,
    date: new Date().toISOString().slice(0, 10),
    cold_start_ms: +coldMs.toFixed(1),
    by_size_chars: results,
  };
  writeFileSync(join(OUT_DIR, 'latency.json'), JSON.stringify(json, null, 2) + '\n');

  let md = '# Public-runtime latency\n\n';
  md += `M5 Pro CPU · Node ${process.version} · ${json.date}\n\n`;
  md += 'Cold start (first `sanitize()` incl. ONNX load + warmup): **' + json.cold_start_ms + ' ms**\n\n';
  md += '| Input size (chars) | n | p50 ms | p95 ms | p99 ms | mean ms |\n';
  md += '|---:|---:|---:|---:|---:|---:|\n';
  for (const size of SIZES) {
    const r = results[size];
    md += `| ${size.toLocaleString()} | ${r.n} | ${r.p50_ms} | ${r.p95_ms} | ${r.p99_ms} | ${r.mean_ms} |\n`;
  }
  md += '\nMeasured with `NullPii({ backend: "cpu" })` against the\n';
  md += 'published `lBroth/nullpii` ONNX. Per-sample input is a\n';
  md += 'reproducible mix of PII + neutral filler padded to the target\n';
  md += 'size; first 5 calls per size are discarded as warmup.\n';
  writeFileSync(join(OUT_DIR, 'latency.md'), md);

  console.log(JSON.stringify(json, null, 2));
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
