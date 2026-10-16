#!/usr/bin/env node
// SPDX-License-Identifier: Apache-2.0
//
// Runs a built dist/ over exported tuning texts at a low threshold and
// records every final span with its score, so per-label threshold
// candidates can be screened offline before a real confirmation run.
// Screening only: lowering the threshold also changes which candidates
// dedupe keeps, so a simulated cut is an approximation (PROTOCOL.md:
// decisions come from the confirmation run).
//
//   node score_capture.mjs --dist <abs dist> --texts <tuning-texts.jsonl> --threshold 0.2 --out <spans.jsonl>

import { createReadStream, createWriteStream } from 'node:fs';
import { join } from 'node:path';
import { createInterface } from 'node:readline';
import { pathToFileURL } from 'node:url';

function parseArgs(argv) {
  const args = {};
  for (let i = 0; i < argv.length; i += 2) args[argv[i].replace(/^--/, '')] = argv[i + 1];
  for (const k of ['dist', 'texts', 'threshold', 'out']) {
    if (!args[k]) throw new Error(`--${k} is required`);
  }
  return args;
}

const args = parseArgs(process.argv.slice(2));
const { NullPii } = await import(pathToFileURL(join(args.dist, 'index.js')).href);
const np = new NullPii({ backend: 'cpu', threshold: Number(args.threshold) });
const out = createWriteStream(args.out);
let n = 0;
for await (const line of createInterface({ input: createReadStream(args.texts) })) {
  if (line.trim() === '') continue;
  const row = JSON.parse(line);
  const r = await np.sanitize(row.text);
  np.destroySession(r.sessionId);
  const spans = r.spans.map((s) => [s.start, s.end, s.label, s.score]);
  out.write(`${JSON.stringify({ dataset: row.dataset, idx: row.idx, spans })}\n`);
  n += 1;
}
out.end();
await np.dispose();
process.stdout.write(`${JSON.stringify({ docs: n, threshold: Number(args.threshold) })}\n`);
