#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// A/B harness for the loop described in PROTOCOL.md. Runs against any
// built `dist/` so a baseline and a candidate are measured by the same
// code on the same inputs.
//
//   node harness.mjs latency     --dist <abs dist> --out <file.json> [--label name]
//   node harness.mjs fingerprint --dist <abs dist> --out <file.json>
//   node harness.mjs cold        --dist <abs dist> --out <file.json>
//   node harness.mjs dump-corpus --out <file.jsonl>   (inputs for competitor_latency.py)
//
// Engine config comes from the AB_CONFIG env var (JSON, merged over
// `{ backend: 'cpu' }`), so a config-only variant needs no code change.
// Corpora are built from repository files at a fixed commit, so every
// run on every branch sees identical inputs.

import { execFileSync, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { performance } from 'node:perf_hooks';
import { fileURLToPath, pathToFileURL } from 'node:url';

const REPO = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..', '..', '..');
const CORPUS_COMMIT = '5130a64';
const DATASETS = join(REPO, 'packages', 'eval', 'datasets');

const SIZES = [2_000, 30_000, 100_000];
const CALLS_PER_KIND = { 2000: 10, 30000: 2, 100000: 1 };
const ROUNDS = 3;
const WARMUP_SIZES = [2_000, 2_000, 2_000, 30_000];
const WINDOW_STRIDE = 0.37;
const COLD_RUNS = 3;
const COLD_INPUT_CHARS = 1_000;

const FP_BENCH_ROWS = 600;
const FP_PRESIDIO_ROWS = 300;
const FP_LEGAL_DOCS = 20;
export const FP_SHAPED_CHARS = 30_000;
/** Window index the fingerprint corpus uses for its shaped documents. */
export const FP_SHAPED_WINDOW = 7;

function git(args) {
  return execFileSync('git', args, { cwd: REPO, encoding: 'utf-8', maxBuffer: 1 << 28 });
}

function filesAt(paths, ext) {
  return git(['ls-tree', '-r', '--name-only', CORPUS_COMMIT, ...paths])
    .split('\n')
    .filter((p) => p.endsWith(ext))
    .sort();
}

function concatFiles(paths, commentPrefix) {
  return paths
    .map((p) => `${commentPrefix} ---- ${p} ----\n${git(['show', `${CORPUS_COMMIT}:${p}`])}`)
    .join('\n');
}

function jsonlTexts(file) {
  return readFileSync(join(DATASETS, file), 'utf-8')
    .split('\n')
    .filter((l) => l.trim() !== '')
    .map((l) => JSON.parse(l).text);
}

/** Legal text of the latency corpus (kept stable so timings stay comparable). */
const LATENCY_LEGAL = 'tab-echr-test.jsonl';
/** Legal text of the fingerprint corpus: TAB dev, never a report document
 * (PROTOCOL rule change 9, item 7). */
const FINGERPRINT_LEGAL = 'tab-echr-dev.jsonl';

/** Claude-Code-shaped corpora: what Read / Bash / Grep / MCP put in context. */
export function buildKinds(legalFile = LATENCY_LEGAL) {
  return {
    code: concatFiles(filesAt(['src', 'packages/gateway/src'], '.ts'), '//'),
    python: concatFiles(filesAt(['packages/eval'], '.py'), '#'),
    markdown: concatFiles(filesAt([], '.md'), '<!--'),
    json: git(['show', `${CORPUS_COMMIT}:package-lock.json`]),
    gitlog: git(['log', '--stat', '-400', CORPUS_COMMIT]),
    legal: jsonlTexts(legalFile).join('\n\n'),
  };
}

/** Deterministic, distinct windows: call `i` never repeats call `i-1`'s text. */
export function windowOf(text, size, i) {
  const span = Math.max(1, text.length - size);
  const start = Math.floor(i * size * WINDOW_STRIDE) % span;
  return text.slice(start, start + size);
}

function percentile(sorted, p) {
  return sorted[Math.min(sorted.length - 1, Math.floor((p / 100) * sorted.length))];
}

function median(xs) {
  const s = [...xs].sort((a, b) => a - b);
  return s[Math.floor(s.length / 2)];
}

async function loadEngine(dist) {
  const mod = await import(pathToFileURL(join(dist, 'index.js')).href);
  const extra = process.env.AB_CONFIG ? JSON.parse(process.env.AB_CONFIG) : {};
  return new mod.NullPii({ backend: 'cpu', ...extra });
}

async function timeCall(np, text) {
  const t0 = performance.now();
  const r = await np.sanitize(text);
  const ms = performance.now() - t0;
  np.destroySession(r.sessionId);
  return ms;
}

/** Every timed input, in timing order. The latency mode times exactly
 * these and `dump-corpus` exports them, so other tools replay the same
 * texts in the same order. */
function latencyPlan(kinds) {
  const plan = WARMUP_SIZES.map((size, i) => ({
    phase: 'warmup',
    size,
    text: windowOf(kinds.code, size, 1000 + i),
  }));
  for (let round = 0; round < ROUNDS; round++) {
    for (const size of SIZES) {
      for (const [kind, text] of Object.entries(kinds).filter(([, t]) => t.length >= size)) {
        for (let call = 0; call < CALLS_PER_KIND[size]; call++) {
          plan.push({ phase: 'measure', round, size, kind, call, text: windowOf(text, size, round * 100 + call) });
        }
      }
    }
  }
  return plan;
}

async function warmup(np, plan) {
  for (const step of plan.filter((s) => s.phase === 'warmup')) await timeCall(np, step.text);
}

async function runRound(np, plan, round) {
  const out = {};
  for (const size of SIZES) {
    const times = [];
    for (const step of plan.filter((s) => s.phase === 'measure' && s.round === round && s.size === size)) {
      times.push(await timeCall(np, step.text));
    }
    times.sort((a, b) => a - b);
    out[size] = { p50: percentile(times, 50), p95: percentile(times, 95), n: times.length };
  }
  return out;
}

function dumpCorpus(args) {
  if (!args.out) throw new Error('dump-corpus needs --out <file.jsonl>');
  const plan = latencyPlan(buildKinds());
  writeFileSync(args.out, `${plan.map((s) => JSON.stringify(s)).join('\n')}\n`);
  return { mode: 'dump-corpus', inputs: plan.length };
}

async function latency(args) {
  const np = await loadEngine(args.dist);
  const plan = latencyPlan(buildKinds());
  await warmup(np, plan);
  const rounds = [];
  for (let r = 0; r < ROUNDS; r++) rounds.push(await runRound(np, plan, r));
  const bySize = {};
  for (const size of SIZES) {
    const p50s = rounds.map((r) => r[size].p50);
    const med = median(p50s);
    bySize[size] = {
      p50: med,
      p95: median(rounds.map((r) => r[size].p95)),
      msPer1k: (med / size) * 1000,
      spreadPct: ((Math.max(...p50s) - Math.min(...p50s)) / med) * 100,
      roundP50s: p50s,
      callsPerRound: rounds[0][size].n,
    };
  }
  await np.dispose();
  return { mode: 'latency', bySize };
}

function fingerprintDocs(kinds) {
  const bench = jsonlTexts('nullpii-bench.jsonl').slice(0, FP_BENCH_ROWS);
  const presidio = jsonlTexts('presidio-synthetic.jsonl').slice(0, FP_PRESIDIO_ROWS);
  const legal = jsonlTexts(FINGERPRINT_LEGAL).slice(0, FP_LEGAL_DOCS);
  const shaped = Object.entries(kinds).map(([k, t]) => [`shaped:${k}`, windowOf(t, FP_SHAPED_CHARS, FP_SHAPED_WINDOW)]);
  return [
    ...bench.map((t, i) => [`bench:${i}`, t]),
    ...presidio.map((t, i) => [`presidio:${i}`, t]),
    ...legal.map((t, i) => [`legal:${i}`, t]),
    ...shaped,
  ];
}

/** Order-independent form: the engine's span order is not part of its output contract. */
export function canonicalSpans(spans) {
  return [...spans].sort((a, b) => a[1] - b[1] || a[2] - b[2] || (a[0] < b[0] ? -1 : 1));
}

/** Count encoder calls whose window was cut by the subword budget. Patches
 * the prototype of the same module instance the engine imports. */
async function cutCounter(dist) {
  const { GlinerTokenizer } = await import(pathToFileURL(join(dist, 'gliner-tokenizer.js')).href);
  const counter = { cuts: 0 };
  const encode = GlinerTokenizer.prototype.encode;
  GlinerTokenizer.prototype.encode = async function (...a) {
    const r = await encode.apply(this, a);
    if (r.truncated) counter.cuts += 1;
    return r;
  };
  return counter;
}

async function fingerprint(args) {
  const counter = await cutCounter(args.dist);
  const np = await loadEngine(args.dist);
  const docs = [];
  const hash = createHash('sha256');
  for (const [id, text] of fingerprintDocs(buildKinds(FINGERPRINT_LEGAL))) {
    counter.cuts = 0;
    const r = await np.sanitize(text);
    np.destroySession(r.sessionId);
    const spans = canonicalSpans(r.spans.map((s) => [s.label, s.start, s.end]));
    hash.update(`${id}\t${JSON.stringify(spans)}\n`);
    docs.push({ id, spans, cutWindows: counter.cuts });
  }
  await np.dispose();
  return { mode: 'fingerprint', sha256: hash.digest('hex'), docs };
}

async function coldChild(args) {
  const np = await loadEngine(args.dist);
  const text = windowOf(buildKinds().code, COLD_INPUT_CHARS, 3);
  await np.sanitize(text);
  process.stdout.write(`${JSON.stringify({ msSinceProcessStart: performance.now() })}\n`);
  await np.dispose();
}

function cold(args) {
  const runs = [];
  for (let i = 0; i < COLD_RUNS; i++) {
    const r = spawnSync(process.execPath, [fileURLToPath(import.meta.url), 'cold-child', '--dist', args.dist], {
      encoding: 'utf-8',
      env: process.env,
    });
    if (r.status !== 0) throw new Error(`cold child failed: ${r.stderr}`);
    runs.push(JSON.parse(r.stdout.trim().split('\n').pop()).msSinceProcessStart);
  }
  return { mode: 'cold', runsMs: runs, medianMs: median(runs) };
}

function parseArgs(argv) {
  const [mode, ...rest] = argv;
  const args = { mode };
  for (let i = 0; i < rest.length; i += 2) args[rest[i].replace(/^--/, '')] = rest[i + 1];
  if (!args.dist && mode !== 'dump-corpus') throw new Error('--dist <abs path to dist/> is required');
  return args;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.mode === 'cold-child') return coldChild(args);
  const runners = { latency, fingerprint, cold, 'dump-corpus': dumpCorpus };
  const run = runners[args.mode];
  if (!run) throw new Error(`unknown mode ${args.mode}`);
  const result = {
    ...(await run(args)),
    label: args.label ?? null,
    dist: args.dist,
    config: process.env.AB_CONFIG ?? null,
    node: process.version,
    at: new Date().toISOString(),
  };
  const json = JSON.stringify(result, null, 2);
  if (args.out && result.mode !== 'dump-corpus') writeFileSync(args.out, `${json}\n`);
  const summary = result.mode === 'fingerprint' ? { sha256: result.sha256, docs: result.docs.length } : result;
  if (result.mode === 'dump-corpus') {
    process.stdout.write(`${JSON.stringify(summary)}\n`);
    return;
  }
  process.stdout.write(`${JSON.stringify(summary.bySize ?? summary)}\n`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
