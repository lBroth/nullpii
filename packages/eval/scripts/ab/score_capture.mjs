#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Runs a built dist/ over exported texts and records every final span.
//
// Two uses:
//   - Threshold screening: pass --threshold to run below the default and
//     keep span scores (--out spans.jsonl). A simulated cut is an
//     approximation, because a lower threshold also changes what dedupe
//     keeps; decisions come from a confirmation run (PROTOCOL.md).
//   - Candidate evaluation without bench_full: --checkpoints <dir> --tool
//     <name> writes bench_full-format checkpoints (<tool>-<dataset>.jsonl)
//     for char_metrics.py, from any dist directory. A candidate can then
//     be measured while another run holds the worktree's dist/.
//
//   node score_capture.mjs --dist <abs dist> --texts <texts.jsonl> [--threshold 0.2] --out <spans.jsonl>
//   node score_capture.mjs --dist <abs dist> --texts <texts.jsonl> --checkpoints <dir> --tool <name>
//   add --model-dir <dir> to load a model other than the cached default (e.g. a quantized variant)

import { createReadStream, createWriteStream, mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) args[argv[i].replace(/^--/, '')] = argv[i + 1];
  for (const k of ['dist', 'texts']) {
    if (!args[k]) throw new Error(`--${k} is required`);
  }
  if (!args.out && !(args.checkpoints && args.tool)) {
    throw new Error('pass --out <file>, or --checkpoints <dir> with --tool <name>');
  }
  return args;
}

function checkpointSink(dir, tool) {
  mkdirSync(dir, { recursive: true });
  const streams = new Map();
  return {
    write(row, spans) {
      if (!streams.has(row.dataset)) {
        streams.set(row.dataset, createWriteStream(join(dir, `${tool}-${row.dataset}.jsonl`)));
      }
      const triples = spans.map(([s, e, label]) => [s, e, label]);
      streams.get(row.dataset).write(`${JSON.stringify({ idx: row.idx, spans: triples })}\n`);
    },
    end() {
      for (const s of streams.values()) s.end();
    },
  };
}

function spanSink(path) {
  const out = createWriteStream(path);
  return {
    write(row, spans) {
      out.write(`${JSON.stringify({ dataset: row.dataset, idx: row.idx, spans })}\n`);
    },
    end() {
      out.end();
    },
  };
}

const args = parseArgs(process.argv.slice(2));
const { NullPii } = await import(pathToFileURL(join(args.dist, 'index.js')).href);
const config = {
  backend: 'cpu',
  ...(args.threshold !== undefined && { threshold: Number(args.threshold) }),
  ...(args['model-dir'] !== undefined && { modelDir: args['model-dir'] }),
};
const np = new NullPii(config);
const sink = args.out ? spanSink(args.out) : checkpointSink(args.checkpoints, args.tool);
let n = 0;
for await (const line of createInterface({ input: createReadStream(args.texts) })) {
  if (line.trim() === '') continue;
  const row = JSON.parse(line);
  const r = await np.sanitize(row.text);
  np.destroySession(r.sessionId);
  sink.write(row, r.spans.map((s) => [s.start, s.end, s.label, s.score]));
  n += 1;
}
sink.end();
await np.dispose();
process.stdout.write(`${JSON.stringify({ docs: n, ...config })}\n`);
